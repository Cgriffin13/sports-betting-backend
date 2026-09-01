from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.session import create_database_engine, create_session_factory
from app.domain.model_registry import (
    ConsensusFairValueInput,
    ShadowOutcomeDraft,
    ShadowPredictionDraft,
)
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.services.model_registry_service import FairValueService, ShadowPredictionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Prospective NCAAF shadow records")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--input", type=Path, required=True, help="Offline consensus JSON; no provider call is implied")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("prediction_id")
    outcome = sub.add_parser("attach-outcome")
    outcome.add_argument("prediction_id")
    outcome.add_argument("--home-score", type=int, required=True)
    outcome.add_argument("--away-score", type=int, required=True)
    outcome.add_argument("--source", required=True)
    outcome.add_argument("--final-at", required=True)
    sub.add_parser("summarize")
    slate = sub.add_parser("plan-slate")
    slate.add_argument("--date", required=True, help="UTC calendar date")
    args = parser.parse_args()
    repository = _repository()
    shadow = ShadowPredictionService(repository)

    if args.command == "plan-slate":
        plan = shadow.plan_slate(date.fromisoformat(args.date))
        print(
            json.dumps(
                {
                    "slate_date_timezone": "UTC",
                    "slate_date": str(plan.slate_date_utc),
                    "prediction_cutoff": plan.prediction_cutoff.isoformat() if plan.prediction_cutoff else None,
                    "canonical_event_ids": plan.canonical_event_ids,
                },
                indent=2,
            )
        )
        return

    if args.command == "generate":
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        registration = repository.get_model(payload["model_id"], payload["model_version"])
        if registration is None:
            raise SystemExit("registered retained benchmark not found")
        fair_value = FairValueService().quote(registration, _consensus_input(payload))
        draft = ShadowPredictionDraft(
            fair_value=fair_value,
            season=int(payload["season"]),
            week=payload.get("week"),
            prediction_timestamp=_datetime(payload["prediction_timestamp"]),
            intended_horizon=payload["intended_horizon"],
        )
        prediction = shadow.record(draft)
        print(json.dumps({"prediction_id": prediction.prediction_id, "prediction_hash": prediction.prediction_hash}))
        return
    if args.command == "inspect":
        inspected = repository.get_prediction(args.prediction_id)
        if inspected is None:
            raise SystemExit("prediction not found")
        print(json.dumps(inspected.fair_value_payload, indent=2, sort_keys=True))
        return
    if args.command == "attach-outcome":
        attached = shadow.attach_outcome(
            ShadowOutcomeDraft(
                prediction_id=args.prediction_id,
                final_home_score=args.home_score,
                final_away_score=args.away_score,
                source=args.source,
                final_at=_datetime(args.final_at),
            )
        )
        print(json.dumps({"outcome_hash": attached.outcome_hash, "result": attached.result}))
        return
    print(json.dumps(repository.summarize_shadow(), indent=2, sort_keys=True))


def _repository() -> SqlAlchemyModelRegistryRepository:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    return SqlAlchemyModelRegistryRepository(create_session_factory(create_database_engine(database_url)))


def _consensus_input(payload: dict[str, Any]) -> ConsensusFairValueInput:
    return ConsensusFairValueInput(
        canonical_event_id=UUID(payload["canonical_event_id"]),
        market_type=payload["market_type"],
        selection_side=payload["selection_side"],
        fair_probability=_decimal(payload.get("fair_probability")),
        fair_point=_decimal(payload.get("fair_point")),
        push_probability=_decimal(payload.get("push_probability")),
        as_of=_datetime(payload["source_as_of"]),
        source_books=tuple(payload["source_books"]),
        consensus_dispersion=_decimal(payload.get("consensus_dispersion")),
        quality_metadata=payload.get("quality_metadata", {}),
        provenance=payload.get("provenance", {}),
    )


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("timestamps must be timezone-aware")
    return parsed


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


if __name__ == "__main__":
    main()
