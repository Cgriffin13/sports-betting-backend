import argparse
import json

from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.persistence.market_repository import SqlAlchemyMarketDataRepository
from app.providers.odds_api import TheOddsApiProvider
from app.services.market_ingestion_service import MarketIngestionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and persist one provider-neutral market snapshot")
    parser.add_argument("--sport", default="NCAAF")
    parser.add_argument("--markets", nargs="+", default=["h2h", "spreads", "totals"])
    args = parser.parse_args()
    settings = Settings.from_env()
    session_factory = create_session_factory(create_database_engine(settings.database_url))
    provider = TheOddsApiProvider(
        settings.odds_api_key,
        timeout_seconds=settings.provider_timeout_seconds,
        max_retries=settings.provider_max_retries,
        backoff_seconds=settings.provider_backoff_seconds,
        cache_ttl_seconds=settings.provider_cache_ttl_seconds,
        low_quota_threshold=settings.provider_low_quota_threshold,
    )
    repository = SqlAlchemyMarketDataRepository(
        session_factory,
        freshness_seconds=settings.market_freshness_seconds,
    )
    result = MarketIngestionService(provider, repository).ingest(args.sport.upper(), args.markets)
    persisted = result.persisted
    print(
        json.dumps(
            {
                "snapshot_id": str(persisted.snapshot_id) if persisted else None,
                "league": result.fetch.canonical_league,
                "events_received": len(result.fetch.games),
                "events_created": persisted.events_created if persisted else 0,
                "observations_created": persisted.observations_created if persisted else 0,
                "warnings": list(persisted.warnings) if persisted else [],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
