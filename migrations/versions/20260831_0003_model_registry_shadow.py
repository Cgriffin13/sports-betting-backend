"""Phase 5B-10 model registry and prospective shadow records.

Revision ID: 20260831_0003
Revises: 20260829_0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0003"
down_revision: str | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "model_registry_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("market_type", sa.String(32), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_family", sa.String(100), nullable=False),
        sa.Column("feature_set_hash", sa.String(64)),
        sa.Column("source_dataset_hashes", JSON_DOCUMENT, nullable=False),
        sa.Column("research_run_hashes", JSON_DOCUMENT, nullable=False),
        sa.Column("calibration_version", sa.String(100)),
        sa.Column("consensus_version", sa.String(100)),
        sa.Column("vig_removal_version", sa.String(100)),
        sa.Column("holdout_result", sa.String(32)),
        sa.Column("promotion_decision", sa.String(200), nullable=False),
        sa.Column("artifact_locations", JSON_DOCUMENT, nullable=False),
        sa.Column("code_build_version", sa.String(100), nullable=False),
        sa.Column("registry_entry_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('retained_benchmark', 'shadow_candidate', 'diagnostic', 'rejected', 'retired')",
            name="model_registry_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "version", name="uq_model_registry_identity"),
        sa.UniqueConstraint("registry_entry_hash"),
    )
    op.create_index(
        "ix_model_registry_league_market_status",
        "model_registry_entries",
        ["league", "market_type", "status"],
    )
    op.create_table(
        "artifact_registry_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.String(180), nullable=False),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_hashes", JSON_DOCUMENT, nullable=False),
        sa.Column("locations", JSON_DOCUMENT, nullable=False),
        sa.Column("code_build_version", sa.String(100), nullable=False),
        sa.Column("metadata", JSON_DOCUMENT, nullable=False),
        sa.Column("registry_entry_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('retained_benchmark', 'shadow_candidate', 'diagnostic', 'rejected', 'retired', 'evidence')",
            name="artifact_registry_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "version", name="uq_artifact_registry_identity"),
        sa.UniqueConstraint("registry_entry_hash"),
    )
    op.create_index(
        "ix_artifact_registry_type_status",
        "artifact_registry_entries",
        ["artifact_type", "status"],
    )
    op.create_table(
        "shadow_predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prediction_id", sa.String(80), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid(), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer()),
        sa.Column("prediction_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intended_horizon", sa.String(100), nullable=False),
        sa.Column("model_registry_entry_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("model_status", sa.String(32), nullable=False),
        sa.Column("market_type", sa.String(32), nullable=False),
        sa.Column("selection_side", sa.String(32), nullable=False),
        sa.Column("fair_probability", sa.Numeric(16, 15)),
        sa.Column("fair_point", sa.Numeric(10, 3)),
        sa.Column("push_probability", sa.Numeric(16, 15)),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_books", JSON_DOCUMENT, nullable=False),
        sa.Column("source_book_count", sa.Integer(), nullable=False),
        sa.Column("consensus_dispersion", sa.Numeric(16, 15)),
        sa.Column("quality_metadata", JSON_DOCUMENT, nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("fair_value_payload", JSON_DOCUMENT, nullable=False),
        sa.Column("prediction_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("league = 'NCAAF'", name="shadow_prediction_ncaaf"),
        sa.CheckConstraint("season >= 2026", name="shadow_prediction_prospective_season"),
        sa.CheckConstraint("source_book_count >= 2", name="shadow_prediction_book_count"),
        sa.CheckConstraint(
            "market_type IN ('moneyline', 'spread', 'total')",
            name="shadow_prediction_market",
        ),
        sa.CheckConstraint(
            "selection_side IN ('home', 'away', 'over', 'under')",
            name="shadow_prediction_side",
        ),
        sa.CheckConstraint(
            "fair_probability IS NULL OR (fair_probability >= 0 AND fair_probability <= 1)",
            name="shadow_fair_probability",
        ),
        sa.CheckConstraint(
            "push_probability IS NULL OR (push_probability >= 0 AND push_probability <= 1)",
            name="shadow_push_probability",
        ),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_registry_entry_id"], ["model_registry_entries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_hash"),
        sa.UniqueConstraint("prediction_id"),
    )
    op.create_index("ix_shadow_predictions_canonical_event_id", "shadow_predictions", ["canonical_event_id"])
    op.create_index("ix_shadow_predictions_model_registry_entry_id", "shadow_predictions", ["model_registry_entry_id"])
    op.create_index(
        "ix_shadow_prediction_event_market_time",
        "shadow_predictions",
        ["canonical_event_id", "market_type", "prediction_timestamp"],
    )
    op.create_table(
        "shadow_prediction_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shadow_prediction_id", sa.Uuid(), nullable=False),
        sa.Column("final_home_score", sa.Integer(), nullable=False),
        sa.Column("final_away_score", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("evaluation_metrics", JSON_DOCUMENT, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("final_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "final_home_score >= 0 AND final_away_score >= 0",
            name="shadow_outcome_scores",
        ),
        sa.CheckConstraint(
            "result IN ('win', 'loss', 'push')",
            name="shadow_outcome_result",
        ),
        sa.ForeignKeyConstraint(["shadow_prediction_id"], ["shadow_predictions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("outcome_hash"),
        sa.UniqueConstraint("shadow_prediction_id"),
    )


def downgrade() -> None:
    op.drop_table("shadow_prediction_outcomes")
    op.drop_index("ix_shadow_prediction_event_market_time", table_name="shadow_predictions")
    op.drop_index("ix_shadow_predictions_model_registry_entry_id", table_name="shadow_predictions")
    op.drop_index("ix_shadow_predictions_canonical_event_id", table_name="shadow_predictions")
    op.drop_table("shadow_predictions")
    op.drop_index("ix_artifact_registry_type_status", table_name="artifact_registry_entries")
    op.drop_table("artifact_registry_entries")
    op.drop_index("ix_model_registry_league_market_status", table_name="model_registry_entries")
    op.drop_table("model_registry_entries")
