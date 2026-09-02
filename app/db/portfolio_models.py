from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models import MONEY_TYPE, POINT_TYPE, PROBABILITY_TYPE
from app.time import utc_now

FRACTION_TYPE = Numeric(16, 12)
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class RecommendationDecisionRun(Base):
    __tablename__ = "recommendation_decision_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
    league: Mapped[str] = mapped_column(String(32), nullable=False)
    slate_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    portfolio_state: Mapped[str] = mapped_column(String(32), nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False)
    starting_bankroll: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    reserved_exposure: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    peak_equity: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    drawdown_fraction: Mapped[Decimal] = mapped_column(FRACTION_TYPE, nullable=False)
    qualification_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parlay_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    pass_reasons: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    rejection_summary: Mapped[dict[str, int]] = mapped_column(JSON_DOCUMENT, nullable=False)
    analysis_summary: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    watchlist_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("league = 'NCAAF'", name="decision_run_ncaaf"),
        CheckConstraint("status IN ('completed', 'failed')", name="decision_run_status"),
        CheckConstraint("portfolio_state IN ('NORMAL', 'REDUCED_RISK', 'PAUSED')", name="decision_run_state"),
        CheckConstraint("top_n >= 1 AND top_n <= 10", name="decision_run_top_n"),
    )


class RecommendationLeg(Base):
    __tablename__ = "recommendation_legs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recommendation_id: Mapped[UUID] = mapped_column(
        ForeignKey("recommendations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    leg_index: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    market_type: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_side: Mapped[str] = mapped_column(String(32), nullable=False)
    selection: Mapped[str] = mapped_column(String(300), nullable=False)
    point: Mapped[Decimal | None] = mapped_column(POINT_TYPE)
    sportsbook: Mapped[str] = mapped_column(String(100), nullable=False)
    american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    fair_probability: Mapped[Decimal] = mapped_column(PROBABILITY_TYPE, nullable=False)
    implied_probability: Mapped[Decimal] = mapped_column(PROBABILITY_TYPE, nullable=False)
    probability_edge: Mapped[Decimal] = mapped_column(PROBABILITY_TYPE, nullable=False)
    ev_per_unit: Mapped[Decimal] = mapped_column(FRACTION_TYPE, nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("recommendation_id", "leg_index", name="uq_recommendation_leg_index"),
        CheckConstraint("leg_index >= 0 AND leg_index < 3", name="recommendation_leg_index"),
    )


def _prevent_decision_mutation(*_: Any, **__: Any) -> None:
    raise ValueError("Decision runs and recommendation legs are immutable")


for immutable_model in (RecommendationDecisionRun, RecommendationLeg):
    event.listen(immutable_model, "before_update", _prevent_decision_mutation)
    event.listen(immutable_model, "before_delete", _prevent_decision_mutation)
