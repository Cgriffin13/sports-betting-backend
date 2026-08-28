from collections.abc import Mapping
from typing import Any, Protocol

from app.domain.identity import Principal


class PortfolioRepository(Protocol):
    def get_portfolio(self, principal: Principal, portfolio_id: str, limit: int = 200) -> dict[str, Any]: ...

    def place_bet(
        self,
        principal: Principal,
        bet_data: Mapping[str, Any],
        *,
        idempotency_key: str | None,
        request_hash: str,
    ) -> dict[str, Any]: ...

    def settle_bet(
        self,
        principal: Principal,
        settlement: Mapping[str, Any],
        *,
        idempotency_key: str | None,
        request_hash: str,
    ) -> dict[str, Any]: ...

    def get_stats(self, principal: Principal, portfolio_id: str) -> dict[str, Any]: ...
