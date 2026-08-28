from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.validation import validate_american_odds


class BetIn(BaseModel):
    portfolio_id: str
    date: date
    sport: str
    league: str
    market_type: str
    selection: str
    book: str
    odds: int
    stake: Decimal = Field(gt=0, allow_inf_nan=False)
    provider_event_id: str | None = None
    event_name: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    scheduled_start: datetime | None = None
    period: str = "full_game"
    point: Decimal | None = Field(default=None, allow_inf_nan=False)
    model_prob: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    book_prob: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    consensus_prob: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    fair_prob: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    edge: float | None = Field(default=None, ge=-1, le=1, allow_inf_nan=False)
    ev_per_1: float | None = Field(default=None, allow_inf_nan=False)
    recommendation_version: str | None = None
    model_version: str | None = None
    policy_version: str | None = None

    @field_validator("odds")
    @classmethod
    def validate_odds(cls, value: int) -> int:
        return validate_american_odds(value)

    @field_validator("scheduled_start")
    @classmethod
    def validate_scheduled_start(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("scheduled_start must be timezone-aware")
        return value


class BetResultIn(BaseModel):
    portfolio_id: str
    bet_id: str
    result: Literal["win", "loss", "push"]
    payout: Decimal = Field(allow_inf_nan=False)
    closing_odds: int | None = None
    closing_book_prob: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    source: str = "manual_api"

    @field_validator("closing_odds")
    @classmethod
    def validate_closing_odds(cls, value: int | None) -> int | None:
        return validate_american_odds(value) if value is not None else None

    @model_validator(mode="after")
    def validate_result_payout(self) -> "BetResultIn":
        if self.result == "win" and self.payout <= 0:
            raise ValueError("Win payout must be positive net profit")
        if self.result == "loss" and self.payout >= 0:
            raise ValueError("Loss payout must be negative net profit")
        if self.result == "push" and self.payout != 0:
            raise ValueError("Push payout must be zero")
        return self


class BetRecordedResponse(BaseModel):
    message: str
    bet_id: str
    bankroll_after: float


class BetResultResponse(BaseModel):
    message: str
    bankroll_after: float
