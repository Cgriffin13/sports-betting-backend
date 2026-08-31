from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

import requests

from app.time import utc_now

HISTORICAL_ODDS_URL = (
    "https://api.the-odds-api.com/v4/historical/sports/americanfootball_ncaaf/odds"
)
USAGE_URL = "https://api.the-odds-api.com/v4/sports"
SAFE_USAGE_HEADERS = ("x-requests-remaining", "x-requests-used", "x-requests-last")


class HistoricalOddsProviderError(RuntimeError):
    """Sanitized historical-provider failure."""


@dataclass(frozen=True, slots=True)
class HistoricalOddsResponse:
    requested_at: datetime
    retrieved_at: datetime
    payload_bytes: bytes
    payload: dict[str, Any]
    usage: dict[str, int | str]

    @property
    def returned_snapshot_at(self) -> datetime | None:
        return parse_iso_timestamp(self.payload.get("timestamp"))


class HistoricalOddsClient:
    """Small audit-only adapter; credentials never enter returned metadata."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("ODDS_API_KEY is required")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def usage(self) -> dict[str, int | str]:
        response = self._get(USAGE_URL, {"all": "true"})
        return safe_usage_headers(response.headers)

    def fetch(self, requested_at: datetime) -> HistoricalOddsResponse:
        if requested_at.tzinfo is None:
            raise ValueError("historical request timestamp must be timezone-aware")
        requested_at = requested_at.astimezone(UTC)
        response = self._get(
            HISTORICAL_ODDS_URL,
            {
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
                "dateFormat": "iso",
                "date": iso_z(requested_at),
            },
        )
        try:
            payload = json.loads(response.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise HistoricalOddsProviderError("Historical odds provider returned malformed JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise HistoricalOddsProviderError("Historical odds provider returned an unsupported response")
        return HistoricalOddsResponse(
            requested_at=requested_at,
            retrieved_at=utc_now(),
            payload_bytes=response.content,
            payload=payload,
            usage=safe_usage_headers(response.headers),
        )

    def _get(self, url: str, parameters: dict[str, str]) -> Any:
        transport_parameters = {**parameters, "apiKey": self._api_key}
        try:
            response = self._session.get(url, params=transport_parameters, timeout=self._timeout_seconds)
        except requests.RequestException as exc:
            raise HistoricalOddsProviderError("Historical odds provider request failed") from exc
        if response.status_code != 200:
            raise HistoricalOddsProviderError(f"Historical odds provider returned HTTP {response.status_code}")
        return response


def safe_usage_headers(headers: Mapping[str, str]) -> dict[str, int | str]:
    lowered = {key.lower(): value for key, value in headers.items()}
    result: dict[str, int | str] = {}
    for name in SAFE_USAGE_HEADERS:
        if name not in lowered:
            continue
        value = lowered[name]
        try:
            result[name.removeprefix("x-").replace("-", "_")] = int(value)
        except ValueError:
            result[name.removeprefix("x-").replace("-", "_")] = value
    return result


def parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
