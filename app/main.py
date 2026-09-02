from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI

from app.api import bets, dashboard, health, odds, opportunities, portfolios, recommendations
from app.config import Settings
from app.db import ncaaf_models, portfolio_models  # noqa: F401
from app.db.session import create_database_engine, create_session_factory
from app.domain.identity import Principal
from app.logging import configure_logging
from app.middleware import RequestIdMiddleware
from app.persistence.base import PortfolioRepository
from app.persistence.dashboard_repository import SqlAlchemyDashboardRepository
from app.persistence.market_base import MarketDataRepository
from app.persistence.market_repository import SqlAlchemyMarketDataRepository
from app.persistence.pricing_base import EmptyPricingObservationRepository, PricingObservationRepository
from app.persistence.pricing_repository import SqlAlchemyPricingObservationRepository
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.persistence.recommendation_repository import SqlAlchemyRecommendationRepository
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.providers.base import MarketDataProvider
from app.providers.odds_api import TheOddsApiProvider
from app.services.odds_service import OddsService
from app.services.dashboard_service import DashboardService
from app.services.market_refresh_service import MarketRefreshService
from app.services.model_registry_bootstrap import bootstrap_ncaaf_registry
from app.services.pricing_service import PricingService, build_pricing_policy
from app.services.portfolio_service import PortfolioService
from app.services.recommendation_service import RecommendationService, build_recommendation_policies
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
    qualification_policy, risk_policy, parlay_policy = build_recommendation_policies(
        _recommendation_policy_values(resolved_settings)
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
            provider_quote_max_age_seconds=resolved_settings.provider_quote_max_age_seconds,
            clock=clock,
        )
        resolved_pricing_repository: PricingObservationRepository = (
            pricing_repository or SqlAlchemyPricingObservationRepository(session_factory)
        )
        registry_repository = SqlAlchemyModelRegistryRepository(session_factory)
        registry_hash = None
        recommendation_repository = SqlAlchemyRecommendationRepository(
            session_factory,
            resolved_settings.starting_bankroll,
            risk_policy=risk_policy,
            parlay_policy=parlay_policy,
            clock=clock,
        )
        dashboard_service = DashboardService(SqlAlchemyDashboardRepository(session_factory), resolved_settings)
    else:
        resolved_repository = repository
        resolved_market_repository = market_repository
        resolved_pricing_repository = pricing_repository or EmptyPricingObservationRepository()
        registry_repository = None
        registry_hash = None
        recommendation_repository = None
        dashboard_service = None
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
        version="1.6.0",
        description="Paper-trading backend for market data, fair value, recommendations, risk, and ledger tracking.",
    )
    application.state.settings = resolved_settings
    application.state.database_engine = database_engine
    application.state.authenticator = resolved_authenticator
    application.state.clock = clock
    application.state.odds_service = OddsService(resolved_provider, resolved_market_repository)
    application.state.registry_hash = registry_hash
    pricing_service = PricingService(
        resolved_pricing_repository,
        build_pricing_policy(
            minimum_books=resolved_settings.pricing_minimum_books,
            minimum_ev=resolved_settings.pricing_minimum_ev,
            minimum_probability_edge=resolved_settings.pricing_minimum_probability_edge,
            outlier_threshold=resolved_settings.pricing_outlier_threshold,
            maximum_dispersion=resolved_settings.pricing_maximum_dispersion,
            supported_books=resolved_settings.pricing_supported_books,
            snapshot_freshness_seconds=resolved_settings.market_freshness_seconds,
            maximum_provider_quote_age_seconds=resolved_settings.provider_quote_max_age_seconds,
        ),
    )
    application.state.pricing_service = pricing_service
    application.state.dashboard_service = dashboard_service
    application.state.portfolio_service = PortfolioService(resolved_repository)
    if registry_repository is not None and recommendation_repository is not None:
        application.state.recommendation_service = RecommendationService(
            pricing_service=pricing_service,
            registry_repository=registry_repository,
            repository=recommendation_repository,
            qualification_policy=qualification_policy,
            risk_policy=risk_policy,
            parlay_policy=parlay_policy,
        )
        application.state.market_refresh_service = MarketRefreshService(
            application.state.odds_service,
            application.state.recommendation_service,
        )

        def bootstrap_registry() -> None:
            application.state.registry_hash = bootstrap_ncaaf_registry(registry_repository)

        application.add_event_handler("startup", bootstrap_registry)
    else:
        application.state.recommendation_service = None
        application.state.market_refresh_service = None
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health.router)
    application.include_router(odds.router)
    application.include_router(opportunities.router)
    application.include_router(bets.router)
    application.include_router(portfolios.router)
    application.include_router(recommendations.router)
    application.include_router(dashboard.router)
    return application


def _recommendation_policy_values(settings: Settings) -> dict[str, object]:
    return {
        "minimum_ev": settings.portfolio_minimum_ev,
        "minimum_edge": settings.portfolio_minimum_edge,
        "maximum_dispersion": settings.portfolio_maximum_dispersion,
        "minimum_books": settings.portfolio_minimum_books,
        "maximum_market_age_seconds": settings.market_freshness_seconds,
        "core_minimum_ev": settings.portfolio_core_minimum_ev,
        "core_minimum_edge": settings.portfolio_core_minimum_edge,
        "kelly_fraction": settings.portfolio_kelly_fraction,
        "minimum_stake": settings.portfolio_minimum_stake,
        "maximum_stake": settings.portfolio_maximum_stake,
        "maximum_core_bet_fraction": settings.portfolio_maximum_core_bet_fraction,
        "maximum_opportunistic_bet_fraction": settings.portfolio_maximum_opportunistic_bet_fraction,
        "maximum_daily_fraction": settings.portfolio_maximum_daily_fraction,
        "maximum_game_fraction": settings.portfolio_maximum_game_fraction,
        "maximum_team_fraction": settings.portfolio_maximum_team_fraction,
        "maximum_market_fraction": settings.portfolio_maximum_market_fraction,
        "maximum_correlated_fraction": settings.portfolio_maximum_correlated_fraction,
        "unit_fraction": settings.portfolio_unit_fraction,
        "reduced_risk_drawdown": settings.portfolio_reduced_risk_drawdown,
        "paused_drawdown": settings.portfolio_paused_drawdown,
        "bankroll_floor_fraction_of_start": settings.portfolio_bankroll_floor_fraction,
        "parlay_enabled": settings.parlay_enabled,
        "parlay_minimum_ev": settings.parlay_minimum_ev,
        "parlay_kelly_fraction": settings.parlay_kelly_fraction,
        "parlay_maximum_fraction": settings.parlay_maximum_fraction,
        "parlay_daily_fraction": settings.parlay_daily_fraction,
    }


app = create_app()
