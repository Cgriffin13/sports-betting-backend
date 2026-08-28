from typing import Any, Protocol

PortfolioRecord = dict[str, Any]


class PortfolioRepository(Protocol):
    def get_or_create(self, portfolio_id: str) -> PortfolioRecord: ...

    def save_portfolio(self, portfolio_id: str, portfolio: PortfolioRecord) -> None: ...
