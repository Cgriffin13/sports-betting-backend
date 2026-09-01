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
    decision_hash: str


class RecommendationListResponse(BaseModel):
    recommendations: list[dict[str, Any]]
    latest_decision: dict[str, Any] | None = None


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
