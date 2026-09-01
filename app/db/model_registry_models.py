from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.time import utc_now

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
PROBABILITY_TYPE = Numeric(16, 15)
POINT_TYPE = Numeric(10, 3)


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model_family: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_set_hash: Mapped[str | None] = mapped_column(String(64))
    source_dataset_hashes: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    research_run_hashes: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    calibration_version: Mapped[str | None] = mapped_column(String(100))
    consensus_version: Mapped[str | None] = mapped_column(String(100))
    vig_removal_version: Mapped[str | None] = mapped_column(String(100))
    holdout_result: Mapped[str | None] = mapped_column(String(32))
    promotion_decision: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_locations: Mapped[list[dict[str, str]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    code_build_version: Mapped[str] = mapped_column(String(100), nullable=False)
    registry_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_model_registry_identity"),
        CheckConstraint(
            "status IN ('retained_benchmark', 'shadow_candidate', 'diagnostic', 'rejected', 'retired')",
            name="model_registry_status",
        ),
        Index("ix_model_registry_league_market_status", "league", "market_type", "status"),
    )


class ArtifactRegistryEntry(Base):
    __tablename__ = "artifact_registry_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[str] = mapped_column(String(180), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_hashes: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    locations: Mapped[list[dict[str, str]]] = mapped_column(JSON_DOCUMENT, nullable=False)
    code_build_version: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_DOCUMENT, nullable=False)
    registry_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("artifact_id", "version", name="uq_artifact_registry_identity"),
        CheckConstraint(
            "status IN ('retained_benchmark', 'shadow_candidate', 'diagnostic', 'rejected', 'retired', 'evidence')",
            name="artifact_registry_status",
        ),
        Index("ix_artifact_registry_type_status", "artifact_type", "status"),
    )


class ShadowPrediction(Base):
    __tablename__ = "shadow_predictions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    prediction_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int | None] = mapped_column(Integer)
    prediction_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    intended_horizon: Mapped[str] = mapped_column(String(100), nullable=False)
    model_registry_entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_registry_entries.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_status: Mapped[str] = mapped_column(String(32), nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_side: Mapped[str] = mapped_column(String(32), nullable=False)
    fair_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    fair_point: Mapped[Decimal | None] = mapped_column(POINT_TYPE)
    push_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    source_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_books: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    source_book_count: Mapped[int] = mapped_column(Integer, nullable=False)
    consensus_dispersion: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    quality_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    fair_value_payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    prediction_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("league = 'NCAAF'", name="shadow_prediction_ncaaf"),
        CheckConstraint("season >= 2026", name="shadow_prediction_prospective_season"),
        CheckConstraint("source_book_count >= 2", name="shadow_prediction_book_count"),
        CheckConstraint("market_type IN ('moneyline', 'spread', 'total')", name="shadow_prediction_market"),
        CheckConstraint("selection_side IN ('home', 'away', 'over', 'under')", name="shadow_prediction_side"),
        CheckConstraint("fair_probability IS NULL OR (fair_probability >= 0 AND fair_probability <= 1)", name="shadow_fair_probability"),
        CheckConstraint("push_probability IS NULL OR (push_probability >= 0 AND push_probability <= 1)", name="shadow_push_probability"),
        Index("ix_shadow_prediction_event_market_time", "canonical_event_id", "market_type", "prediction_timestamp"),
    )


class ShadowPredictionOutcome(Base):
    __tablename__ = "shadow_prediction_outcomes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    shadow_prediction_id: Mapped[UUID] = mapped_column(
        ForeignKey("shadow_predictions.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    final_home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    final_away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluation_metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    final_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("final_home_score >= 0 AND final_away_score >= 0", name="shadow_outcome_scores"),
        CheckConstraint("result IN ('win', 'loss', 'push')", name="shadow_outcome_result"),
    )


def _prevent_registry_history_mutation(*_: Any, **__: Any) -> None:
    raise ValueError("Model registry and shadow history are immutable")


for immutable_type in (ModelRegistryEntry, ArtifactRegistryEntry, ShadowPrediction, ShadowPredictionOutcome):
    event.listen(immutable_type, "before_update", _prevent_registry_history_mutation)
    event.listen(immutable_type, "before_delete", _prevent_registry_history_mutation)
