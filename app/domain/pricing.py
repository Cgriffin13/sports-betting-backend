from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Final, Literal
from uuid import UUID

from app.domain.validation import validate_american_odds

VIG_REMOVAL_POLICY_VERSION: Final = "proportional-v1"
CONSENSUS_POLICY_VERSION: Final = "unweighted-median-ml_empirical-cross-line-v1"
UNWEIGHTED_MEDIAN_POLICY_VERSION: Final = "unweighted-median-v1"
PRICING_POLICY_VERSION: Final = "market-baseline-v2"
QUALIFICATION_POLICY_VERSION: Final = "baseline-qualification-v2"
FAIR_PROBABILITY_SOURCE: Final = "market_consensus"
PROBABILITY_QUANTUM: Final = Decimal("0.000000000001")

MarketType = Literal["moneyline", "spread", "total"]
SelectionSide = Literal["home", "away", "over", "under"]


def _probability(value: Decimal | int | str, *, name: str) -> Decimal:
    try:
        probability = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a finite probability") from None
    if not probability.is_finite() or probability < 0 or probability > 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return probability


def american_odds_to_decimal(odds: int) -> Decimal:
    validated = validate_american_odds(odds)
    if validated > 0:
        return Decimal(1) + Decimal(validated) / Decimal(100)
    return Decimal(1) + Decimal(100) / Decimal(abs(validated))


def decimal_odds_to_implied_probability(decimal_odds: Decimal | int | str) -> Decimal:
    try:
        price = decimal_odds if isinstance(decimal_odds, Decimal) else Decimal(str(decimal_odds))
    except (InvalidOperation, ValueError):
        raise ValueError("Decimal odds must be finite and greater than 1") from None
    if not price.is_finite() or price <= 1:
        raise ValueError("Decimal odds must be finite and greater than 1")
    return Decimal(1) / price


def american_odds_to_implied_probability(odds: int) -> Decimal:
    return decimal_odds_to_implied_probability(american_odds_to_decimal(odds))


@dataclass(frozen=True, slots=True)
class NoVigResult:
    probabilities: tuple[Decimal, ...]
    raw_probability_sum: Decimal
    overround: Decimal
    policy_version: str = VIG_REMOVAL_POLICY_VERSION


def remove_vig_proportionally(raw_probabilities: tuple[Decimal, ...]) -> NoVigResult:
    if len(raw_probabilities) < 2:
        raise ValueError("Vig removal requires at least two mutually exclusive outcomes")
    probabilities = tuple(_probability(value, name="Raw implied probability") for value in raw_probabilities)
    if any(value <= 0 for value in probabilities):
        raise ValueError("Raw implied probabilities must be greater than zero")
    total = sum(probabilities, Decimal(0))
    if total <= 0:
        raise ValueError("Raw implied probability sum must be positive")
    normalized = tuple((value / total).quantize(PROBABILITY_QUANTUM, rounding=ROUND_HALF_EVEN) for value in probabilities)
    normalized = (*normalized[:-1], Decimal(1) - sum(normalized[:-1], Decimal(0)))
    return NoVigResult(
        probabilities=normalized,
        raw_probability_sum=total,
        overround=total - Decimal(1),
    )


def probability_edge(fair_probability: Decimal, offered_implied_probability: Decimal) -> Decimal:
    return _probability(fair_probability, name="Fair probability") - _probability(
        offered_implied_probability,
        name="Offered implied probability",
    )


def expected_value_binary(fair_probability: Decimal, decimal_odds: Decimal) -> Decimal:
    probability = _probability(fair_probability, name="Fair probability")
    price = american_or_decimal_price(decimal_odds)
    return probability * price - Decimal(1)


def expected_value_with_push(
    win_probability: Decimal,
    loss_probability: Decimal,
    decimal_odds: Decimal,
) -> Decimal:
    win = _probability(win_probability, name="Win probability")
    loss = _probability(loss_probability, name="Loss probability")
    if win + loss > 1:
        raise ValueError("Win and loss probabilities cannot sum above 1")
    price = american_or_decimal_price(decimal_odds)
    return win * (price - Decimal(1)) - loss


def american_or_decimal_price(value: Decimal | int | str) -> Decimal:
    try:
        price = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Decimal odds must be finite and greater than 1") from None
    if not price.is_finite() or price <= 1:
        raise ValueError("Decimal odds must be finite and greater than 1")
    return price


