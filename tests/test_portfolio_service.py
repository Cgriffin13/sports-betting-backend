from datetime import date

import pytest

from app.persistence.memory_repository import InMemoryPortfolioRepository
from app.services.portfolio_service import (
    BetAlreadySettledError,
    BetNotFoundError,
    InsufficientBankrollError,
    InvalidLossPayoutError,
    PortfolioService,
)


def service() -> tuple[PortfolioService, InMemoryPortfolioRepository]:
    repository = InMemoryPortfolioRepository(200.0)
    portfolio_service = PortfolioService(
        repository,
        200.0,
        clock=lambda: "2026-08-29T00:00:00+00:00",
        id_factory=lambda: "bet-fixed",
    )
    return portfolio_service, repository


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
        "stake": 10.0,
    }


def test_service_places_and_settles_without_fastapi_or_disk() -> None:
    portfolio_service, repository = service()
    placed = portfolio_service.place_bet(bet_data())
    settled = portfolio_service.settle_bet(
        {"portfolio_id": "main", "bet_id": "bet-fixed", "result": "win", "payout": 9.09}
    )
    assert placed == {"message": "Bet recorded", "bet_id": "bet-fixed", "bankroll_after": 190.0}
    assert settled["bankroll_after"] == pytest.approx(209.09)
    assert repository.data["portfolios"]["main"]["bets"][0]["created_at"].endswith("+00:00")
    assert repository.save_count == 2


def test_service_rejects_insufficient_bankroll() -> None:
    portfolio_service, _ = service()
    data = bet_data()
    data["stake"] = 201.0
    with pytest.raises(InsufficientBankrollError):
        portfolio_service.place_bet(data)


def test_service_settlement_errors() -> None:
    portfolio_service, _ = service()
    portfolio_service.place_bet(bet_data())
    with pytest.raises(InvalidLossPayoutError):
        portfolio_service.settle_bet(
            {"portfolio_id": "main", "bet_id": "bet-fixed", "result": "loss", "payout": -5.0}
        )
    portfolio_service.settle_bet(
        {"portfolio_id": "main", "bet_id": "bet-fixed", "result": "push", "payout": 0.0}
    )
    with pytest.raises(BetAlreadySettledError):
        portfolio_service.settle_bet(
            {"portfolio_id": "main", "bet_id": "bet-fixed", "result": "push", "payout": 0.0}
        )
    with pytest.raises(BetNotFoundError):
        portfolio_service.settle_bet(
            {"portfolio_id": "main", "bet_id": "missing", "result": "push", "payout": 0.0}
        )


def test_service_stats_preserve_prototype_hit_rate_semantics() -> None:
    portfolio_service, repository = service()
    repository.data["portfolios"]["main"]["bets"] = [
        {"sport": "NCAAF", "market_type": "h2h", "stake": 10, "payout": 10, "result": "win"},
        {"sport": "NCAAF", "market_type": "h2h", "stake": 10, "payout": 0, "result": "push"},
    ]
    repository.data["portfolios"]["main"]["bankroll"] = 210.0
    stats = portfolio_service.get_stats("main")
    assert stats["overall"]["hit_rate"] == 0.5
    assert stats["overall"]["roi"] == 0.5
    assert stats["by_bucket"][0]["pushes"] == 1
