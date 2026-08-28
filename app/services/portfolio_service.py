from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.identity import Principal
from app.domain.money import money
from app.persistence.base import PortfolioRepository


class PortfolioService:
    def __init__(self, repository: PortfolioRepository) -> None:
        self._repository = repository

    def get_portfolio(self, principal: Principal, portfolio_id: str, limit: int = 200) -> dict[str, Any]:
        return self._repository.get_portfolio(principal, portfolio_id, limit)

    def place_bet(
        self,
        principal: Principal,
        bet_data: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        normalized = dict(bet_data)
        normalized["stake"] = money(normalized["stake"])
        return self._repository.place_bet(
            principal,
            normalized,
            idempotency_key=idempotency_key,
            request_hash=request_hash(normalized),
        )

    def settle_bet(
        self,
        principal: Principal,
        settlement: Mapping[str, Any],
        *,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        normalized = dict(settlement)
        normalized["payout"] = money(normalized["payout"])
        return self._repository.settle_bet(
            principal,
            normalized,
            idempotency_key=idempotency_key,
            request_hash=request_hash(normalized),
        )

    def get_stats(self, principal: Principal, portfolio_id: str) -> dict[str, Any]:
        return self._repository.get_stats(principal, portfolio_id)


def request_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported idempotency payload type: {type(value).__name__}")