def decimal_median(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("Median requires at least one value")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    probability: Decimal
    dispersion: Decimal
    outlier_indexes: tuple[int, ...]
    policy_version: str = UNWEIGHTED_MEDIAN_POLICY_VERSION


def unweighted_median_consensus(
    probabilities: tuple[Decimal, ...],
    *,
    outlier_threshold: Decimal,
) -> ConsensusResult:
    if len(probabilities) < 2:
        raise ValueError("Consensus requires at least two books")
    validated = tuple(_probability(value, name="No-vig book probability") for value in probabilities)
    if not outlier_threshold.is_finite() or outlier_threshold < 0:
        raise ValueError("Outlier threshold must be finite and nonnegative")
    consensus = decimal_median(validated)
    return ConsensusResult(
        probability=consensus,
        dispersion=max(validated) - min(validated),
        outlier_indexes=tuple(
            index for index, probability in enumerate(validated) if abs(probability - consensus) > outlier_threshold
        ),
    )


@dataclass(frozen=True, slots=True)
class PricingObservation:
    observation_id: UUID
    snapshot_id: UUID
    event_id: UUID
    league: str
    home_team: str
    away_team: str
    scheduled_start_utc: datetime
    event_review_status: str
    sportsbook_id: UUID
    sportsbook_key: str
    sportsbook_name: str
    sportsbook_active: bool
    market_type: str
    period: str
    selection_side: str
    selection_name: str
    point: Decimal | None
    american_odds: int
    snapshot_requested_at: datetime
    observed_at: datetime
    ingested_at: datetime
    stale_after_seconds: int
    observation_status: str
    match_review_status: str


@dataclass(frozen=True, slots=True)
class BookNoVigPrice:
    sportsbook_key: str
    sportsbook_name: str
    selection_probability: Decimal
    opposing_probability: Decimal
    raw_probability_sum: Decimal
    overround: Decimal
    selection_observation_id: UUID
    opposing_observation_id: UUID
    snapshot_ids: tuple[UUID, ...]
    selection_american_odds: int | None = None
    selection_point: Decimal | None = None
    selection_observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PricingOpportunity:
    event_id: UUID
    league: str
    home_team: str
    away_team: str
    scheduled_start_utc: datetime
    market_type: str
    period: str
    selection_side: str
    selection_name: str
    point: Decimal | None
    best_sportsbook_key: str
    best_sportsbook_name: str
    best_american_odds: int
    best_decimal_odds: Decimal
    raw_implied_probability: Decimal
    no_vig_consensus_probability: Decimal
    proprietary_model_probability: None
    final_fair_probability_source: str
    final_fair_probability: Decimal
    probability_edge: Decimal
    ev_per_unit: Decimal
    books_contributing: int
    consensus_dispersion: Decimal
    uncertainty_indicator: str
    outlier_sportsbooks: tuple[str, ...]
    quality_warnings: tuple[str, ...]
    vig_removal_policy_version: str
    consensus_policy_version: str
    pricing_policy_version: str
    qualification_policy_version: str
    source_observation_ids: tuple[UUID, ...]
    best_executable_observation_id: UUID
    snapshot_ids: tuple[UUID, ...]
    book_probabilities: tuple[BookNoVigPrice, ...]
    calculated_at: datetime
    pricing_gate_failures: tuple[str, ...] = ()
    consensus_fair_point: Decimal | None = None
    line_advantage: Decimal | None = None
    push_probability: Decimal = Decimal(0)
    loss_probability: Decimal | None = None
    market_probability_policy_version: str = "exact-line-moneyline-v1"
    market_curve_artifact_hash: str | None = None
    center_dispersion: Decimal | None = None


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    minimum_books: int
    minimum_ev: Decimal
    minimum_probability_edge: Decimal
    outlier_threshold: Decimal
    maximum_dispersion: Decimal
    supported_books: frozenset[str]
    snapshot_freshness_seconds: int = 120
    maximum_provider_quote_age_seconds: int = 604_800
    pricing_version: str = PRICING_POLICY_VERSION
    consensus_version: str = CONSENSUS_POLICY_VERSION
    vig_removal_version: str = VIG_REMOVAL_POLICY_VERSION
    qualification_version: str = QUALIFICATION_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.minimum_books < 2:
            raise ValueError("Pricing minimum books must be at least 2")
        for name, value in (
            ("minimum_ev", self.minimum_ev),
            ("minimum_probability_edge", self.minimum_probability_edge),
            ("outlier_threshold", self.outlier_threshold),
            ("maximum_dispersion", self.maximum_dispersion),
        ):
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        if self.outlier_threshold < 0 or self.maximum_dispersion < 0:
            raise ValueError("Pricing dispersion thresholds must be nonnegative")
        if not self.supported_books:
            raise ValueError("At least one supported sportsbook is required")
        if self.snapshot_freshness_seconds <= 0:
            raise ValueError("Snapshot freshness threshold must be positive")
        if self.maximum_provider_quote_age_seconds <= self.snapshot_freshness_seconds:
            raise ValueError("Provider quote-age ceiling must exceed snapshot freshness")


@dataclass(frozen=True, slots=True)
class PricingAnalysis:
    as_of: datetime
    pricing_policy_version: str
    qualification_policy_version: str
    first_scheduled_start_utc: datetime | None
    candidates: tuple[PricingOpportunity, ...]
    opportunities: tuple[PricingOpportunity, ...]
    events_analyzed: int
    observations_considered: int
    paired_book_markets: int
    opportunities_qualified: int
    top_n_per_league: int
    rejection_counts: dict[str, int]
    funnel: dict[str, int]
    pipeline_status: str = "HEALTHY"
    pipeline_status_reason: str | None = None
