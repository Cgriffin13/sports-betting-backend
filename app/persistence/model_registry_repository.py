from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import CanonicalEvent
from app.db.model_registry_models import (
    ArtifactRegistryEntry,
    ModelRegistryEntry,
    ShadowPrediction,
    ShadowPredictionOutcome,
)
from app.domain.model_registry import (
    ArtifactRegistration,
    ModelRegistration,
    RegistryConflictError,
    RegistryError,
    ShadowOutcomeDraft,
    ShadowPredictionDraft,
)


class SqlAlchemyModelRegistryRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def register_models(self, registrations: Iterable[ModelRegistration]) -> list[ModelRegistryEntry]:
        with self.session_factory.begin() as session:
            return [self._register_model(session, item) for item in registrations]

    def register_artifacts(self, registrations: Iterable[ArtifactRegistration]) -> list[ArtifactRegistryEntry]:
        with self.session_factory.begin() as session:
            return [self._register_artifact(session, item) for item in registrations]

    def list_models(self, *, league: str | None = None) -> list[ModelRegistryEntry]:
        with self.session_factory() as session:
            statement = select(ModelRegistryEntry)
            if league is not None:
                statement = statement.where(ModelRegistryEntry.league == league)
            return list(session.scalars(statement.order_by(ModelRegistryEntry.model_id, ModelRegistryEntry.version)))

    def get_model(self, model_id: str, version: str) -> ModelRegistryEntry | None:
        with self.session_factory() as session:
            return session.scalar(
                select(ModelRegistryEntry).where(
                    ModelRegistryEntry.model_id == model_id,
                    ModelRegistryEntry.version == version,
                )
            )

    def append_prediction(self, draft: ShadowPredictionDraft) -> ShadowPrediction:
        with self.session_factory.begin() as session:
            same_hash = session.scalar(
                select(ShadowPrediction).where(ShadowPrediction.prediction_hash == draft.prediction_hash)
            )
            if same_hash is not None:
                return same_hash
            registry = session.scalar(
                select(ModelRegistryEntry).where(
                    ModelRegistryEntry.model_id == draft.fair_value.model_id,
                    ModelRegistryEntry.version == draft.fair_value.model_version,
                )
            )
            if registry is None:
                raise RegistryError("fair-value model is not registered")
            event = session.get(CanonicalEvent, draft.fair_value.canonical_event_id)
            if event is None:
                raise RegistryError("canonical event does not exist")
            if event.league != "NCAAF" or event.season != draft.season:
                raise RegistryError("shadow prediction event identity does not match NCAAF season")
            if _as_utc(draft.prediction_timestamp) >= _as_utc(event.scheduled_start_utc):
                raise RegistryError("shadow prediction must be recorded before kickoff")
            row = ShadowPrediction(
                prediction_id=draft.prediction_id,
                canonical_event_id=event.id,
                league="NCAAF",
                season=draft.season,
                week=draft.week,
                prediction_timestamp=draft.prediction_timestamp,
                intended_horizon=draft.intended_horizon,
                model_registry_entry_id=registry.id,
                model_id=registry.model_id,
                model_version=registry.version,
                model_status=registry.status,
                market_type=draft.fair_value.market_type,
                selection_side=draft.fair_value.selection_side,
                fair_probability=draft.fair_value.fair_probability,
                fair_point=draft.fair_value.fair_point,
                push_probability=draft.fair_value.push_probability,
                source_as_of=draft.fair_value.source_as_of,
                source_books=list(draft.fair_value.source_books),
                source_book_count=draft.fair_value.source_book_count,
                consensus_dispersion=draft.fair_value.consensus_dispersion,
                quality_metadata=dict(draft.fair_value.uncertainty_quality),
                provenance=dict(draft.fair_value.provenance),
                fair_value_payload=_jsonable(draft.fair_value.payload),
                prediction_hash=draft.prediction_hash,
            )
            session.add(row)
            session.flush()
            return row

    def get_prediction(self, prediction_id: str) -> ShadowPrediction | None:
        with self.session_factory() as session:
            return session.scalar(select(ShadowPrediction).where(ShadowPrediction.prediction_id == prediction_id))

    def list_ncaaf_slate(self, slate_date_utc: date) -> list[CanonicalEvent]:
        start = datetime.combine(slate_date_utc, time.min, UTC)
        end = start + timedelta(days=1)
        with self.session_factory() as session:
            return list(
                session.scalars(
                    select(CanonicalEvent)
                    .where(
                        CanonicalEvent.league == "NCAAF",
                        CanonicalEvent.scheduled_start_utc >= start,
                        CanonicalEvent.scheduled_start_utc < end,
                        CanonicalEvent.review_status == "matched",
                    )
                    .order_by(CanonicalEvent.scheduled_start_utc, CanonicalEvent.id)
                )
            )

    def attach_outcome(
        self,
        draft: ShadowOutcomeDraft,
        *,
        result: str,
        evaluation_metrics: dict[str, Any],
    ) -> ShadowPredictionOutcome:
        with self.session_factory.begin() as session:
            prediction = session.scalar(
                select(ShadowPrediction).where(ShadowPrediction.prediction_id == draft.prediction_id)
            )
            if prediction is None:
                raise RegistryError("shadow prediction does not exist")
            existing = session.scalar(
                select(ShadowPredictionOutcome).where(
                    ShadowPredictionOutcome.shadow_prediction_id == prediction.id
                )
            )
            if existing is not None:
                if existing.outcome_hash != draft.outcome_hash:
                    raise RegistryConflictError("an immutable outcome is already attached")
                return existing
            event = session.get(CanonicalEvent, prediction.canonical_event_id)
            if event is None or _as_utc(draft.final_at) < _as_utc(event.scheduled_start_utc):
                raise RegistryError("final outcome timestamp cannot precede kickoff")
            row = ShadowPredictionOutcome(
                shadow_prediction_id=prediction.id,
                final_home_score=draft.final_home_score,
                final_away_score=draft.final_away_score,
                result=result,
                evaluation_metrics=evaluation_metrics,
                source=draft.source,
                final_at=draft.final_at,
                outcome_hash=draft.outcome_hash,
            )
            session.add(row)
            session.flush()
            return row

    def summarize_shadow(self) -> dict[str, Any]:
        with self.session_factory() as session:
            predictions = list(session.scalars(select(ShadowPrediction)))
            outcomes = list(session.scalars(select(ShadowPredictionOutcome)))
        settled_ids = {item.shadow_prediction_id for item in outcomes}
        return {
            "predictions": len(predictions),
            "outcomes": len(outcomes),
            "pending": sum(item.id not in settled_ids for item in predictions),
            "by_model": _count_by(item.model_id for item in predictions),
            "by_market": _count_by(item.market_type for item in predictions),
        }

    @staticmethod
    def _register_model(session: Session, item: ModelRegistration) -> ModelRegistryEntry:
        existing = session.scalar(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.model_id == item.model_id,
                ModelRegistryEntry.version == item.version,
            )
        )
        if existing is not None:
            if existing.registry_entry_hash != item.entry_hash:
                raise RegistryConflictError("registered model version is immutable")
            return existing
        row = ModelRegistryEntry(
            model_id=item.model_id,
            league=item.league,
            market_type=item.market_type,
            version=item.version,
            status=item.status.value,
            model_family=item.model_family,
            feature_set_hash=item.feature_set_hash,
            source_dataset_hashes=dict(item.source_dataset_hashes),
            research_run_hashes=dict(item.research_run_hashes),
            calibration_version=item.calibration_version,
            consensus_version=item.consensus_version,
            vig_removal_version=item.vig_removal_version,
            holdout_result=item.holdout_result,
            promotion_decision=item.promotion_decision,
            artifact_locations=[dict(value) for value in item.artifact_locations],
            code_build_version=item.code_build_version,
            registry_entry_hash=item.entry_hash,
        )
        session.add(row)
        session.flush()
        return row

    @staticmethod
    def _register_artifact(session: Session, item: ArtifactRegistration) -> ArtifactRegistryEntry:
        existing = session.scalar(
            select(ArtifactRegistryEntry).where(
                ArtifactRegistryEntry.artifact_id == item.artifact_id,
                ArtifactRegistryEntry.version == item.version,
            )
        )
        if existing is not None:
            if existing.registry_entry_hash != item.entry_hash:
                raise RegistryConflictError("registered artifact version is immutable")
            return existing
        row = ArtifactRegistryEntry(
            artifact_id=item.artifact_id,
            artifact_type=item.artifact_type,
            version=item.version,
            status=item.status,
            content_hash=item.content_hash,
            source_hashes=dict(item.source_hashes),
            locations=[dict(value) for value in item.locations],
            code_build_version=item.code_build_version,
            metadata_json=dict(item.metadata),
            registry_entry_hash=item.entry_hash,
        )
        session.add(row)
        session.flush()
        return row


def _count_by(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value) if hasattr(value, "isoformat") or not isinstance(value, (str, int, float, bool, type(None))) else value


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
