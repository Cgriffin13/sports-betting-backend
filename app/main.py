from collections.abc import Callable

from fastapi import FastAPI

from app.api import bets, health, odds, portfolios
from app.config import Settings
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware
from app.persistence.base import PortfolioRepository
from app.persistence.json_repository import JsonPortfolioRepository
from app.providers.base import MarketDataProvider
from app.providers.odds_api import TheOddsApiProvider
from app.services.odds_service import OddsService
from app.services.portfolio_service import PortfolioService
from app.time import utc_now_iso


def create_app(
    *,
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    repository: PortfolioRepository | None = None,
    clock: Callable[[], str] = utc_now_iso,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_provider = provider or TheOddsApiProvider(
        resolved_settings.odds_api_key,
        timeout_seconds=resolved_settings.provider_timeout_seconds,
    )
    resolved_repository = repository or JsonPortfolioRepository(
        resolved_settings.data_dir,
        resolved_settings.starting_bankroll,
    )

    configure_logging()
    application = FastAPI(
        title="Sports Betting Portfolio Backend",
        version="1.2.0",
        description="Backend for odds, bankroll tracking, bet logging, and learning stats.",
    )
    application.state.settings = resolved_settings
    application.state.odds_service = OddsService(resolved_provider)
    application.state.portfolio_service = PortfolioService(
        resolved_repository,
        resolved_settings.starting_bankroll,
        clock=clock,
    )
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health.router)
    application.include_router(odds.router)
    application.include_router(bets.router)
    application.include_router(portfolios.router)
    return application


app = create_app()
