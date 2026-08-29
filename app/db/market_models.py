from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.time import utc_now

JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
POINT_TYPE = Numeric(10, 3)
CONFIDENCE_TYPE = Numeric(5, 4)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_sport_key: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_league: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_parameters: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    raw_payload: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False)
    warning_metadata: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON_DOCUMENT)
    error_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("ingestion_status IN ('success', 'partial', 'failed')", name="ingestion_status"),
        Index("ix_market_snapshots_provider_league_requested", "provider_name", "canonical_league", "requested_at"),
    )


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    home_team: Mapped[str] = mapped_column(String(200), nullable=False)
    away_team: Mapped[str] = mapped_column(String(200), nullable=False)
    scheduled_start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    match_confidence: Mapped[Decimal] = mapped_column(CONFIDENCE_TYPE, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    match_provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("match_confidence >= 0 AND match_confidence <= 1", name="event_match_confidence"),
        CheckConstraint("review_status IN ('matched', 'needs_review', 'conflict')", name="event_review_status"),
        Index("ix_canonical_events_league_start", "league", "scheduled_start_utc"),
    )


class ProviderEventMapping(Base):
    __tablename__ = "provider_event_mappings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_sport_key: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    match_confidence: Mapped[Decimal] = mapped_column(CONFIDENCE_TYPE, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "provider_sport_key",
            "provider_event_id",
            "canonical_event_id",
            name="uq_provider_event_candidate",
        ),
        CheckConstraint("match_confidence >= 0 AND match_confidence <= 1", name="mapping_match_confidence"),
        CheckConstraint("review_status IN ('matched', 'needs_review', 'conflict')", name="mapping_review_status"),
        Index("ix_provider_event_lookup", "provider_name", "provider_sport_key", "provider_event_id"),
    )


class Sportsbook(Base):
    __tablename__ = "sportsbooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    canonical_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class ProviderSportsbook(Base):
    __tablename__ = "provider_sportsbooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sportsbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("sportsbooks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("provider_name", "provider_identifier", name="uq_provider_sportsbook_identifier"),
    )


class MarketObservation(Base):
    __tablename__ = "market_observations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sportsbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("sportsbooks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_sportsbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_sportsbooks.id", ondelete="RESTRICT"), nullable=False
    )
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_side: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_name: Mapped[str] = mapped_column(String(300), nullable=False)
    point: Mapped[Decimal | None] = mapped_column(POINT_TYPE)
    point_key: Mapped[str] = mapped_column(String(32), nullable=False)
    american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_age_seconds: Mapped[int | None] = mapped_column(Integer)
    freshness_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    match_review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_source: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "event_id",
            "sportsbook_id",
            "market_type",
            "period",
            "selection_side",
            "point_key",
            name="uq_market_observation_identity",
        ),
        CheckConstraint("market_type IN ('moneyline', 'spread', 'total')", name="observation_market_type"),
        CheckConstraint("period IN ('full_game')", name="observation_period"),
        CheckConstraint("selection_side IN ('home', 'away', 'draw', 'over', 'under')", name="selection_side"),
        CheckConstraint("american_odds <= -100 OR american_odds >= 100", name="american_odds_valid"),
        CheckConstraint(
            "(market_type = 'moneyline' AND point IS NULL AND point_key = 'none') OR "
            "(market_type IN ('spread', 'total') AND point IS NOT NULL AND point_key <> 'none')",
            name="observation_point_identity",
        ),
        CheckConstraint("stale_after_seconds > 0", name="stale_after_positive"),
        CheckConstraint("observation_age_seconds IS NULL OR observation_age_seconds >= 0", name="age_nonnegative"),
        CheckConstraint("observation_status IN ('active', 'suspended')", name="observation_status"),
        CheckConstraint("match_review_status IN ('matched', 'needs_review', 'conflict')", name="match_review_status"),
        Index(
            "ix_market_observation_lookup",
            "event_id",
            "sportsbook_id",
            "market_type",
            "period",
            "selection_side",
            "point_key",
            "observed_at",
        ),
    )
