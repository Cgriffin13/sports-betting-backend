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
    last_odds_refresh: datetime | None = None
    snapshot_age_seconds: int | None = None
    stale: bool
    next_scheduled_refresh: datetime | None = None
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
