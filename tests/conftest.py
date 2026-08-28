from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.persistence.memory_repository import InMemoryPortfolioRepository
from app.providers.base import MarketGame


class FakeProvider:
    def __init__(
        self,
        games: list[MarketGame] | None = None,
        *,
        configured: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.games = games or []
        self._configured = configured
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    @property
    def configured(self) -> bool:
        return self._configured

    def fetch_current_odds(self, sport: str, markets: list[str]) -> list[MarketGame]:
        self.calls.append((sport, markets))
        if self.error:
            raise self.error
        return self.games


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, starting_bankroll=200.0)


@pytest.fixture
def repository() -> InMemoryPortfolioRepository:
    return InMemoryPortfolioRepository(200.0)


@pytest.fixture
def client(settings: Settings, repository: InMemoryPortfolioRepository) -> TestClient:
    return TestClient(create_app(settings=settings, provider=FakeProvider(), repository=repository))


@pytest.fixture
def app_client(settings: Settings, repository: InMemoryPortfolioRepository) -> Any:
    def build(provider: FakeProvider) -> TestClient:
        return TestClient(create_app(settings=settings, provider=provider, repository=repository))

    return build
