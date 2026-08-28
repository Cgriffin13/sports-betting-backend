"""Portfolio responses retain the prototype's flexible JSON record shape."""

from typing import Any

from pydantic import BaseModel


class PortfolioResponse(BaseModel):
    portfolio_id: str
    bankroll: float
    bets: list[dict[str, Any]]


class PortfolioStatsResponse(BaseModel):
    portfolio_id: str
    starting_bankroll: float
    current_bankroll: float
    net_pnl: float
    overall: dict[str, Any]
    by_bucket: list[dict[str, Any]]
