from typing import Any

from fastapi.testclient import TestClient


def bet_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "portfolio_id": "main",
        "date": "2026-08-29",
        "sport": "NCAAF",
        "league": "NCAAF",
        "market_type": "spreads",
        "selection": "Example State -3.5",
        "book": "DraftKings",
        "odds": -110,
        "stake": 10.0,
        "model_prob": 0.55,
        "book_prob": 0.524,
        "edge": 0.026,
        "ev_per_1": 0.05,
    }
    payload.update(overrides)
    return payload


def place_bet(client: TestClient, **overrides: Any) -> str:
    response = client.post("/bets", json=bet_payload(**overrides))
    assert response.status_code == 200, response.text
    return response.json()["bet_id"]


def settle_bet(client: TestClient, bet_id: str, result: str, payout: Any) -> dict[str, Any]:
    response = client.post(
        "/bet-result",
        json={"portfolio_id": "main", "bet_id": bet_id, "result": result, "payout": payout},
    )
    assert response.status_code == 200, response.text
    return response.json()
