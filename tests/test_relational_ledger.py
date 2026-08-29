from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Bet, BetApproval, BetStateTransition, LedgerEntry, Owner, Portfolio, Settlement
from app.domain.identity import Principal
from app.migration.json_import import import_json_file
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.services.portfolio_service import PortfolioService
from tests.helpers import bet_payload

PRINCIPAL = Principal("ledger-owner", "Ledger Owner")


def _service(repository: SqlAlchemyPortfolioRepository) -> PortfolioService:
    return PortfolioService(repository)


def test_schema_contains_phase2_tables_and_constraints(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {
        "bet_approvals",
        "bet_state_transitions",
        "bets",
        "canonical_events",
        "idempotency_records",
        "ledger_entries",
        "market_observations",
        "market_snapshots",
        "owners",
        "portfolios",
        "provider_event_mappings",
        "provider_sportsbooks",
        "recommendations",
        "settlements",
        "sportsbooks",
    } <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("bets")} >= {
        "provider_event_id",
        "period",
        "point",
        "consensus_probability",
        "fair_probability",
        "recommendation_version",
        "closing_american_odds",
        "realized_pnl",
    }
    assert any(constraint["name"] == "uq_ledger_portfolio_reference" for constraint in inspector.get_unique_constraints("ledger_entries"))


def test_portfolio_creation_creates_exact_initial_funding(
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
) -> None:
    portfolio = repository.get_portfolio(PRINCIPAL, "main")

    assert portfolio["cash"] == portfolio["equity"] == 200.0
    assert portfolio["reserved_stake"] == portfolio["realized_pnl"] == 0.0
    with session_factory() as session:
        entry = session.scalar(select(LedgerEntry))
        assert entry is not None
        assert entry.entry_type == "initial_funding"
        assert entry.amount == Decimal("200.00")


def test_money_rounding_stake_settlement_and_reconciliation(
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
) -> None:
    service = _service(repository)
    placed = service.place_bet(PRINCIPAL, bet_payload(stake=Decimal("10.005")), idempotency_key="round-place")
    assert placed["bankroll_after"] == 189.99

    settled = service.settle_bet(
        PRINCIPAL,
        {"portfolio_id": "main", "bet_id": placed["bet_id"], "result": "win", "payout": Decimal("9.095")},
        idempotency_key="round-settle",
    )
    assert settled["bankroll_after"] == 209.10

    portfolio = service.get_portfolio(PRINCIPAL, "main")
    assert portfolio["cash"] == portfolio["equity"] == 209.10
    assert portfolio["reserved_stake"] == 0.0
    assert portfolio["realized_pnl"] == 9.10
    with session_factory() as session:
        ledger_total = session.scalar(select(func.sum(LedgerEntry.amount)))
        bet = session.scalar(select(Bet))
        settlement = session.scalar(select(Settlement))
        assert ledger_total == Decimal("209.10")
        assert bet is not None and bet.stake == Decimal("10.01")
        assert settlement is not None and settlement.net_payout == Decimal("9.10")


def test_open_stake_is_reserved_exposure_not_realized_loss(repository: SqlAlchemyPortfolioRepository) -> None:
    service = _service(repository)
    service.place_bet(PRINCIPAL, bet_payload(stake=25), idempotency_key=None)

    portfolio = service.get_portfolio(PRINCIPAL, "main")
    stats = service.get_stats(PRINCIPAL, "main")
    assert portfolio["cash"] == 175.0
    assert portfolio["reserved_stake"] == portfolio["open_exposure"] == 25.0
    assert portfolio["equity"] == 200.0
    assert portfolio["realized_pnl"] == 0.0
    assert stats["net_pnl"] == 0.0


def test_placement_rolls_back_bet_and_stake_entry_when_ledger_insert_fails(
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
) -> None:
    service = _service(repository)
    service.get_portfolio(PRINCIPAL, "main")

    def fail_stake_ledger(session: Session, *_: Any) -> None:
        if any(isinstance(item, LedgerEntry) and item.entry_type == "bet_stake" for item in session.new):
            raise RuntimeError("injected ledger failure")

    event.listen(Session, "before_flush", fail_stake_ledger)
    try:
        with pytest.raises(RuntimeError, match="injected ledger failure"):
            service.place_bet(PRINCIPAL, bet_payload(), idempotency_key="rollback-test")
    finally:
        event.remove(Session, "before_flush", fail_stake_ledger)

    assert service.get_portfolio(PRINCIPAL, "main")["cash"] == 200.0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Bet)) == 0
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 1


