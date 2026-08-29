from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI

from app.api import bets, health, odds, opportunities, portfolios
from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.domain.identity import Principal
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware
from app.persistence.base import PortfolioRepository
from app.persistence.market_base import MarketDataRepository
from app.persistence.market_repository import SqlAlchemyMarketDataRepository
from app.persistence.pricing_base import EmptyPricingObservationRepository, PricingObservationRepository
from app.persistence.pricing_repository import SqlAlchemyPricingObservationRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import MarketDataProvider
from app.providers.odds_api import TheOddsApiProvider
from app.services.odds_service import OddsService
from app.services.pricing_service import PricingService, build_pricing_policy
from app.services.portfolio_service import PortfolioService
from app.security import ApiKeyAuthenticator
from app.time import utc_now


def create_app(
    *,
    settings: Settings | None = None,
    provider: MarketDataProvider | None = None,
    repository: PortfolioRepository | None = None,
    market_repository: MarketDataRepository | None = None,
    pricing_repository: PricingObservationRepository | None = None,
    authenticator: ApiKeyAuthenticator | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_provider = provider or TheOddsApiProvider(
        resolved_settings.odds_api_key,
        timeout_seconds=resolved_settings.provider_timeout_seconds,
        max_retries=resolved_settings.provider_max_retries,
        backoff_seconds=resolved_settings.provider_backoff_seconds,
        cache_ttl_seconds=resolved_settings.provider_cache_ttl_seconds,
        low_quota_threshold=resolved_settings.provider_low_quota_threshold,
        clock=clock,
    )
    database_engine = None
    if repository is None:
        database_engine = create_database_engine(resolved_settings.database_url)
        session_factory = create_session_factory(database_engine)
        resolved_repository: PortfolioRepository = SqlAlchemyPortfolioRepository(
            session_factory, resolved_settings.starting_bankroll, clock=clock
        )
        resolved_market_repository: MarketDataRepository | None = market_repository or SqlAlchemyMarketDataRepository(
            session_factory,
            freshness_seconds=resolved_settings.market_freshness_seconds,
            clock=clock,
        )
        resolved_pricing_repository: PricingObservationRepository = (
            pricing_repository or SqlAlchemyPricingObservationRepository(session_factory)
        )
    else:
        resolved_repository = repository
        resolved_market_repository = market_repository
        resolved_pricing_repository = pricing_repository or EmptyPricingObservationRepository()
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
        version="1.4.0",
        description="Paper-trading backend for market data, baseline pricing, and portfolio tracking.",
    )
    application.state.settings = resolved_settings
    application.state.database_engine = database_engine
    application.state.authenticator = resolved_authenticator
    application.state.clock = clock
    application.state.odds_service = OddsService(resolved_provider, resolved_market_repository)
    application.state.pricing_service = PricingService(
        resolved_pricing_repository,
        build_pricing_policy(
            minimum_books=resolved_settings.pricing_minimum_books,
            minimum_ev=resolved_settings.pricing_minimum_ev,
            minimum_probability_edge=resolved_settings.pricing_minimum_probability_edge,
            outlier_threshold=resolved_settings.pricing_outlier_threshold,
            maximum_dispersion=resolved_settings.pricing_maximum_dispersion,
            supported_books=resolved_settings.pricing_supported_books,
        ),
    )
    application.state.portfolio_service = PortfolioService(resolved_repository)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health.router)
    application.include_router(odds.router)
    application.include_router(opportunities.router)
    application.include_router(bets.router)
    application.include_router(portfolios.router)
    return application


app = create_app()
