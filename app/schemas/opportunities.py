from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.pricing import PricingAnalysis


class OpportunitiesRequest(BaseModel):
    leagues: list[str] = Field(default_factory=lambda: ["NCAAF"], min_length=1)
    market_types: list[str] = Field(
        default_factory=lambda: ["moneyline", "spread", "total"],
        min_length=1,
    )
    top_n: int = Field(default=10, ge=1, le=50)
    as_of: datetime | None = None
    event_date: date | None = None
    pricing_policy_version: str | None = None
    qualification_policy_version: str | None = None

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value


class BookNoVigPriceResponse(BaseModel):
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


class PricingOpportunityResponse(BaseModel):
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
    proprietary_model_probability: None = None
    final_fair_probability_source: Literal["market_consensus"]
    final_fair_probability: Decimal
    probability_edge: Decimal
    ev_per_unit: Decimal
    books_contributing: int
    consensus_dispersion: Decimal
    uncertainty_indicator: Literal["low", "moderate", "high"]
    outlier_sportsbooks: tuple[str, ...]
    quality_warnings: tuple[str, ...]
    vig_removal_policy_version: str
    consensus_policy_version: str
    pricing_policy_version: str
    qualification_policy_version: str
    source_observation_ids: tuple[UUID, ...]
    best_executable_observation_id: UUID
    snapshot_ids: tuple[UUID, ...]
    book_probabilities: tuple[BookNoVigPriceResponse, ...]
    calculated_at: datetime
    consensus_fair_point: Decimal | None = None
    line_advantage: Decimal | None = None
    push_probability: Decimal = Decimal(0)
    loss_probability: Decimal | None = None
    market_probability_policy_version: str
    market_curve_artifact_hash: str | None = None
    center_dispersion: Decimal | None = None


class PricingAnalysisResponse(BaseModel):
    analysis_type: Literal["market_consensus_baseline"] = "market_consensus_baseline"
    paper_research_only: bool = True
    as_of: datetime
    pricing_policy_version: str
    qualification_policy_version: str
    observations_considered: int
    paired_book_markets: int
    opportunities_qualified: int
    opportunities_returned: int
    top_n_per_league: int
    rejection_counts: dict[str, int]
    funnel: dict[str, int]
    opportunities: tuple[PricingOpportunityResponse, ...]

    @classmethod
    def from_domain(cls, analysis: PricingAnalysis) -> "PricingAnalysisResponse":
        return cls(
            as_of=analysis.as_of,
            pricing_policy_version=analysis.pricing_policy_version,
            qualification_policy_version=analysis.qualification_policy_version,
            observations_considered=analysis.observations_considered,
            paired_book_markets=analysis.paired_book_markets,
            opportunities_qualified=analysis.opportunities_qualified,
            opportunities_returned=len(analysis.opportunities),
            top_n_per_league=analysis.top_n_per_league,
            rejection_counts=analysis.rejection_counts,
            funnel=analysis.funnel,
            opportunities=tuple(
                PricingOpportunityResponse.model_validate(opportunity, from_attributes=True)
                for opportunity in analysis.opportunities
            ),
        )
