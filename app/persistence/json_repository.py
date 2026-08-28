from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.persistence.base import PortfolioRecord

LOGGER = logging.getLogger(__name__)


def default_database(starting_bankroll: float) -> dict[str, Any]:
    return {"portfolios": {"main": {"bankroll": starting_bankroll, "bets": []}}}


class JsonPortfolioRepository:
    """Compatibility JSON store. It intentionally retains prototype mutation semantics."""

    def __init__(self, data_dir: Path, starting_bankroll: float) -> None:
        self._starting_bankroll = starting_bankroll
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_file = self._data_dir / "portfolio_db.json"
        self._data = self._load()

    @property
    def db_file(self) -> Path:
        return self._db_file

    def _load(self) -> dict[str, Any]:
        if self._db_file.exists():
            try:
                with self._db_file.open("r", encoding="utf-8") as file:
                    data = json.load(file)
                if isinstance(data, dict) and "portfolios" in data:
                    return data
            except Exception:
                LOGGER.warning("portfolio_store_load_failed", extra={"storage": "json"})
        return default_database(self._starting_bankroll)

    def get_or_create(self, portfolio_id: str) -> PortfolioRecord:
        portfolios = self._data.setdefault("portfolios", {})
        if portfolio_id not in portfolios:
            portfolios[portfolio_id] = {"bankroll": self._starting_bankroll, "bets": []}
            self.save_portfolio(portfolio_id, portfolios[portfolio_id])
        return portfolios[portfolio_id]

    def save_portfolio(self, portfolio_id: str, portfolio: PortfolioRecord) -> None:
        self._data.setdefault("portfolios", {})[portfolio_id] = portfolio
        try:
            temporary = self._db_file.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as file:
                json.dump(self._data, file, indent=2, default=str)
            temporary.replace(self._db_file)
        except Exception:
            LOGGER.warning("portfolio_store_save_failed", extra={"storage": "json"})
