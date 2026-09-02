from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class DashboardModelResponse(BaseModel):
    model_id: str
    market_type: str
    version: str
    status: str
    model_family: str
    feature_set_hash: str | None = None
    holdout_result: str | None = None
    promotion_decision: str
    consensus_version: str | None = None
    vig_removal_version: str | None = None
    registry_entry_hash: str
    created_at: datetime


class DashboardSystemResponse(BaseModel):
    paper_trading: bool = True
    league: str = "NCAAF"
    system_status: str
    model_status: str
    market_status: str
    market_status_reason: str
    last_odds_refresh: datetime | None = None
    last_market_attempt: datetime | None = None
    last_market_attempt_status: str | None = None
    last_provider_error: str | None = None
    snapshot_age_seconds: int | None = None
    stale: bool
    next_scheduled_refresh: datetime | None = None
    supported_sportsbooks: list[str]
    policies: dict[str, Any]
    models: list[DashboardModelResponse]


class MarketMovementPointResponse(BaseModel):
    snapshot_id: str
    requested_at: datetime
    observed_at: datetime
    sportsbook: str
    market: str
    side: str
    point: float | None = None
    american_odds: int
    is_stale: bool


class MarketMovementEventResponse(BaseModel):
    event_id: str
    home_team: str
    away_team: str
    scheduled_start: datetime
    opening_available: bool = False
    points: list[MarketMovementPointResponse] = Field(default_factory=list)


class MarketMovementResponse(BaseModel):
    slate_date: date
    as_of: datetime
    source_snapshot_count: int
    events: list[MarketMovementEventResponse]


class MarketHistoryResponse(BaseModel):
    event_id: str
    market: str
    side: str
    as_of: datetime
    home_team: str | None = None
    away_team: str | None = None
    scheduled_start: datetime | None = None
    points: list[MarketMovementPointResponse] = Field(default_factory=list)


class MarketRefreshDecisionResponse(BaseModel):
    slate_date: date
    first_kickoff: datetime
    timing_classification: str
    primary_horizon_at: datetime
    horizon_delta_seconds: int
    horizon_version: str
    decision_run_id: str
    qualified_straights: int
    qualified_candidates: int
    actionable_straights: int
    games_analyzed: int
    watchlist_count: int
    parlay_status: str
    pass_reasons: list[str]


class MarketRefreshResponse(BaseModel):
    status: str
    snapshot_id: str
    requested_at: datetime
    provider_retrieved_at: datetime | None
    ingestion_completed_at: datetime
    decision_as_of: datetime
    provider: str
    provider_metadata: dict[str, Any]
    from_cache: bool
    events_received: int
    upcoming_events: int
    observations_created: int
    warnings: list[dict[str, Any]]
    decisions: list[MarketRefreshDecisionResponse]
