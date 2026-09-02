from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from math import ceil
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.base import Base
from app.db.session import create_session_factory
from app.domain.consensus import build_pricing_analysis
from app.domain.identity import Principal
from app.domain.portfolio_engine import (
    INFORMATIONAL_PRICING_WARNINGS,
    MAXIMUM_ACTIONABLE_POSITIVE_AMERICAN_ODDS,
)
from app.domain.pricing import PricingObservation
from app.persistence.pricing_base import PricingObservationQuery
from app.persistence.pricing_repository import SqlAlchemyPricingObservationRepository
from app.providers.base import MarketDataProvider, ProviderFetchResult
from app.providers.odds_api import TheOddsApiProvider
from app.services.model_registry_bootstrap import bootstrap_ncaaf_registry
from app.services.pricing_service import build_pricing_policy
from app.time import commence_datetime_utc

MARKETS = ["h2h", "spreads", "totals"]
CANONICAL_MARKETS = ["moneyline", "spread", "total"]


class _SingleFetchReplayProvider(MarketDataProvider):
    configured = True

    def __init__(self, fetch: ProviderFetchResult) -> None:
        self.fetch = fetch
        self.calls = 0

    def fetch_current_odds(self, sport: str, markets: list[str]) -> ProviderFetchResult:
        if sport != "NCAAF" or markets != MARKETS or self.calls:
            raise RuntimeError("Live verification replay provider is single-use")
        self.calls += 1
        return self.fetch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make one current NCAAF provider request and verify pricing in an isolated database."
    )
    parser.add_argument("--execute", action="store_true", help="Required acknowledgement for the one live request")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required; this command intentionally performs one billable provider request")

    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    os.environ.setdefault("APP_API_KEY", "isolated-live-verification")
    settings = Settings.from_env()
    provider = TheOddsApiProvider(
        settings.odds_api_key,
        timeout_seconds=settings.provider_timeout_seconds,
        max_retries=0,
        backoff_seconds=0,
        cache_ttl_seconds=0,
        low_quota_threshold=settings.provider_low_quota_threshold,
    )
    fetch = provider.fetch_current_odds("NCAAF", MARKETS)  # The only live provider request.
    report = verify_fetch(fetch, settings)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["acceptance_passed"] else 2


