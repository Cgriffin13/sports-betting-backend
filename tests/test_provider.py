from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests

from app.providers.base import MarketDataProviderError
from app.providers.odds_api import TheOddsApiProvider


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        response_error: Exception | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.response_error = response_error
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.response_error:
            raise self.response_error
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

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
    result = provider.fetch_current_odds("NCAAF", ["h2h", "spreads"])
    games = result.games

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
    assert result.provider_sport_key == "americanfootball_ncaaf"
    assert result.raw_payload == payload
    assert "apiKey" not in result.request_parameters


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


def test_adapter_retries_transient_failures_with_bounded_exponential_backoff() -> None:
    responses = [FakeResponse([], status_code=500), FakeResponse([], status_code=429), FakeResponse([])]
    sleeps: list[float] = []

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        return responses.pop(0)

    provider = TheOddsApiProvider(
        "placeholder",
        max_retries=2,
        backoff_seconds=0.5,
        cache_ttl_seconds=0,
        requester=requester,
        sleeper=sleeps.append,
    )
    assert provider.fetch_current_odds("NCAAF", ["h2h"]).games == ()
    assert sleeps == [0.5, 1.0]
    assert responses == []


def test_adapter_does_not_retry_auth_or_other_client_errors() -> None:
    calls = 0

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse([], status_code=401)

    provider = TheOddsApiProvider("placeholder", max_retries=3, requester=requester, sleeper=lambda _: None)
    with pytest.raises(MarketDataProviderError, match="Provider request failed"):
        provider.fetch_current_odds("NCAAF", ["h2h"])
    assert calls == 1


def test_adapter_cache_and_quota_metadata_are_bounded_and_traceable() -> None:
    now = datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    calls = 0

    def clock() -> datetime:
        return now + timedelta(seconds=calls)

    def requester(url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse(
            [],
            headers={
                "Date": "Sat, 29 Aug 2026 20:00:00 GMT",
                "x-requests-remaining": "5",
                "x-requests-used": "95",
            },
        )

    provider = TheOddsApiProvider(
        "placeholder",
        requester=requester,
        clock=clock,
        cache_ttl_seconds=30,
        low_quota_threshold=10,
    )
    first = provider.fetch_current_odds("NCAAF", ["h2h"])
    second = provider.fetch_current_odds("NCAAF", ["h2h"])

    assert calls == 1
    assert first.response_metadata == {"requests_remaining": 5, "requests_used": 95, "cache": "miss"}
    assert first.warnings == (({"code": "provider_quota_low", "requests_remaining": 5, "threshold": 10}),)
    assert first.provider_retrieved_at == datetime(2026, 8, 29, 20, 0, tzinfo=UTC)
    assert second.from_cache is True
    assert second.response_metadata["cache"] == "hit"
