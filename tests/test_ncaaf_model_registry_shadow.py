from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from app.db.market_models import CanonicalEvent
from app.db.model_registry_models import (
    ArtifactRegistryEntry,
    ModelRegistryEntry,
    ShadowPrediction,
    ShadowPredictionOutcome,
)
from app.domain.model_registry import (
    NCAAF_MORNING_HORIZON,
    ConsensusFairValueInput,
    ModelStatus,
    RegistryConflictError,
    RegistryError,
    ShadowOutcomeDraft,
    ShadowPredictionDraft,
)
from app.persistence.model_registry_repository import SqlAlchemyModelRegistryRepository
from app.research.ncaaf.model_registry import (
    build_registry_manifest,
    registrations_from_manifest,
    registered_models,
    validate_registry_manifest,
    verify_authoritative_reports,
)
from app.services.model_registry_service import FairValueService, ShadowPredictionService


def test_registry_manifest_is_deterministic_and_preserves_holdout_decision() -> None:
    first = build_registry_manifest()
    second = build_registry_manifest()

    assert first == second
    assert validate_registry_manifest(first) == []
    assert verify_authoritative_reports(_repo_root()) == []
    retained = [item for item in first["models"] if item["status"] == "retained_benchmark"]
    assert {item["market_type"] for item in retained} == {"margin", "moneyline", "spread", "total"}
    assert {item["model_family"] for item in retained} == {"market_consensus"}
    rejected = {item["model_id"] for item in first["models"] if item["status"] == "rejected"}
    assert "ncaaf-market-ridge-total-blend-v1" in rejected


def test_registry_and_shadow_schema_compile_for_postgresql() -> None:
    for model in (ModelRegistryEntry, ArtifactRegistryEntry, ShadowPrediction, ShadowPredictionOutcome):
        sql = str(CreateTable(cast(Table, model.__table__)).compile(dialect=postgresql.dialect()))
        assert "JSONB" in sql or model is ShadowPredictionOutcome


def test_integer_line_requires_explicit_push_mass() -> None:
    with pytest.raises(RegistryError, match="nonzero push"):
        ConsensusFairValueInput(
            canonical_event_id=uuid4(),
            market_type="spread",
            selection_side="home",
            fair_probability=Decimal("0.50"),
            fair_point=Decimal("-3"),
            push_probability=Decimal("0"),
            as_of=datetime(2026, 9, 5, 13, tzinfo=UTC),
            source_books=("draftkings", "fanduel"),
            consensus_dispersion=Decimal("0.01"),
            quality_metadata={},
            provenance={},
        )


def test_registered_version_is_immutable(session_factory: sessionmaker[Session]) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    original = registered_models()[0]
    repository.register_models([original])
    assert repository.register_models([original])[0].registry_entry_hash == original.entry_hash

    changed = replace(original, status=ModelStatus.DIAGNOSTIC, promotion_decision="diagnostic_not_fair_value")
    with pytest.raises(RegistryConflictError, match="immutable"):
        repository.register_models([changed])


def test_machine_manifest_sync_is_idempotent(session_factory: sessionmaker[Session]) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    models, artifacts = registrations_from_manifest(build_registry_manifest())
    repository.register_models(models)
    repository.register_artifacts(artifacts)
    repository.register_models(models)
    repository.register_artifacts(artifacts)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ModelRegistryEntry)) == 7
        assert session.scalar(select(func.count()).select_from(ArtifactRegistryEntry)) == 4


