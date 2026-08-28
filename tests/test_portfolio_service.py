from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.errors import (
    BetAlreadySettledError,
    BetNotFoundError,
    InsufficientBankrollError,
    InvalidLossPayoutError,
)
from app.domain.identity import Principal
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository
from app.services.portfolio_service import PortfolioService

PRINCIPAL = Principal("owner-primary", "Primary Owner")


def service(session_factory: sessionmaker[Session]) -> PortfolioService:
    repository = SqlAlchemyPortfolioRepository(
        session_factory,
        Decimal("200.00"),
        clock=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )
    return PortfolioService(repository)


def bet_data() -> dict[str, object]:
    return {
        "portfolio_id": "main",
        "date": date(2026, 8, 29),
        "sport": "NCAAF",
        "league": "NCAAF",
        "market_type": "h2h",
        "selection": "Home",
        "book": "DraftKings",
        "odds": -110,
        "stake": Decimal("10.00"),
    }


def test_service_places_and_settles_without_fastapi_network_or_disk(
    session_factory: sessionmaker[Session],
) -> None:
    portfolio_service = service(session_factory)
    placed = portfolio_service.place_bet(PRINCIPAL, bet_data(), idempotency_key="place-1")
    settled = portfolio_service.settle_bet(
        PRINCIPAL,
        {
            "portfolio_id": "main",
            "bet_id": placed["bet_id"],
            "result": "win",
            "payout": Decimal("9.09"),
        },
        idempotency_key="settle-1",
    )
    assert placed["bankroll_after"] == 190.0
    assert settled["bankroll_after"] == 209.09
    portfolio = portfolio_service.get_portfolio(PRINCIPAL, "main")
    assert portfolio["cash"] == 209.09
    assert portfolio["reserved_stake"] == 0.0
    assert portfolio["equity"] == 209.09


def test_service_rejects_insufficient_bankroll(session_factory: sessionmaker[Session]) -> None:
    portfolio_service = service(session_factory)
    data = bet_data()
    data["stake"] = Decimal("201.00")
    with pytest.raises(InsufficientBankrollError):
        portfolio_service.place_bet(PRINCIPAL, data, idempotency_key=None)


def test_service_settlement_errors(session_factory: sessionmaker[Session]) -> None:
    portfolio_service = service(session_factory)
    placed = portfolio_service.place_bet(PRINCIPAL, bet_data(), idempotency_key=None)
    settlement = {
        "portfolio_id": "main",
        "bet_id": placed["bet_id"],
        "result": "loss",
        "payout": Decimal("-5.00"),
    }
    with pytest.raises(InvalidLossPayoutError):
        portfolio_service.settle_bet(PRINCIPAL, settlement, idempotency_key=None)
    settlement.update(result="push", payout=Decimal("0.00"))
    portfolio_service.settle_bet(PRINCIPAL, settlement, idempotency_key=None)
    with pytest.raises(BetAlreadySettledError):
        portfolio_service.settle_bet(PRINCIPAL, settlement, idempotency_key=None)
    settlement["bet_id"] = "missing"
    with pytest.raises(BetNotFoundError):
        portfolio_service.settle_bet(PRINCIPAL, settlement, idempotency_key=None)


def test_open_stake_is_reserved_not_realized_loss(session_factory: sessionmaker[Session]) -> None:
    portfolio_service = service(session_factory)
    portfolio_service.place_bet(PRINCIPAL, bet_data(), idempotency_key=None)
    portfolio = portfolio_service.get_portfolio(PRINCIPAL, "main")
    stats = portfolio_service.get_stats(PRINCIPAL, "main")
    assert portfolio["cash"] == 190.0
    assert portfolio["reserved_stake"] == 10.0
    assert portfolio["equity"] == 200.0
    assert portfolio["realized_pnl"] == 0.0
    assert stats["net_pnl"] == 0.0
