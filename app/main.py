from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI

from app.api import bets, health, odds, portfolios
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain.identity import Principal
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware
from app.persistence.base import PortfolioRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import MarketDataProvider
from app.providers.odds_api import TheOddsApiProvider
from app.services.odds_service import OddsService
from app.services.portfolio_service import PortfolioService
from app.security import ApiKeyAuthenticator
from app.time import utc_now


def create_app(
    *,
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    repository: PortfolioRepository | None = None,
    authenticator: ApiKeyAuthenticator | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_provider = provider or TheOddsApiProvider(
        resolved_settings.odds_api_key,
        timeout_seconds=resolved_settings.provider_timeout_seconds,
    )
    database_engine = None
    if repository is None:
        database_engine = create_database_engine(resolved_settings.database_url)
        resolved_repository: PortfolioRepository = SqlAlchemyPortfolioRepository(
            create_session_factory(database_engine), resolved_settings.starting_bankroll, clock=clock
        )
    else:
        resolved_repository = repository
    resolved_authenticator = authenticator or ApiKeyAuthenticator(
        {
            resolved_settings.app_api_key: Principal(
                external_id=resolved_settings.app_owner_id,
                display_name=resolved_settings.app_owner_name,
            )
        }
    )

    configure_logging()
    application = FastAPI(
        title="Sports Betting Portfolio Backend",
        version="1.2.0",
        description="Backend for odds, bankroll tracking, bet logging, and learning stats.",
    )
    application.state.settings = resolved_settings
    application.state.database_engine = database_engine
    application.state.authenticator = resolved_authenticator
    application.state.odds_service = OddsService(resolved_provider)
    application.state.portfolio_service = PortfolioService(resolved_repository)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health.router)
    application.include_router(odds.router)
    application.include_router(bets.router)
    application.include_router(portfolios.router)
    return application


app = create_app()
