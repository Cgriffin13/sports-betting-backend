from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main
from app.providers.base import MarketGame, MarketOffer
from tests.conftest import FakeProvider
from tests.helpers import bet_payload, place_bet, settle_bet


def test_root_main_exposes_fastapi_application() -> None:
    assert isinstance(main.app, FastAPI)


def test_health_and_generated_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    body = response.json()
    assert body["ok"] is True
    assert body["has_odds_key"] is False
    assert body["data_dir"]
    assert body["time_utc"].endswith("+00:00")


def test_valid_incoming_request_id_is_honored(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-request_123"})
    assert response.headers["X-Request-ID"] == "client-request_123"


@pytest.mark.parametrize("request_id", ["", "has spaces", "x" * 129, "unsafe/value"])
def test_invalid_incoming_request_id_is_replaced(client: TestClient, request_id: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] != request_id


def test_odds_endpoint_preserves_utc_filtering_contract(app_client: Any) -> None:
    provider = FakeProvider(
        [
            MarketGame(
                "utc-date",
                "NCAAF",
                "Home State",
                "Away State",
                "2026-08-28T18:30:00-07:00",
                (MarketOffer("DraftKings", "h2h", "Home State", -120),),
            )
        ],
        configured=True,
    )
    response = app_client(provider).post(
        "/odds",
        json={"date": "2026-08-29", "sports": ["CFB"], "markets": ["h2h"]},
    )
    assert response.status_code == 200
    assert response.json()["date_timezone"] == "UTC"
    assert response.json()["games"][0]["game_id"] == "utc-date"


def test_bet_placement(client: TestClient) -> None:
    response = client.post("/bets", json=bet_payload())
    assert response.status_code == 200
    assert response.json()["bankroll_after"] == pytest.approx(190.0)
    portfolio = client.get("/portfolio/main").json()
    assert portfolio["bankroll"] == pytest.approx(190.0)
    assert portfolio["bets"][0]["result"] is None


def test_insufficient_bankroll(client: TestClient) -> None:
    response = client.post("/bets", json=bet_payload(stake=201.0))
    assert response.status_code == 400
    assert response.json()["detail"] == "Insufficient bankroll for this stake"
    assert client.get("/portfolio/main").json()["bankroll"] == pytest.approx(200.0)


@pytest.mark.parametrize(
    ("result", "payout", "expected"),
    [("win", 9.09, 209.09), ("loss", -10.0, 190.0), ("push", 0.0, 200.0)],
)
def test_settlement(client: TestClient, result: str, payout: float, expected: float) -> None:
    bet_id = place_bet(client)
    response = settle_bet(client, bet_id, result, payout)
    assert response["bankroll_after"] == pytest.approx(expected)


def test_prevent_double_settlement(client: TestClient) -> None:
    bet_id = place_bet(client)
    settle_bet(client, bet_id, "win", 9.09)
    response = client.post(
        "/bet-result",
        json={"portfolio_id": "main", "bet_id": bet_id, "result": "win", "payout": 9.09},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Bet already settled"


def test_invalid_loss_payout_does_not_settle_bet(client: TestClient) -> None:
    bet_id = place_bet(client)
    invalid = client.post(
        "/bet-result",
        json={"portfolio_id": "main", "bet_id": bet_id, "result": "loss", "payout": -5.0},
    )
    valid = client.post(
        "/bet-result",
        json={"portfolio_id": "main", "bet_id": bet_id, "result": "loss", "payout": -10.0},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Loss payout must equal the negative stake"
    assert valid.status_code == 200


def test_portfolio_stats(client: TestClient) -> None:
    settle_bet(client, place_bet(client, sport="NCAAF", market_type="spreads"), "win", 9.09)
    settle_bet(client, place_bet(client, sport="NCAAF", market_type="spreads"), "loss", -10.0)
    settle_bet(client, place_bet(client, sport="NFL", league="NFL", market_type="h2h"), "push", 0.0)
    response = client.get("/portfolio/main/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["current_bankroll"] == pytest.approx(199.09)
    assert body["overall"] == pytest.approx(
        {
            "bets_settled": 3,
            "wins": 1,
            "losses": 1,
            "pushes": 1,
            "hit_rate": 1 / 3,
            "total_staked": 30.0,
            "total_profit": -0.91,
            "roi": -0.91 / 30.0,
        }
    )
    assert {(bucket["sport"], bucket["market_type"]) for bucket in body["by_bucket"]} == {
        ("NCAAF", "spreads"),
        ("NFL", "h2h"),
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stake", 0),
        ("stake", -1),
        ("stake", "NaN"),
        ("stake", "Infinity"),
        ("odds", 0),
        ("odds", 99),
        ("odds", -99),
        ("model_prob", -0.01),
        ("model_prob", 1.01),
        ("model_prob", "NaN"),
        ("book_prob", "Infinity"),
        ("edge", 1.01),
        ("ev_per_1", "NaN"),
    ],
)
def test_invalid_bet_numeric_inputs(client: TestClient, field: str, value: Any) -> None:
    assert client.post("/bets", json=bet_payload(**{field: value})).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"result": "win", "payout": 0},
        {"result": "loss", "payout": 0},
        {"result": "push", "payout": 1},
        {"result": "win", "payout": "NaN"},
        {"result": "win", "payout": 1, "closing_odds": 0},
        {"result": "win", "payout": 1, "closing_book_prob": 1.01},
    ],
)
def test_invalid_settlement_numeric_inputs(client: TestClient, payload: dict[str, Any]) -> None:
    response = client.post("/bet-result", json={"portfolio_id": "main", "bet_id": "missing", **payload})
    assert response.status_code == 422
