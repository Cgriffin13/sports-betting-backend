from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RecommendationRequest(BaseModel):
    slate_date: date
    as_of: datetime | None = None
    market_types: list[str] = Field(default_factory=lambda: ["moneyline", "spread", "total"], min_length=1)
    top_n: int = Field(default=10, ge=1, le=10)

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        return value


class RecommendationDecisionResponse(BaseModel):
    decision_run_id: str
    as_of: str
    slate_date: str
    portfolio_state: str
    top_n: int
    pass_reasons: list[str]
    policy_versions: dict[str, str]
    portfolio: dict[str, Any]
    straight_recommendations: list[dict[str, Any]]
    parlay_of_the_day: dict[str, Any]
    analysis_summary: dict[str, Any]
    watchlist_count: int
    decision_hash: str


class RecommendationListResponse(BaseModel):
    recommendations: list[dict[str, Any]]
    latest_decision: dict[str, Any] | None = None


class WatchlistItemResponse(BaseModel):
    watchlist_id: str
    event_id: str
    slate_date: date
    scheduled_start: datetime
    home_team: str
    away_team: str
    market: str
    side: str
    selection: str
    sportsbook: str
    point: float | None = None
    consensus_fair_point: float | None = None
    line_advantage: float | None = None
    odds: int
    fair_probability: float
    implied_probability: float
    edge: float
    ev_per_unit: float
    books_count: int
    dispersion: float
    freshness_age_seconds: int
    fresh: bool
    timing_classification: str
    primary_horizon_at: datetime
    rejection_reasons: list[str]
    primary_blocker: str
    failed_gate_count: int
    distance_to_qualification: float
    ranking_score: float
    source_observation_ids: list[str]
    snapshot_ids: list[str]
    best_executable_observation_id: str
    watchlist_version: str
    market_probability_policy_version: str | None = None
    market_curve_artifact_hash: str | None = None
    actionable: bool = False


class QualifiedOpportunityResponse(BaseModel):
    qualified_opportunity_id: str
    event_id: str
    slate_date: date
    scheduled_start: datetime
    home_team: str
    away_team: str
    market: str
    side: str
    selection: str
    sportsbook: str
    point: float | None = None
    odds: int
    fair_probability: float
    implied_probability: float
    push_probability: float
    edge: float
    ev_per_unit: float
    books_count: int
    dispersion: float
    freshness_age_seconds: int
    calculated_stake: float
    minimum_operational_stake: float
    raw_kelly_fraction: float
    adjusted_kelly_fraction: float
    ranking_score: float
    classification: str | None
    blocker: str
    risk_adjustments: list[str]
    source_observation_ids: list[str]
    snapshot_ids: list[str]
    best_executable_observation_id: str
    model_id: str
    model_version: str
    model_status: str
    pricing_policy_version: str
    qualification_policy_version: str
    risk_policy_version: str
    market_probability_policy_version: str
    timing_classification: str | None = None
    primary_horizon_at: datetime | None = None
    qualified: bool = True
    actionable: bool = False
    approvable: bool = False
    opportunity_hash: str


class WatchlistResponse(BaseModel):
    as_of: datetime
    upcoming_games_analyzed: int
    qualified_recommendations: int
    actionable_recommendations: int
    watchlist_count: int
    watchlist_version: str
    pricing_funnel: dict[str, int]
    rejection_counts: dict[str, int]
    pricing_pipeline_status: str
    pricing_pipeline_status_reason: str | None
    slates: list[dict[str, Any]]
    items: list[WatchlistItemResponse]
    qualified_opportunities: list[QualifiedOpportunityResponse]


class RecommendationDispositionResponse(BaseModel):
    recommendation: dict[str, Any]


class RiskExposureResponse(BaseModel):
    portfolio_id: str
    slate_date: str
    portfolio_state: str
    state_reason: str
    cash: float
    reserved_exposure: float
    equity: float
    peak_equity: float
    drawdown_fraction: float
    by_game: dict[str, float]
    by_team: dict[str, float]
    by_market: dict[str, float]
    by_kind: dict[str, float]