def verify_fetch(fetch: ProviderFetchResult, settings: Settings) -> dict[str, Any]:
    """Exercise persistence, latest-state pricing, recommendations, and Watchlist without production state."""
    with tempfile.TemporaryDirectory(prefix="polaris-live-verification-") as directory:
        database = Path(directory) / "verification.sqlite3"
        isolated = replace(
            settings,
            database_url=f"sqlite+pysqlite:///{database.as_posix()}",
            app_api_key="isolated-live-verification",
            app_owner_id="isolated-live-verification",
            data_dir=Path(directory),
        )
        replay = _SingleFetchReplayProvider(fetch)
        create_app = _load_create_app(isolated)
        application = create_app(settings=isolated, provider=replay, clock=lambda: fetch.requested_at)
        assert application.state.database_engine is not None
        Base.metadata.create_all(application.state.database_engine)
        recommendation_service = application.state.recommendation_service
        if recommendation_service is None:
            raise RuntimeError("Recommendation service unavailable in isolated verification")
        bootstrap_ncaaf_registry(recommendation_service.registry_repository)
        principal = Principal("isolated-live-verification", "Isolated Live Verification")
        refresh = application.state.market_refresh_service.refresh(principal, portfolio_id="verification")
        watchlist = recommendation_service.watchlist(principal, "verification", as_of=fetch.requested_at)
        if replay.calls != 1:
            raise RuntimeError("Replay provider call count was not exactly one")

        session_factory = create_session_factory(application.state.database_engine)
        pricing_repository = SqlAlchemyPricingObservationRepository(session_factory)
        upcoming = [
            (game, kickoff)
            for game in fetch.games
            if (kickoff := commence_datetime_utc(game.commence_time)) is not None and kickoff > fetch.requested_at
        ]
        dates = sorted({kickoff.date() for _, kickoff in upcoming})
        aggregate: Counter[str] = Counter()
        analyses = []
        all_rows: list[PricingObservation] = []
        observation_quote_age: dict[str, int] = {}
        for slate_date in dates:
            analysis = application.state.pricing_service.analyze(
                leagues=["NCAAF"],
                market_types=CANONICAL_MARKETS,
                as_of=fetch.requested_at,
                event_date=slate_date,
                top_n=50,
            )
            analyses.append(analysis)
            aggregate.update(analysis.funnel)
            rows = pricing_repository.list_for_pricing(
                PricingObservationQuery(
                    leagues=("NCAAF",),
                    market_types=("moneyline", "spread", "total"),
                    as_of=fetch.requested_at,
                    event_date=slate_date,
                )
            )
            all_rows.extend(rows)
            for row in rows:
                observation_quote_age[str(row.observation_id)] = max(
                    0,
                    int((row.snapshot_requested_at - row.observed_at).total_seconds()),
                )

        qualified = [
            item
            for decision in refresh["decisions"]
            for item in recommendation_service.list(
                principal,
                "verification",
                slate_date=decision["slate_date"],
            )
            if item["kind"] == "straight"
        ]
        all_quote_ages = sorted(
            max(0, int((row.snapshot_requested_at - row.observed_at).total_seconds())) for row in all_rows
        )
        supported_rows = [row for row in all_rows if row.sportsbook_key in settings.pricing_supported_books]
        aggregate_gauges = {
            "supported_books_seen": len({row.sportsbook_key for row in supported_rows}),
            "unsupported_books_seen": len(
                {row.sportsbook_key for row in all_rows if row.sportsbook_key not in settings.pricing_supported_books}
            ),
            "snapshot_age_seconds": max(
                (max(0, int((fetch.requested_at - row.snapshot_requested_at).total_seconds())) for row in all_rows),
                default=0,
            ),
            "provider_quote_age_min_seconds": min(all_quote_ages, default=0),
            "provider_quote_age_median_seconds": _percentile(all_quote_ages, 0.5),
            "provider_quote_age_p90_seconds": _percentile(all_quote_ages, 0.9),
            "provider_quote_age_max_seconds": max(all_quote_ages, default=0),
        }
        for key, value in aggregate_gauges.items():
            aggregate[key] = value
        closest = _closest_positive_ev(analyses, observation_quote_age, settings)
        saturday_date = min(
            (
                row.scheduled_start_utc.astimezone(UTC).date()
                for row in all_rows
                if row.scheduled_start_utc.astimezone(UTC).weekday() == 5
            ),
            default=None,
        )
        saturday_rows = tuple(
            row
            for row in all_rows
            if saturday_date is not None and row.scheduled_start_utc.astimezone(UTC).date() == saturday_date
        )
        saturday_analysis = build_pricing_analysis(
            saturday_rows,
            as_of=fetch.requested_at,
            policy=build_pricing_policy(
                minimum_books=settings.pricing_minimum_books,
                minimum_ev=settings.pricing_minimum_ev,
                minimum_probability_edge=settings.pricing_minimum_probability_edge,
                outlier_threshold=settings.pricing_outlier_threshold,
                maximum_dispersion=settings.pricing_maximum_dispersion,
                supported_books=settings.pricing_supported_books,
                snapshot_freshness_seconds=settings.market_freshness_seconds,
                maximum_provider_quote_age_seconds=settings.provider_quote_max_age_seconds,
            ),
            top_n_per_league=50,
        )
        saturday = _saturday_summary(
            fetch,
            saturday_analysis,
            watchlist,
            qualified,
            saturday_date=saturday_date,
        )
        acceptance = (
            aggregate["eligible_observations"] > 0
            and aggregate["exact_paired_book_markets"] > 0
            and aggregate["calculable_candidate_sides"] > 0
        )
        metadata = fetch.response_metadata or {}
        requests_last = _integer(metadata.get("requests_last"))
        requests_remaining = _integer(metadata.get("requests_remaining"))
        report = {
            "acceptance_passed": acceptance,
            "integrity_status": (
                "HEALTHY WITH QUALIFIED" if acceptance and qualified else "HEALTHY PASS" if acceptance else "DEGRADED"
            ),
            "provider_calls": 1,
            "provider_quota": {
                "requests_last": requests_last,
                "requests_remaining_after": requests_remaining,
                "estimated_remaining_before": (
                    requests_remaining + requests_last
                    if requests_remaining is not None and requests_last is not None
                    else None
                ),
                "requests_used": _integer(metadata.get("requests_used")),
            },
            "events_received": len(fetch.games),
            "upcoming_events": len(upcoming),
            "saturday_games_received": saturday["games"],
            "observations_created": refresh["observations_created"],
            "pricing_funnel": dict(sorted(aggregate.items())),
            "saturday": saturday,
            "qualified_candidates": qualified,
            "closest_positive_ev_candidates": closest[:10] if not qualified else [],
            "watchlist_count": watchlist["watchlist_count"],
            "qualified_count": len(qualified),
            "ledger_or_bet_mutation": False,
        }
        application.state.database_engine.dispose()
        from app import main as main_module

        global_engine = main_module.app.state.database_engine
        if global_engine is not None and global_engine is not application.state.database_engine:
            global_engine.dispose()
        return report


