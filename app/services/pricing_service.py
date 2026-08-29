from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from time import perf_counter

from app.domain.consensus import build_pricing_analysis
from app.domain.markets import ALLOWED_MARKETS, MARKET_ALIASES
from app.domain.market_identity import CANONICAL_MARKET_TYPES
from app.domain.pricing import PricingAnalysis, PricingPolicy
from app.domain.sports import SUPPORTED_SPORTS, normalize_sport
from app.persistence.pricing_base import PricingObservationQuery, PricingObservationRepository

CANONICAL_REQUEST_MARKETS = frozenset(CANONICAL_MARKET_TYPES.values())
logger = logging.getLogger(__name__)


class PricingService:
    def __init__(self, repository: PricingObservationRepository, policy: PricingPolicy) -> None:
        self._repository = repository
        self._policy = policy

    def analyze(
        self,
        *,
        leagues: list[str],
        market_types: list[str],
        as_of: datetime,
        event_date: date | None,
        top_n: int,
        pricing_policy_version: str | None = None,
        qualification_policy_version: str | None = None,
    ) -> PricingAnalysis:
        normalized_leagues = _normalize_leagues(leagues)
        normalized_markets = _normalize_pricing_markets(market_types)
        cutoff = _timezone_aware_utc(as_of)
        if pricing_policy_version is not None and pricing_policy_version != self._policy.pricing_version:
            raise ValueError(f"Unsupported pricing policy version '{pricing_policy_version}'")
        if qualification_policy_version is not None and qualification_policy_version != self._policy.qualification_version:
            raise ValueError(f"Unsupported qualification policy version '{qualification_policy_version}'")
        query_started = perf_counter()
        observations = self._repository.list_for_pricing(
            PricingObservationQuery(
                leagues=normalized_leagues,
                market_types=normalized_markets,
                as_of=cutoff,
                event_date=event_date,
            )
        )
        query_elapsed_ms = (perf_counter() - query_started) * 1_000
        calculation_started = perf_counter()
        analysis = build_pricing_analysis(
            observations,
            as_of=cutoff,
            policy=self._policy,
            top_n_per_league=top_n,
        )
        calculation_elapsed_ms = (perf_counter() - calculation_started) * 1_000
        logger.info(
            "pricing_analysis_complete",
            extra={
                "observations_fetched": len(observations),
                "snapshots_represented": len({item.snapshot_id for item in observations}),
                "events_represented": len({item.event_id for item in observations}),
                "books_represented": len({item.sportsbook_id for item in observations}),
                "query_elapsed_ms": round(query_elapsed_ms, 3),
                "calculation_elapsed_ms": round(calculation_elapsed_ms, 3),
                "opportunities_returned": len(analysis.opportunities),
            },
        )
        return analysis


def build_pricing_policy(
    *,
    minimum_books: int,
    minimum_ev: Decimal,
    minimum_probability_edge: Decimal,
    outlier_threshold: Decimal,
    maximum_dispersion: Decimal,
    supported_books: tuple[str, ...],
) -> PricingPolicy:
    return PricingPolicy(
        minimum_books=minimum_books,
        minimum_ev=minimum_ev,
        minimum_probability_edge=minimum_probability_edge,
        outlier_threshold=outlier_threshold,
        maximum_dispersion=maximum_dispersion,
        supported_books=frozenset(book.strip().lower() for book in supported_books if book.strip()),
    )


def _normalize_leagues(leagues: list[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(normalize_sport(league) for league in leagues))
    invalid = [league for league in normalized if league not in SUPPORTED_SPORTS]
    if invalid:
        raise ValueError(f"Unsupported league(s): {', '.join(invalid)}")
    if not normalized:
        raise ValueError("At least one league is required")
    return normalized


def _normalize_pricing_markets(markets: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for market in markets:
        raw = market.strip()
        provider_market = MARKET_ALIASES.get(raw.upper(), raw.lower())
        if provider_market in ALLOWED_MARKETS:
            canonical = CANONICAL_MARKET_TYPES[provider_market]
        elif provider_market in CANONICAL_REQUEST_MARKETS:
            canonical = provider_market
        else:
            raise ValueError(f"Unsupported market type '{market}'")
        if canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        raise ValueError("At least one market type is required")
    return tuple(normalized)


def _timezone_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return value.astimezone(UTC)