def test_settlement_rolls_back_state_and_records_when_ledger_insert_fails(
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
) -> None:
    service = _service(repository)
    placed = service.place_bet(PRINCIPAL, bet_payload(), idempotency_key=None)

    def fail_settlement_ledger(session: Session, *_: Any) -> None:
        if any(isinstance(item, LedgerEntry) and item.entry_type == "settlement" for item in session.new):
            raise RuntimeError("injected settlement ledger failure")

    event.listen(Session, "before_flush", fail_settlement_ledger)
    try:
        with pytest.raises(RuntimeError, match="injected settlement ledger failure"):
            service.settle_bet(
                PRINCIPAL,
                {"portfolio_id": "main", "bet_id": placed["bet_id"], "result": "win", "payout": 9.09},
                idempotency_key="settlement-rollback-test",
            )
    finally:
        event.remove(Session, "before_flush", fail_settlement_ledger)

    portfolio = service.get_portfolio(PRINCIPAL, "main")
    assert portfolio["cash"] == 190.0
    assert portfolio["reserved_stake"] == 10.0
    assert portfolio["bets"][0]["status"] == "open"
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Settlement)) == 0
        assert session.scalar(select(func.count()).select_from(BetStateTransition)) == 1
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 2


def test_ledger_entries_reject_normal_orm_update(
    repository: SqlAlchemyPortfolioRepository,
    session_factory: sessionmaker[Session],
) -> None:
    repository.get_portfolio(PRINCIPAL, "main")
    with session_factory() as session:
        entry = session.scalar(select(LedgerEntry))
        assert entry is not None
        entry.amount = Decimal("999.00")
        with pytest.raises(ValueError, match="immutable"):
            session.commit()
        session.rollback()


def test_json_import_is_rerunnable_and_reconciles_legacy_cash(
    tmp_path: Path,
    session_factory: sessionmaker[Session],
) -> None:
    legacy_path = tmp_path / "portfolio_db.json"
    legacy_path.write_text(
        """{
          "portfolios": {
            "legacy": {
              "bankroll": 205.55,
              "bets": [{
                "bet_id": "legacy-bet-1",
                "date": "2026-08-20",
                "sport": "NCAAF",
                "league": "NCAAF",
                "market_type": "spreads",
                "selection": "Example State -3.5",
                "book": "DraftKings",
                "odds": -110,
                "stake": 10,
                "result": "win",
                "payout": 9.09,
                "created_at": "2026-08-20T12:00:00Z"
              }]
            }
          }
        }""",
        encoding="utf-8",
    )
    principal = Principal("legacy-owner", "Legacy Owner")

    first = import_json_file(legacy_path, session_factory, principal, Decimal("200.00"))
    second = import_json_file(legacy_path, session_factory, principal, Decimal("200.00"))

    assert first == {
        "portfolios_imported": 1,
        "bets_imported": 1,
        "adjustments": [{"portfolio_id": "legacy", "amount": "-3.54"}],
    }
    assert second == {"portfolios_imported": 0, "bets_imported": 0, "adjustments": []}
    with session_factory() as session:
        portfolio = session.scalar(select(Portfolio).where(Portfolio.external_id == "legacy"))
        assert portfolio is not None
        total = session.scalar(
            select(func.sum(LedgerEntry.amount)).where(LedgerEntry.portfolio_id == portfolio.id)
        )
        assert total == Decimal("205.55")
        assert session.scalar(select(func.count()).select_from(Owner)) == 1
        assert session.scalar(select(func.count()).select_from(Bet)) == 1
        assert session.scalar(select(func.count()).select_from(BetApproval)) == 1
        assert session.scalar(select(func.count()).select_from(BetStateTransition)) == 2
        assert session.scalar(select(func.count()).select_from(Settlement)) == 1
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 4


def test_timestamps_are_timezone_aware_at_repository_boundary(
    session_factory: sessionmaker[Session],
) -> None:
    fixed = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    repository = SqlAlchemyPortfolioRepository(session_factory, Decimal("200"), clock=lambda: fixed)
    portfolio = repository.get_portfolio(PRINCIPAL, "main")
    assert portfolio["bets"] == []
    with session_factory() as session:
        owner = session.scalar(select(Owner))
        assert owner is not None
        # SQLite strips timezone information; PostgreSQL preserves TIMESTAMPTZ semantics.
        assert owner.created_at.replace(tzinfo=UTC) == fixed
