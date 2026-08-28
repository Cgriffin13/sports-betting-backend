from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.time import utc_now

MONEY_TYPE = Numeric(18, 2)
PROBABILITY_TYPE = Numeric(12, 10)
POINT_TYPE = Numeric(10, 3)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="owner_status"),)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False, index=True)
    starting_capital: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("starting_capital >= 0", name="portfolio_starting_capital_nonnegative"),
        CheckConstraint("status IN ('active', 'archived')", name="portfolio_status"),
    )


class Recommendation(Base):
    """Future-compatible decision snapshot; no recommendation engine exists yet."""

    __tablename__ = "recommendations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(200))
    league: Mapped[str] = mapped_column(String(64), nullable=False)
    market_type: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="full_game")
    selection: Mapped[str] = mapped_column(String(300), nullable=False)
    point: Mapped[Decimal | None] = mapped_column(POINT_TYPE)
    sportsbook: Mapped[str] = mapped_column(String(100), nullable=False)
    offered_american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    model_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    consensus_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    fair_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    probability_edge: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    ev_per_unit: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    uncertainty_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recommendation_version: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'approved', 'rejected', 'expired')", name="recommendation_status"),
    )


class Bet(Base):
    __tablename__ = "bets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(200))
    bet_date: Mapped[date] = mapped_column(Date, nullable=False)
    sport: Mapped[str] = mapped_column(String(32), nullable=False)
    league: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(300))
    home_team: Mapped[str | None] = mapped_column(String(200))
    away_team: Mapped[str | None] = mapped_column(String(200))
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    market_type: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(32), nullable=False, default="full_game")
    selection: Mapped[str] = mapped_column(String(300), nullable=False)
    point: Mapped[Decimal | None] = mapped_column(POINT_TYPE)
    sportsbook: Mapped[str] = mapped_column(String(100), nullable=False)
    entry_american_odds: Mapped[int] = mapped_column(Integer, nullable=False)
    stake: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    model_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    book_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    consensus_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    fair_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    probability_edge: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    ev_per_unit: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    recommendation_version: Mapped[str | None] = mapped_column(String(100))
    model_version: Mapped[str | None] = mapped_column(String(100))
    policy_version: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_source: Mapped[str | None] = mapped_column(String(64))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    result: Mapped[str | None] = mapped_column(String(16))
    closing_american_odds: Mapped[int | None] = mapped_column(Integer)
    closing_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[Decimal | None] = mapped_column(MONEY_TYPE)

    __table_args__ = (
        CheckConstraint("stake > 0", name="bet_stake_positive"),
        CheckConstraint("status IN ('open', 'settled', 'void')", name="bet_status"),
        CheckConstraint("result IS NULL OR result IN ('win', 'loss', 'push', 'void')", name="bet_result"),
    )


class Settlement(Base):
    __tablename__ = "settlements"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bet_id: Mapped[UUID] = mapped_column(ForeignKey("bets.id", ondelete="RESTRICT"), unique=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    net_payout: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual_api")
    closing_american_odds: Mapped[int | None] = mapped_column(Integer)
    closing_probability: Mapped[Decimal | None] = mapped_column(PROBABILITY_TYPE)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (CheckConstraint("outcome IN ('win', 'loss', 'push', 'void')", name="settlement_outcome"),)


class BetApproval(Base):
    __tablename__ = "bet_approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bet_id: Mapped[UUID] = mapped_column(ForeignKey("bets.id", ondelete="RESTRICT"), unique=True, nullable=False)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"), nullable=False, index=True)
    recommendation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recommendations.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class BetStateTransition(Base):
    __tablename__ = "bet_state_transitions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    bet_id: Mapped[UUID] = mapped_column(ForeignKey("bets.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint("from_status IS NULL OR from_status IN ('open', 'settled', 'void')", name="from_status"),
        CheckConstraint("to_status IN ('open', 'settled', 'void')", name="to_status"),
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    portfolio_id: Mapped[UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="RESTRICT"), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY_TYPE, nullable=False)
    related_bet_id: Mapped[UUID | None] = mapped_column(ForeignKey("bets.id", ondelete="RESTRICT"), index=True)
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        UniqueConstraint("portfolio_id", "reference", name="uq_ledger_portfolio_reference"),
        CheckConstraint(
            "entry_type IN ('initial_funding', 'bet_stake', 'settlement', 'adjustment', 'refund_void')",
            name="ledger_entry_type",
        ),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"), index=True)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (UniqueConstraint("owner_id", "endpoint", "key", name="uq_idempotency_owner_endpoint_key"),)


def _prevent_ledger_mutation(*_: Any, **__: Any) -> None:
    raise ValueError("Ledger entries are immutable")


event.listen(LedgerEntry, "before_update", _prevent_ledger_mutation)
event.listen(LedgerEntry, "before_delete", _prevent_ledger_mutation)
