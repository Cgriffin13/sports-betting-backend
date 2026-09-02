from __future__ import annotations

from datetime import UTC, date, datetime
from threading import Lock
from typing import Any, Protocol

from app.domain.identity import Principal
from app.domain.recommendation_timing import classify_recommendation_timing
from app.providers.base import MarketDataProviderError
from app.services.market_ingestion_service import MarketIngestionResult
from app.time import commence_datetime_utc

REFRESH_MARKETS = ["h2h", "spreads", "totals"]
RECOMMENDATION_MARKETS = ["moneyline", "spread", "total"]


class RefreshOddsService(Protocol):
    @property
    def provider_configured(self) -> bool: ...

    def ingest_current(self, *, sport: str, markets: list[str]) -> MarketIngestionResult: ...


class RefreshRecommendationService(Protocol):
    def analyze(self, principal: Principal, **values: Any) -> dict[str, Any]: ...


class MarketRefreshUnavailableError(RuntimeError):
    pass


class MarketRefreshInProgressError(RuntimeError):
    pass


class MarketRefreshService:
    """Explicit, bounded NCAAF market refresh and recommendation orchestration."""

    def __init__(
        self,
        odds_service: RefreshOddsService,
        recommendation_service: RefreshRecommendationService,
    ) -> None:
        self.odds_service = odds_service
        self.recommendation_service = recommendation_service
        self._lock = Lock()

    def refresh(self, principal: Principal, *, portfolio_id: str, top_n: int = 10) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise MarketRefreshInProgressError("A market refresh is already in progress")
        try:
            if not self.odds_service.provider_configured:
                raise MarketRefreshUnavailableError("The odds provider is not configured on the server")
            try:
                ingestion = self.odds_service.ingest_current(sport="NCAAF", markets=REFRESH_MARKETS)
            except MarketDataProviderError as exc:
                raise MarketRefreshUnavailableError(exc.public_message) from exc
            if ingestion.persisted is None:
                raise MarketRefreshUnavailableError("Market persistence is unavailable")
            as_of = _utc(ingestion.fetch.requested_at)
            upcoming = [
                (game, kickoff)
                for game in ingestion.fetch.games
                if (kickoff := commence_datetime_utc(game.commence_time)) is not None and kickoff > as_of
            ]
            by_date: dict[date, list[datetime]] = {}
            observations_by_date: dict[date, int] = {}
            for game, kickoff in upcoming:
                by_date.setdefault(kickoff.date(), []).append(kickoff)
                observations_by_date[kickoff.date()] = observations_by_date.get(kickoff.date(), 0) + len(
                    game.offers
                )
            decisions: list[dict[str, Any]] = []
            for slate_date, kickoffs in sorted(by_date.items()):
                timing = classify_recommendation_timing(as_of, min(kickoffs))
                decision = self.recommendation_service.analyze(
                    principal,
                    portfolio_id=portfolio_id,
                    slate_date=slate_date,
                    as_of=as_of,
                    market_types=RECOMMENDATION_MARKETS,
                    top_n=top_n,
                    games_received=len(kickoffs),
                    observations_received=observations_by_date[slate_date],
                )
                decisions.append(
                    {
                        "slate_date": slate_date,
                        "first_kickoff": min(kickoffs),
                        **timing,
                        "decision_run_id": decision["decision_run_id"],
                        "qualified_straights": len(decision["straight_recommendations"]),
                        "games_analyzed": int(decision.get("analysis_summary", {}).get("games_analyzed", len(kickoffs))),
                        "watchlist_count": int(decision.get("watchlist_count", 0)),
                        "parlay_status": (
                            "QUALIFIED" if "recommendation_id" in decision["parlay_of_the_day"] else "PASS"
                        ),
                        "pass_reasons": decision["pass_reasons"],
                    }
                )
            metadata = ingestion.fetch.response_metadata or {}
            safe_metadata = {
                key: metadata[key]
                for key in ("requests_remaining", "requests_used", "requests_last", "cache_status")
                if key in metadata
            }
            return {
                "status": "completed",
                "snapshot_id": str(ingestion.persisted.snapshot_id),
                "requested_at": as_of,
                "provider": ingestion.fetch.provider_name,
                "provider_metadata": safe_metadata,
                "from_cache": ingestion.fetch.from_cache,
                "events_received": len(ingestion.fetch.games),
                "upcoming_events": len(upcoming),
                "observations_created": ingestion.persisted.observations_created,
                "warnings": [dict(item) for item in ingestion.persisted.warnings],
                "decisions": decisions,
            }
        finally:
            self._lock.release()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
