from __future__ import annotations

import argparse
from datetime import date, datetime

from app.config import Settings
from app.db.session import create_database_engine, create_session_factory
from app.persistence.pricing_repository import SqlAlchemyPricingObservationRepository
from app.schemas.opportunities import PricingAnalysisResponse
from app.services.pricing_service import PricingService, build_pricing_policy


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay market-consensus pricing from stored observations")
    parser.add_argument("--sport", action="append", dest="sports", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--as-of", type=datetime.fromisoformat, required=True)
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        default=None,
        help="Repeat for each market; defaults to moneyline, spread, and total",
    )
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--pricing-policy-version")
    parser.add_argument("--qualification-policy-version")
    args = parser.parse_args()

    settings = Settings.from_env()
    repository = SqlAlchemyPricingObservationRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    service = PricingService(
        repository,
        build_pricing_policy(
            minimum_books=settings.pricing_minimum_books,
            minimum_ev=settings.pricing_minimum_ev,
            minimum_probability_edge=settings.pricing_minimum_probability_edge,
            outlier_threshold=settings.pricing_outlier_threshold,
            maximum_dispersion=settings.pricing_maximum_dispersion,
            supported_books=settings.pricing_supported_books,
        ),
    )
    analysis = service.analyze(
        leagues=args.sports,
        market_types=args.markets or ["moneyline", "spread", "total"],
        as_of=args.as_of,
        event_date=args.date,
        top_n=args.top_n,
        pricing_policy_version=args.pricing_policy_version,
        qualification_policy_version=args.qualification_policy_version,
    )
    print(PricingAnalysisResponse.from_domain(analysis).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
