from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

import requests

from app.domain.ncaaf import canonical_request_parameters, content_hash
from app.time import utc_now

CFBD_BASE_URL = "https://api.collegefootballdata.com"
SAFE_HEADER_NAMES = {
    "content-length",
    "content-type",
    "date",
    "etag",
    "last-modified",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-requests-remaining",
}


class CfbdProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CfbdResponse:
    endpoint: str
    parameters: dict[str, Any]
    retrieved_at: datetime
    payload_bytes: bytes
    records: list[dict[str, Any]] | dict[str, Any]
    headers: dict[str, str]
    status_code: int

    @property
    def content_hash(self) -> str:
        return content_hash(self.payload_bytes)

    @property
    def row_count(self) -> int:
        return len(self.records) if isinstance(self.records, list) else 1


class CfbdDataClient(Protocol):
    def get(self, endpoint: str, parameters: Mapping[str, Any] | None = None) -> CfbdResponse: ...


class CfbdClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("CFBD_API_KEY is required")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._session = session or requests.Session()

    def get(self, endpoint: str, parameters: Mapping[str, Any] | None = None) -> CfbdResponse:
        clean = canonical_request_parameters(parameters or {})
        try:
            response = self._session.get(
                f"{CFBD_BASE_URL}/{endpoint.strip('/')}",
                params=clean,
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as exc:
            raise CfbdProviderError("CFBD request failed") from exc
        if response.status_code != 200:
            raise CfbdProviderError(f"CFBD returned HTTP {response.status_code}")
        try:
            parsed = json.loads(response.content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise CfbdProviderError("CFBD returned malformed JSON") from exc
        if not isinstance(parsed, (list, dict)):
            raise CfbdProviderError("CFBD returned an unsupported response shape")
        safe_headers = {
            name.lower(): value
            for name, value in response.headers.items()
            if name.lower() in SAFE_HEADER_NAMES
        }
        return CfbdResponse(
            endpoint=endpoint.strip("/"),
            parameters=clean,
            retrieved_at=utc_now(),
            payload_bytes=response.content,
            records=parsed,
            headers=safe_headers,
            status_code=response.status_code,
        )