def test_diagnostic_and_rejected_models_cannot_provide_fair_value(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    models = registered_models()
    rows = repository.register_models(models)
    event = _event(session_factory)
    value = _consensus(event.id)

    for row in rows:
        if row.status in {"diagnostic", "rejected"}:
            with pytest.raises(RegistryError, match="retained benchmark"):
                FairValueService().quote(row, value)


def test_fair_value_contract_excludes_executable_price_and_is_deterministic(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    registration = next(item for item in registered_models() if item.market_type == "total")
    row = repository.register_models([registration])[0]
    event = _event(session_factory)
    value = _consensus(event.id)

    quote = FairValueService().quote(row, value)

    assert quote.fair_value_hash == FairValueService().quote(row, value).fair_value_hash
    assert quote.model_status is ModelStatus.RETAINED_BENCHMARK
    assert quote.source_book_count == 3
    assert "best_executable_price" not in quote.payload
    assert "american_odds" not in quote.payload


def test_shadow_predictions_append_and_outcomes_do_not_mutate_prediction(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    registration = next(item for item in registered_models() if item.market_type == "total")
    registry_row = repository.register_models([registration])[0]
    event = _event(session_factory)
    quote = FairValueService().quote(registry_row, _consensus(event.id))
    service = ShadowPredictionService(repository)
    draft = ShadowPredictionDraft(
        fair_value=quote,
        season=2026,
        week=1,
        prediction_timestamp=quote.source_as_of,
        intended_horizon=NCAAF_MORNING_HORIZON,
    )

    first = service.record(draft)
    assert service.record(draft).id == first.id
    moved_quote = replace(
        quote,
        fair_point=Decimal("54.5"),
        source_as_of=quote.source_as_of + timedelta(minutes=5),
    )
    moved = service.record(
        ShadowPredictionDraft(
            fair_value=moved_quote,
            season=2026,
            week=1,
            prediction_timestamp=moved_quote.source_as_of,
            intended_horizon=NCAAF_MORNING_HORIZON,
        )
    )
    assert moved.id != first.id
    original_payload = dict(first.fair_value_payload)

    outcome = ShadowOutcomeDraft(
        prediction_id=first.prediction_id,
        final_home_score=31,
        final_away_score=24,
        source="official_final",
        final_at=datetime(2026, 9, 6, 1, tzinfo=UTC),
    )
    attached = service.attach_outcome(outcome)
    assert attached.result == "win"
    assert service.attach_outcome(outcome).id == attached.id
    assert repository.get_prediction(first.prediction_id).fair_value_payload == original_payload  # type: ignore[union-attr]

    with pytest.raises(RegistryConflictError, match="already attached"):
        service.attach_outcome(replace(outcome, final_home_score=30))
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ShadowPrediction)) == 2
        assert session.scalar(select(func.count()).select_from(ShadowPredictionOutcome)) == 1


def test_prediction_preserves_model_version_after_new_registry_version(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    original = next(item for item in registered_models() if item.market_type == "moneyline")
    original_row = repository.register_models([original])[0]
    event = _event(session_factory)
    quote = FairValueService().quote(original_row, _consensus(event.id, market="moneyline"))
    prediction = ShadowPredictionService(repository).record(
        ShadowPredictionDraft(quote, 2026, 1, quote.source_as_of, NCAAF_MORNING_HORIZON)
    )
    repository.register_models([replace(original, version="2.0.0")])

    stored = repository.get_prediction(prediction.prediction_id)
    assert stored is not None
    assert stored.model_version == "1.0.0"
    assert stored.model_id == original.model_id


def test_shadow_timestamp_must_be_prospective_morning_and_pregame(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    registration = next(item for item in registered_models() if item.market_type == "total")
    row = repository.register_models([registration])[0]
    event = _event(session_factory)
    quote = FairValueService().quote(row, _consensus(event.id))
    service = ShadowPredictionService(repository)

    with pytest.raises(RegistryError, match="beginning with 2026"):
        ShadowPredictionDraft(quote, 2025, 1, quote.source_as_of, NCAAF_MORNING_HORIZON)
    late = replace(quote, source_as_of=event.scheduled_start_utc)
    with pytest.raises(RegistryError, match="before kickoff"):
        service.record(ShadowPredictionDraft(late, 2026, 1, late.source_as_of, NCAAF_MORNING_HORIZON))


def test_shadow_slate_uses_first_kickoff_minus_three_hours(
    session_factory: sessionmaker[Session],
) -> None:
    repository = SqlAlchemyModelRegistryRepository(session_factory)
    first = _event(session_factory)
    with session_factory.begin() as session:
        session.add(
            CanonicalEvent(
                id=uuid4(),
                league="NCAAF",
                home_team="Team C",
                away_team="Team D",
                scheduled_start_utc=first.scheduled_start_utc + timedelta(hours=3),
                event_status="scheduled",
                match_confidence=Decimal("1"),
                review_status="matched",
                match_provenance={"method": "test"},
                season=2026,
                week=1,
            )
        )

    plan = ShadowPredictionService(repository).plan_slate(first.scheduled_start_utc.date())

    assert plan.prediction_cutoff == datetime(2026, 9, 5, 16, tzinfo=UTC)
    assert len(plan.canonical_event_ids) == 2


def _event(session_factory: sessionmaker[Session]) -> CanonicalEvent:
    with session_factory.begin() as session:
        event = CanonicalEvent(
            id=uuid4(),
            league="NCAAF",
            home_team="Team A",
            away_team="Team B",
            scheduled_start_utc=datetime(2026, 9, 5, 19, tzinfo=UTC),
            event_status="scheduled",
            match_confidence=Decimal("1"),
            review_status="matched",
            match_provenance={"method": "test"},
            season=2026,
            week=1,
        )
        session.add(event)
        session.flush()
        return event


def _consensus(event_id: object, *, market: str = "total") -> ConsensusFairValueInput:
    return ConsensusFairValueInput(
        canonical_event_id=event_id,  # type: ignore[arg-type]
        market_type=market,
        selection_side="home" if market == "moneyline" else "over",
        fair_probability=Decimal("0.53"),
        fair_point=None if market == "moneyline" else Decimal("52.5"),
        push_probability=Decimal("0"),
        as_of=datetime(2026, 9, 5, 13, tzinfo=UTC),
        source_books=("draftkings", "fanduel", "betmgm"),
        consensus_dispersion=Decimal("0.012"),
        quality_metadata={"fresh": True},
        provenance={"snapshot_ids": ["a", "b", "c"]},
    )


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]