def _closest_positive_ev(
    analyses: list[Any],
    quote_ages: dict[str, int],
    settings: Settings,
) -> list[dict[str, Any]]:
    values: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for analysis in analyses:
        for candidate in analysis.candidates:
            if candidate.ev_per_unit <= 0:
                continue
            blockers = list(candidate.pricing_gate_failures)
            if candidate.probability_edge < settings.portfolio_minimum_edge:
                blockers.append("below_minimum_edge")
            if candidate.ev_per_unit < settings.portfolio_minimum_ev:
                blockers.append("below_minimum_ev")
            if candidate.consensus_dispersion > settings.portfolio_maximum_dispersion:
                blockers.append("excessive_consensus_dispersion")
            if candidate.best_american_odds > MAXIMUM_ACTIONABLE_POSITIVE_AMERICAN_ODDS:
                blockers.append("outside_main_board_odds_profile")
            if set(candidate.quality_warnings) - INFORMATIONAL_PRICING_WARNINGS:
                blockers.append("pricing_quality_warning")
            blockers = sorted(set(blockers))
            distance = sum(
                (
                    (
                        max(Decimal(0), settings.portfolio_minimum_edge - candidate.probability_edge)
                        / settings.portfolio_minimum_edge
                    ),
                    (
                        max(Decimal(0), settings.portfolio_minimum_ev - candidate.ev_per_unit)
                        / settings.portfolio_minimum_ev
                    ),
                    (
                        max(Decimal(0), candidate.consensus_dispersion - settings.portfolio_maximum_dispersion)
                        / settings.portfolio_maximum_dispersion
                    ),
                ),
                start=Decimal(0),
            )
            quote_age = max(
                (quote_ages.get(str(value), 0) for value in candidate.source_observation_ids),
                default=0,
            )
            record = {
                "matchup": f"{candidate.away_team} @ {candidate.home_team}",
                "market": candidate.market_type,
                "side": candidate.selection_side,
                "sportsbook": candidate.best_sportsbook_key,
                "odds": candidate.best_american_odds,
                "point": candidate.point,
                "fair_probability": candidate.final_fair_probability,
                "implied_probability": candidate.raw_implied_probability,
                "edge": candidate.probability_edge,
                "ev": candidate.ev_per_unit,
                "books": candidate.books_contributing,
                "dispersion": candidate.consensus_dispersion,
                "provider_quote_age_seconds": quote_age,
                "quality_warnings": list(candidate.quality_warnings),
                "blockers": blockers,
            }
            values.append(
                (
                    (
                        len(blockers),
                        distance,
                        -candidate.ev_per_unit,
                        -candidate.probability_edge,
                        candidate.scheduled_start_utc,
                        str(candidate.best_executable_observation_id),
                    ),
                    record,
                )
            )
    return [record for _, record in sorted(values, key=lambda item: item[0])]


def _saturday_summary(
    fetch: ProviderFetchResult,
    analysis: Any,
    watchlist: dict[str, Any],
    qualified: list[dict[str, Any]],
    *,
    saturday_date: date | None,
) -> dict[str, Any]:
    def is_selected_saturday(value: str) -> bool:
        return saturday_date is not None and datetime.fromisoformat(value).astimezone(UTC).date() == saturday_date

    return {
        "slate_date_utc": saturday_date.isoformat() if saturday_date is not None else None,
        "games": sum(
            1
            for game in fetch.games
            if (kickoff := commence_datetime_utc(game.commence_time)) is not None
            and saturday_date is not None
            and kickoff.astimezone(UTC).date() == saturday_date
        ),
        "eligible_observations": analysis.funnel["eligible_observations"],
        "exact_paired_book_markets": analysis.funnel["exact_paired_book_markets"],
        "calculable_candidate_sides": analysis.funnel["calculable_candidate_sides"],
        "positive_ev_candidates": analysis.funnel["positive_ev_candidates"],
        "watchlist_candidates": sum(
            is_selected_saturday(item["scheduled_start"]) for item in watchlist["items"]
        ),
        "qualified_candidates": sum(
            item.get("scheduled_start") is not None
            and is_selected_saturday(item["scheduled_start"])
            for item in qualified
        ),
    }


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, ceil(len(values) * fraction) - 1))
    return values[index]


def _load_create_app(settings: Settings) -> Any:
    prior_database = os.environ.get("DATABASE_URL")
    prior_api_key = os.environ.get("APP_API_KEY")
    try:
        os.environ["DATABASE_URL"] = settings.database_url
        os.environ["APP_API_KEY"] = settings.app_api_key
        from app.main import create_app

        return create_app
    finally:
        if prior_database is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prior_database
        if prior_api_key is None:
            os.environ.pop("APP_API_KEY", None)
        else:
            os.environ["APP_API_KEY"] = prior_api_key


if __name__ == "__main__":
    raise SystemExit(main())
