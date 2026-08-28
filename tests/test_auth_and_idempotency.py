from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Bet, BetApproval, BetStateTransition, IdempotencyRecord, LedgerEntry, Settlement
from tests.helpers import bet_payload


def test_mutating_and_private_read_endpoints_require_authentication(raw_client: TestClient) -> None:
    requests: list[tuple[str, str, dict[str, Any] | None]] = [
        ("post", "/odds", {"date": "2026-08-29", "sports": ["NCAAF"], "markets": ["h2h"]}),
        ("get", "/portfolio/main", None),
        ("post", "/bets", bet_payload()),
        (
            "post",
            "/bet-result",
            {"portfolio_id": "main", "bet_id": "missing", "result": "push", "payout": 0},
        ),
        ("get", "/portfolio/main/stats", None),
    ]

    for method, path, body in requests:
        response = raw_client.request(method, path, json=body)
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}


def test_health_remains_public(raw_client: TestClient) -> None:
    assert raw_client.get("/health").status_code == 200


def test_cross_owner_portfolio_access_is_rejected(client: TestClient) -> None:
    assert client.get("/portfolio/main").status_code == 200

    secondary_headers = {"X-API-Key": "test-secondary-key"}
    assert client.get("/portfolio/main", headers=secondary_headers).status_code == 403
    assert client.post("/bets", headers=secondary_headers, json=bet_payload()).status_code == 403
    assert client.get("/portfolio/main/stats", headers=secondary_headers).status_code == 403


def test_idempotent_bet_placement_returns_original_response_and_mutates_once(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    headers = {"Idempotency-Key": "place-main-001"}
    first = client.post("/bets", headers=headers, json=bet_payload())
    second = client.post("/bets", headers=headers, json=bet_payload())

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.get("/portfolio/main").json()["cash"] == 190.0
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Bet)) == 1
        assert session.scalar(select(func.count()).select_from(BetApproval)) == 1
        assert session.scalar(select(func.count()).select_from(BetStateTransition)) == 1
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 2
        assert session.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


def test_idempotency_key_reuse_with_different_payload_is_conflict(client: TestClient) -> None:
    headers = {"Idempotency-Key": "place-main-conflict"}
    assert client.post("/bets", headers=headers, json=bet_payload()).status_code == 200
    conflict = client.post("/bets", headers=headers, json=bet_payload(stake=11))

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Idempotency key was already used with a different request"
    assert client.get("/portfolio/main").json()["cash"] == 190.0


def test_missing_idempotency_key_allows_distinct_mutations(client: TestClient) -> None:
    first = client.post("/bets", json=bet_payload())
    second = client.post("/bets", json=bet_payload())

    assert first.status_code == second.status_code == 200
    assert first.json()["bet_id"] != second.json()["bet_id"]
    assert client.get("/portfolio/main").json()["cash"] == 180.0


def test_idempotent_settlement_mutates_once(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    bet_id = client.post("/bets", json=bet_payload()).json()["bet_id"]
    payload = {"portfolio_id": "main", "bet_id": bet_id, "result": "win", "payout": 9.09}
    headers = {"Idempotency-Key": "settle-main-001"}
    first = client.post("/bet-result", headers=headers, json=payload)
    second = client.post("/bet-result", headers=headers, json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {"message": "Bet result recorded", "bankroll_after": 209.09}
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Settlement)) == 1
        assert session.scalar(select(func.count()).select_from(BetStateTransition)) == 2
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 3


def test_settlement_idempotency_key_reuse_with_different_payload_is_conflict(client: TestClient) -> None:
    bet_id = client.post("/bets", json=bet_payload()).json()["bet_id"]
    headers = {"Idempotency-Key": "settle-main-conflict"}
    first_payload = {"portfolio_id": "main", "bet_id": bet_id, "result": "win", "payout": 9.09}
    second_payload = {**first_payload, "payout": 10.00}

    assert client.post("/bet-result", headers=headers, json=first_payload).status_code == 200
    assert client.post("/bet-result", headers=headers, json=second_payload).status_code == 409
