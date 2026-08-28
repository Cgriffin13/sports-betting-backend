from typing import Any

import pytest

from app.providers.base import MarketDataProviderError
from app.providers.odds_api import TheOddsApiProvider


class FakeResponse:
    def __init__(self, payload: Any, *, response_error: Exception | None = None) -> None:
        self.payload = payload
        self.response_error = response_error

    def raise_for_status(self) -> None:
        if self.response_error:
            raise self.response_error

    def json(self) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_adapter_owns_request_and_parses_provider_neutral_games() -> None:
    captured: dict[str, Any] = {}
    payload = [
        {
            "id": "game-1",
            "home_team": "Home State",
            "away_team": "Away State",
            "commence_time": "2026-08-29T01:30:00Z",
            "bookmakers": [
                {
                    "title": "DraftKings",
                    "markets": [
                        {"key": "h2h", "outcomes": [{"name": "Home State", "price": -120}]},
                        {"key": "spreads", "outcomes": [{"name": "Away State", "price": -110, "point": 3.5}]},
                        {"key": "player_props", "outcomes": [{"name": "Player", "price": -110}]},
                    ],
                }
            ],
        }
    ]

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse(payload)

    provider = TheOddsApiProvider("placeholder-key", requester=requester)
    games = provider.fetch_current_odds("NCAAF", ["h2h", "spreads"])

    assert captured["url"].endswith("/americanfootball_ncaaf/odds")
    assert captured["params"] == {
        "apiKey": "placeholder-key",
        "regions": "us",
        "markets": "h2h,spreads",
        "oddsFormat": "american",
    }
    assert captured["timeout"] == 12.0
    assert games[0].provider_event_id == "game-1"
    assert [(offer.market_type, offer.point, offer.has_point) for offer in games[0].offers] == [
        ("h2h", None, False),
        ("spreads", 3.5, True),
    ]


def test_adapter_sanitizes_transport_failure(caplog: pytest.LogCaptureFixture) -> None:
    secret = "should-never-escape"

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        raise RuntimeError(f"failed {url}?apiKey={secret}")

    provider = TheOddsApiProvider(secret, requester=requester)
    with pytest.raises(MarketDataProviderError, match="Provider request failed") as exc_info:
        provider.fetch_current_odds("NCAAF", ["h2h"])

    assert secret not in exc_info.value.public_message
    assert secret not in caplog.text
    assert "apiKey" not in caplog.text


@pytest.mark.parametrize("payload", [{"unexpected": "shape"}, ValueError("invalid json")])
def test_adapter_rejects_invalid_provider_response(payload: Any) -> None:
    provider = TheOddsApiProvider("placeholder", requester=lambda *args, **kwargs: FakeResponse(payload))
    with pytest.raises(MarketDataProviderError, match="Provider returned an invalid response"):
        provider.fetch_current_odds("NFL", ["h2h"])
