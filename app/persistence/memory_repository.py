from typing import Any

from app.persistence.base import PortfolioRecord
from app.persistence.json_repository import default_database


class InMemoryPortfolioRepository:
    """Deterministic repository for unit tests and local composition."""

    def __init__(self, starting_bankroll: float = 200.0, data: dict[str, Any] | None = None) -> None:
        self._starting_bankroll = starting_bankroll
        self.data = data if data is not None else default_database(starting_bankroll)
        self.save_count = 0

    def get_or_create(self, portfolio_id: str) -> PortfolioRecord:
        portfolios = self.data.setdefault("portfolios", {})
        if portfolio_id not in portfolios:
            portfolios[portfolio_id] = {"bankroll": self._starting_bankroll, "bets": []}
            self.save_portfolio(portfolio_id, portfolios[portfolio_id])
        return portfolios[portfolio_id]

    def save_portfolio(self, portfolio_id: str, portfolio: PortfolioRecord) -> None:
        self.data.setdefault("portfolios", {})[portfolio_id] = portfolio
        self.save_count += 1
