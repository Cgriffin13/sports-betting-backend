from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient

import main


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


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["has_odds_key"] is False
    assert body["data_dir"]
    assert body["time_utc"].endswith("+00:00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NCAAF", "NCAAF"),
        ("cfb", "NCAAF"),
        ("college_football", "NCAAF"),
        ("College Football", "NCAAF"),
        ("ncaab", "NCAAB"),
        ("college_basketball", "NCAAB"),
        ("nba", "NBA"),
        ("college", "COLLEGE"),
    ],
)
def test_sport_normalization(raw: str, expected: str) -> None:
    assert main.normalize_sport(raw) == expected


def test_ncaaf_provider_mapping_is_distinct_from_ncaab() -> None:
    assert main.SPORT_KEYS["NCAAF"] == "americanfootball_ncaaf"
    assert main.SPORT_KEYS["NCAAB"] == "basketball_ncaab"
    assert main.SPORT_KEYS["NCAAF"] != main.SPORT_KEYS["NCAAB"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ["h2h", "spreads", "totals"]),
        (["ML", "spread", "OU"], ["h2h", "spreads", "totals"]),
        (["h2h", "player_props"], ["h2h"]),
        (["player_props"], ["h2h", "spreads", "totals"]),
    ],
)
def test_market_normalization(raw: list[str] | None, expected: list[str]) -> None:
    assert main.normalize_markets(raw) == expected


def test_odds_filtering_date_semantics_and_ncaaf_provider_mapping(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": "utc-date",
                    "home_team": "Home State",
                    "away_team": "Away State",
                    "commence_time": "2026-08-28T18:30:00-07:00",
                    "bookmakers": [
                        {
                            "title": "DraftKings",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Home State", "price": -120},
                                        {"name": "Away State", "price": 105},
                                    ],
                                },
                                {
                                    "key": "spreads",
                                    "outcomes": [{"name": "Home State", "price": -110, "point": -3.5}],
                                },
                                {"key": "player_props", "outcomes": [{"name": "Player", "price": -110}]},
                            ],
                        },
                        {
                            "title": "Caesars",
                            "markets": [{"key": "h2h", "outcomes": [{"name": "Home State", "price": -115}]}],
                        },
                    ],
                },
                {
                    "id": "next-date",
                    "home_team": "Later Home",
                    "away_team": "Later Away",
                    "commence_time": "2026-08-30T01:00:00Z",
                    "bookmakers": [],
                },
                {
                    "id": "naive-time",
                    "home_team": "Unknown Home",
                    "away_team": "Unknown Away",
                    "commence_time": "2026-08-29T12:00:00",
                    "bookmakers": [],
                },
            ]

    def fake_get(url: str, params: dict[str, Any], timeout: int) -> FakeResponse:
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(main, "ODDS_API_KEY", "test-placeholder-key")
    monkeypatch.setattr(main.requests, "get", fake_get)

    response = client.post(
        "/odds",
        json={"date": "2026-08-29", "sports": ["CFB"], "markets": ["h2h", "spreads", "player_props"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-08-29"
    assert body["date_timezone"] == "UTC"
    assert body["sports"] == ["NCAAF"]
    assert [game["game_id"] for game in body["games"]] == ["utc-date"]
    assert {offer["book"] for offer in body["games"][0]["offers"]} == {"DraftKings"}
    assert {offer["market_type"] for offer in body["games"][0]["offers"]} == {"h2h", "spreads"}
    assert any(offer.get("point") == -3.5 for offer in body["games"][0]["offers"])
    assert captured["url"].endswith("/americanfootball_ncaaf/odds")
    assert captured["params"]["markets"] == "h2h,spreads"
    assert captured["timeout"] == 12


def test_provider_errors_are_sanitized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "should-never-escape"

    def failing_get(url: str, params: dict[str, Any], timeout: int) -> None:
        raise requests.HTTPError(f"failed URL {url}?apiKey={secret}")

    monkeypatch.setattr(main, "ODDS_API_KEY", secret)
    monkeypatch.setattr(main.requests, "get", failing_get)

    response = client.post("/odds", json={"date": "2026-08-29", "sports": ["NCAAF"]})

    assert response.status_code == 200
    assert response.json()["errors"] == [{"sport": "NCAAF", "error": "Provider request failed"}]
    assert secret not in response.text
    assert "apiKey" not in response.text


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


def test_win_settlement(client: TestClient) -> None:
    bet_id = place_bet(client)

    result = settle_bet(client, bet_id, "win", 9.09)

    assert result["bankroll_after"] == pytest.approx(209.09)


def test_loss_settlement(client: TestClient) -> None:
    bet_id = place_bet(client)

    result = settle_bet(client, bet_id, "loss", -10.0)

    assert result["bankroll_after"] == pytest.approx(190.0)


def test_push_settlement(client: TestClient) -> None:
    bet_id = place_bet(client)

    result = settle_bet(client, bet_id, "push", 0.0)

    assert result["bankroll_after"] == pytest.approx(200.0)


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
    response = client.post("/bets", json=bet_payload(**{field: value}))

    assert response.status_code == 422


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
    response = client.post(
        "/bet-result",
        json={"portfolio_id": "main", "bet_id": "missing", **payload},
    )

    assert response.status_code == 422
