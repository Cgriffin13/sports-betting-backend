"""Portfolio responses retain the prototype's flexible JSON record shape."""

from typing import Any

from pydantic import BaseModel, Field


class PortfolioResponse(BaseModel):
    portfolio_id: str
    bankroll: float
    cash: float
    reserved_stake: float
    open_exposure: float
    equity: float
    realized_pnl: float
    currency: str
    bets: list[dict[str, Any]]


class PortfolioStatsResponse(BaseModel):
    portfolio_id: str
    starting_bankroll: float
    current_bankroll: float
    cash: float
    reserved_stake: float
    open_exposure: float
    equity: float
    realized_pnl: float
    net_pnl: float
    overall: dict[str, Any]
    by_bucket: list[dict[str, Any]]
    attribution: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)
    risk_metrics: dict[str, Any] = Field(default_factory=dict)
