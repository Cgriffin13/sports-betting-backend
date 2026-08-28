import os
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Default app composition is fail-closed; provide non-secret test-only runtime values before importing app.main.
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("APP_API_KEY", "root-test-only-key")

from app.config import Settings
from app.db.base import Base
from app.db.session import create_session_factory
from app.domain.identity import Principal
from app.main import create_app
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import MarketGame
from app.security import ApiKeyAuthenticator


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
    return Settings(
        data_dir=tmp_path,
        database_url="sqlite+pysqlite:///:memory:",
        app_api_key="test-primary-key",
        app_owner_id="owner-primary",
        app_owner_name="Primary Owner",
        starting_bankroll=Decimal("200.00"),
    )


@pytest.fixture
def engine() -> Engine:
    database_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database_engine)
    return database_engine


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def repository(session_factory: sessionmaker[Session]) -> SqlAlchemyPortfolioRepository:
    return SqlAlchemyPortfolioRepository(session_factory, Decimal("200.00"))


@pytest.fixture
def authenticator() -> ApiKeyAuthenticator:
    return ApiKeyAuthenticator(
        {
            "test-primary-key": Principal("owner-primary", "Primary Owner"),
            "test-secondary-key": Principal("owner-secondary", "Secondary Owner"),
        }
    )


@pytest.fixture
def raw_client(
    settings: Settings,
    repository: SqlAlchemyPortfolioRepository,
    authenticator: ApiKeyAuthenticator,
) -> TestClient:
    return TestClient(
        create_app(
            settings=settings,
            provider=FakeProvider(),
            repository=repository,
            authenticator=authenticator,
        )
    )


@pytest.fixture
def client(raw_client: TestClient) -> TestClient:
    raw_client.headers.update({"X-API-Key": "test-primary-key"})
    return raw_client


@pytest.fixture
def app_client(
    settings: Settings,
    repository: SqlAlchemyPortfolioRepository,
    authenticator: ApiKeyAuthenticator,
) -> Any:
    def build(provider: FakeProvider) -> TestClient:
        result = TestClient(
            create_app(
                settings=settings,
                provider=provider,
                repository=repository,
                authenticator=authenticator,
            )
        )
        result.headers.update({"X-API-Key": "test-primary-key"})
        return result

    return build
