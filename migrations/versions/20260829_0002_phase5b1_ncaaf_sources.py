"""Phase 5B-1 NCAAF source manifests and canonical identities.

Revision ID: 20260829_0002
Revises: 8c297f23101e
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260829_0002"
down_revision: str | None = "8c297f23101e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "source_manifests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("product", sa.String(128), nullable=False),
        sa.Column("request_parameters", JSON_DOCUMENT, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_timestamps", JSON_DOCUMENT),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(64)),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("stored_bytes", sa.Integer(), nullable=False),
        sa.Column("availability_mode", sa.String(32), nullable=False),
        sa.Column("response_metadata", JSON_DOCUMENT),
        sa.Column("warnings", JSON_DOCUMENT),
        sa.Column("errors", JSON_DOCUMENT),
        sa.Column("supersedes_manifest_id", sa.Uuid()),
        sa.Column("artifact_uri", sa.String(1000), nullable=False),
        sa.Column("artifact_format", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["supersedes_manifest_id"], ["source_manifests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "request_hash", "content_hash", name="uq_source_manifest_version"),
    )
    op.create_index(
        "ix_source_manifest_request_retrieved", "source_manifests", ["provider", "request_hash", "retrieved_at"]
    )
    op.create_index(
        "ix_source_manifest_endpoint_retrieved", "source_manifests", ["provider", "endpoint", "retrieved_at"]
    )
    op.create_table(
        "canonical_programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "canonical_venues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(300), nullable=False),
        sa.Column("timezone", sa.String(64)),
        sa.Column("latitude", sa.String(32)),
        sa.Column("longitude", sa.String(32)),
        sa.Column("elevation", sa.String(32)),
        sa.Column("dome", sa.Boolean()),
        sa.Column("surface", sa.String(100)),
        sa.Column("source_vintage", sa.DateTime(timezone=True)),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "provider_program_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_team_id", sa.String(128), nullable=False),
        sa.Column("canonical_program_id", sa.Uuid(), nullable=False),
        sa.Column("match_confidence", sa.String(16), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_program_id"], ["canonical_programs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_team_id", name="uq_provider_program"),
    )
    op.create_table(
        "program_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_program_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(200), nullable=False),
        sa.Column("effective_start_season", sa.Integer()),
        sa.Column("effective_end_season", sa.Integer()),
        sa.Column("provider", sa.String(64)),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(["canonical_program_id"], ["canonical_programs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_program_id", "alias", "effective_start_season", "effective_end_season", name="uq_program_alias"
        ),
    )
    op.create_table(
        "program_season_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_program_id", sa.Uuid(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(32)),
        sa.Column("conference_name", sa.String(200)),
        sa.Column("conference_provider_id", sa.String(128)),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["canonical_program_id"], ["canonical_programs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_program_id", "season", name="uq_program_season_membership"),
    )
    op.create_index(
        "ix_program_membership_season_class", "program_season_memberships", ["season", "classification"]
    )
    op.create_table(
        "provider_venue_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_venue_id", sa.String(128), nullable=False),
        sa.Column("canonical_venue_id", sa.Uuid(), nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["canonical_venue_id"], ["canonical_venues.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_venue_id", name="uq_provider_venue"),
    )
    with op.batch_alter_table("canonical_events") as batch:
        batch.add_column(sa.Column("home_program_id", sa.Uuid()))
        batch.add_column(sa.Column("away_program_id", sa.Uuid()))
        batch.add_column(sa.Column("venue_id", sa.Uuid()))
        batch.add_column(sa.Column("season", sa.Integer()))
        batch.add_column(sa.Column("week", sa.Integer()))
        batch.add_column(sa.Column("season_type", sa.String(32)))
        batch.add_column(sa.Column("neutral_site", sa.Boolean()))
        batch.add_column(sa.Column("schedule_revision", sa.String(128)))
        batch.add_column(sa.Column("schedule_provenance", JSON_DOCUMENT))
        batch.create_foreign_key(
            "fk_canonical_events_home_program_id_canonical_programs",
            "canonical_programs",
            ["home_program_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_canonical_events_away_program_id_canonical_programs",
            "canonical_programs",
            ["away_program_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_canonical_events_venue_id_canonical_venues",
            "canonical_venues",
            ["venue_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_table(
        "source_artifact_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manifest_id", sa.Uuid(), nullable=False),
        sa.Column("league", sa.String(32), nullable=False),
        sa.Column("season", sa.Integer()),
        sa.Column("week", sa.Integer()),
        sa.Column("artifact_kind", sa.String(64), nullable=False),
        sa.Column("included_game_ids", JSON_DOCUMENT, nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["manifest_id"], ["source_manifests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_id"),
    )
    op.create_index(
        "ix_source_artifact_partition", "source_artifact_indexes", ["league", "season", "week", "artifact_kind"]
    )
    op.create_table(
        "football_game_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manifest_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_game_id", sa.String(128), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid()),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer()),
        sa.Column("season_type", sa.String(32)),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("overtime_periods", sa.Integer()),
        sa.Column("neutral_site", sa.Boolean()),
        sa.Column("home_program_id", sa.Uuid()),
        sa.Column("away_program_id", sa.Uuid()),
        sa.Column("home_classification", sa.String(32)),
        sa.Column("away_classification", sa.String(32)),
        sa.Column("final_home_points", sa.Integer()),
        sa.Column("final_away_points", sa.Integer()),
        sa.Column("target_margin", sa.Integer()),
        sa.Column("target_total", sa.Integer()),
        sa.Column("model_eligible", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.String(128)),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column("supersedes_game_fact_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["manifest_id"], ["source_manifests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["canonical_event_id"], ["canonical_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_program_id"], ["canonical_programs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["away_program_id"], ["canonical_programs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_game_fact_id"], ["football_game_facts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_id", "provider", "provider_game_id", name="uq_football_game_fact_version"),
    )
    op.create_index("ix_football_game_fact_season_eligible", "football_game_facts", ["season", "model_eligible"])
    op.create_index("ix_football_game_fact_provider_game", "football_game_facts", ["provider", "provider_game_id"])


def downgrade() -> None:
    op.drop_index("ix_football_game_fact_provider_game", table_name="football_game_facts")
    op.drop_index("ix_football_game_fact_season_eligible", table_name="football_game_facts")
    op.drop_table("football_game_facts")
    op.drop_index("ix_source_artifact_partition", table_name="source_artifact_indexes")
    op.drop_table("source_artifact_indexes")
    with op.batch_alter_table("canonical_events") as batch:
        batch.drop_constraint("fk_canonical_events_venue_id_canonical_venues", type_="foreignkey")
        batch.drop_constraint("fk_canonical_events_away_program_id_canonical_programs", type_="foreignkey")
        batch.drop_constraint("fk_canonical_events_home_program_id_canonical_programs", type_="foreignkey")
        for column in (
            "schedule_provenance",
            "schedule_revision",
            "neutral_site",
            "season_type",
            "week",
            "season",
            "venue_id",
            "away_program_id",
            "home_program_id",
        ):
            batch.drop_column(column)
    op.drop_table("provider_venue_mappings")
    op.drop_index("ix_program_membership_season_class", table_name="program_season_memberships")
    op.drop_table("program_season_memberships")
    op.drop_table("program_aliases")
    op.drop_table("provider_program_mappings")
    op.drop_table("canonical_venues")
    op.drop_table("canonical_programs")
    op.drop_index("ix_source_manifest_endpoint_retrieved", table_name="source_manifests")
    op.drop_index("ix_source_manifest_request_retrieved", table_name="source_manifests")
    op.drop_table("source_manifests")
