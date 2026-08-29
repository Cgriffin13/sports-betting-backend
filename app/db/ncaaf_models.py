from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.time import utc_now

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class SourceManifest(Base):
    __tablename__ = "source_manifests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    product: Mapped[str] = mapped_column(String(128), nullable=False)
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_timestamps: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    availability_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    warnings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_DOCUMENT)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_DOCUMENT)
    supersedes_manifest_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_manifests.id", ondelete="RESTRICT")
    )
    artifact_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    artifact_format: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("provider", "request_hash", "content_hash", name="uq_source_manifest_version"),
        Index("ix_source_manifest_request_retrieved", "provider", "request_hash", "retrieved_at"),
        Index("ix_source_manifest_endpoint_retrieved", "provider", "endpoint", "retrieved_at"),
    )


class SourceArtifactIndex(Base):
    __tablename__ = "source_artifact_indexes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_manifests.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    week: Mapped[int | None] = mapped_column(Integer)
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    included_game_ids: Mapped[list[int]] = mapped_column(JSON_DOCUMENT, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (Index("ix_source_artifact_partition", "league", "season", "week", "artifact_kind"),)


class CanonicalProgram(Base):
    __tablename__ = "canonical_programs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ProviderProgramMapping(Base):
    __tablename__ = "provider_program_mappings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_team_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_program_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_programs.id", ondelete="RESTRICT"), nullable=False
    )
    match_confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0000")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (UniqueConstraint("provider", "provider_team_id", name="uq_provider_program"),)


class ProgramAlias(Base):
    __tablename__ = "program_aliases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_program_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_programs.id", ondelete="RESTRICT"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    effective_start_season: Mapped[int | None] = mapped_column(Integer)
    effective_end_season: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(64))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "canonical_program_id", "alias", "effective_start_season", "effective_end_season", name="uq_program_alias"
        ),
    )


class ProgramSeasonMembership(Base):
    __tablename__ = "program_season_memberships"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_program_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_programs.id", ondelete="RESTRICT"), nullable=False
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str | None] = mapped_column(String(32))
    conference_name: Mapped[str | None] = mapped_column(String(200))
    conference_provider_id: Mapped[str | None] = mapped_column(String(128))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")

    __table_args__ = (
        UniqueConstraint("canonical_program_id", "season", name="uq_program_season_membership"),
        Index("ix_program_membership_season_class", "season", "classification"),
    )


class CanonicalVenue(Base):
    __tablename__ = "canonical_venues"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[str | None] = mapped_column(String(32))
    longitude: Mapped[str | None] = mapped_column(String(32))
    elevation: Mapped[str | None] = mapped_column(String(32))
    dome: Mapped[bool | None] = mapped_column(Boolean)
    surface: Mapped[str | None] = mapped_column(String(100))
    source_vintage: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")


class ProviderVenueMapping(Base):
    __tablename__ = "provider_venue_mappings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_venue_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_venues.id", ondelete="RESTRICT"), nullable=False
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="matched")

    __table_args__ = (UniqueConstraint("provider", "provider_venue_id", name="uq_provider_venue"),)


class FootballGameFact(Base):
    __tablename__ = "football_game_facts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    manifest_id: Mapped[UUID] = mapped_column(ForeignKey("source_manifests.id", ondelete="RESTRICT"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_game_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="RESTRICT")
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int | None] = mapped_column(Integer)
    season_type: Mapped[str | None] = mapped_column(String(32))
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    overtime_periods: Mapped[int | None] = mapped_column(Integer)
    neutral_site: Mapped[bool | None] = mapped_column(Boolean)
    home_program_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_programs.id", ondelete="RESTRICT"))
    away_program_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_programs.id", ondelete="RESTRICT"))
    home_classification: Mapped[str | None] = mapped_column(String(32))
    away_classification: Mapped[str | None] = mapped_column(String(32))
    final_home_points: Mapped[int | None] = mapped_column(Integer)
    final_away_points: Mapped[int | None] = mapped_column(Integer)
    target_margin: Mapped[int | None] = mapped_column(Integer)
    target_total: Mapped[int | None] = mapped_column(Integer)
    model_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(128))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    supersedes_game_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("football_game_facts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("manifest_id", "provider", "provider_game_id", name="uq_football_game_fact_version"),
        Index("ix_football_game_fact_season_eligible", "season", "model_eligible"),
        Index("ix_football_game_fact_provider_game", "provider", "provider_game_id"),
    )
