from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import requests

from app.domain.markets import ALLOWED_MARKETS
from app.providers.base import (
    MarketDataProviderError,
    MarketGame,
    MarketOffer,
    ProviderFetchResult,
    ProviderRequestContext,
)
from app.time import utc_now

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.the-odds-api.com/v4/sports"
PROVIDER_NAME = "the_odds_api"
SPORT_PROVIDER_KEYS = {
    "NCAAF": "americanfootball_ncaaf",
    "NFL": "americanfootball_nfl",
    "NCAAB": "basketball_ncaab",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
}


class ProviderResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class TheOddsApiProvider:
    """The Odds API adapter with bounded retries, cache, quota metadata, and sanitized failures."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout_seconds: float = 12.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        cache_ttl_seconds: float = 15.0,
        low_quota_threshold: int = 10,
        requester: Callable[..., Any] = requests.get,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._low_quota_threshold = low_quota_threshold
        self._requester = requester
        self._sleeper = sleeper
        self._clock = clock
        self._cache: dict[tuple[str, tuple[str, ...]], tuple[datetime, ProviderFetchResult]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def fetch_current_odds(self, sport: str, markets: list[str]) -> ProviderFetchResult:
        provider_key = SPORT_PROVIDER_KEYS[sport]
        safe_params: dict[str, object] = {
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }
        context = ProviderRequestContext(PROVIDER_NAME, provider_key, sport, safe_params)
        if not self._api_key:
            raise MarketDataProviderError("Missing ODDS_API_KEY in server environment.", context=context)

        normalized_markets = tuple(markets)
        cache_key = (sport, normalized_markets)
        requested_at = self._clock()
        cached = self._cache.get(cache_key)
        if cached and (requested_at - cached[0]).total_seconds() <= self._cache_ttl_seconds:
            metadata = {**cached[1].response_metadata, "cache": "hit"}
            return replace(cached[1], requested_at=requested_at, response_metadata=metadata, from_cache=True)

        url = f"{BASE_URL}/{provider_key}/odds"
        transport_params = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }
        response = self._request_with_retry(url, transport_params, sport, context)

        try:
            payload = response.json()
        except Exception:
            LOGGER.warning("market_provider_invalid_response", extra={"provider": PROVIDER_NAME, "sport": sport})
            raise MarketDataProviderError("Provider returned an invalid response", context=context) from None
        if not isinstance(payload, list):
            raise MarketDataProviderError("Provider returned an invalid response", context=context)

        response_metadata, quota_warnings = self._response_metadata(response.headers)
        games, parse_warnings = self._parse_games(payload, sport)
        result = ProviderFetchResult(
            provider_name=PROVIDER_NAME,
            provider_sport_key=provider_key,
            canonical_league=sport,
            requested_at=requested_at,
            provider_retrieved_at=self._provider_timestamp(response.headers),
            request_parameters=dict(safe_params),
            raw_payload=payload,
            response_metadata={**response_metadata, "cache": "miss"},
            warnings=tuple([*quota_warnings, *parse_warnings]),
            games=tuple(games),
        )
        self._cache[cache_key] = (requested_at, result)
        return result

    def _request_with_retry(
        self,
        url: str,
        params: dict[str, Any],
        sport: str,
        context: ProviderRequestContext,
    ) -> ProviderResponse:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._requester(url, params=params, timeout=self._timeout_seconds)
                status_code = getattr(response, "status_code", 200)
                if status_code in {408, 425, 429} or status_code >= 500:
                    if attempt < self._max_retries:
                        self._backoff(attempt)
                        continue
                response.raise_for_status()
                return response
            except (requests.Timeout, requests.ConnectionError):
                if attempt < self._max_retries:
                    self._backoff(attempt)
                    continue
                break
            except Exception:
                break
        LOGGER.warning("market_provider_request_failed", extra={"provider": PROVIDER_NAME, "sport": sport})
        raise MarketDataProviderError("Provider request failed", context=context) from None

    def _backoff(self, attempt: int) -> None:
        self._sleeper(self._backoff_seconds * (2**attempt))

    def _response_metadata(self, headers: Mapping[str, str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        lowered = {key.lower(): value for key, value in headers.items()}
        metadata: dict[str, Any] = {}
        warnings: list[dict[str, Any]] = []
        header_mapping = {
            "x-requests-remaining": "requests_remaining",
            "x-requests-used": "requests_used",
            "x-requests-last": "requests_last",
        }
        for header, field_name in header_mapping.items():
            if header in lowered:
                metadata[field_name] = self._integer_or_string(lowered[header])
        remaining = metadata.get("requests_remaining")
        if isinstance(remaining, int) and remaining <= self._low_quota_threshold:
            warnings.append(
                {
                    "code": "provider_quota_low",
                    "requests_remaining": remaining,
                    "threshold": self._low_quota_threshold,
                }
            )
        return metadata, warnings

    @staticmethod
    def _integer_or_string(value: str) -> int | str:
        try:
            return int(value)
        except ValueError:
            return value

    @staticmethod
    def _provider_timestamp(headers: Mapping[str, str]) -> datetime | None:
        raw_date = next((value for key, value in headers.items() if key.lower() == "date"), None)
        if raw_date is None:
            return None
        try:
            parsed = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @classmethod
    def _parse_games(cls, payload: list[Any], sport: str) -> tuple[list[MarketGame], list[dict[str, Any]]]:
        games: list[MarketGame] = []
        warnings: list[dict[str, Any]] = []
        for game_index, raw_game in enumerate(payload):
            if not isinstance(raw_game, dict):
                warnings.append({"code": "malformed_event", "event_index": game_index})
                continue
            offers: list[MarketOffer] = []
            bookmakers = raw_game.get("bookmakers", [])
            if not isinstance(bookmakers, list):
                warnings.append({"code": "malformed_bookmakers", "event_index": game_index})
                bookmakers = []
            for book_index, bookmaker in enumerate(bookmakers):
                if not isinstance(bookmaker, dict):
                    warnings.append(
                        {"code": "malformed_bookmaker", "event_index": game_index, "book_index": book_index}
                    )
                    continue
                book_name = bookmaker.get("title")
                book_key = bookmaker.get("key")
                book_updated_at = cls._parse_timestamp(bookmaker.get("last_update"))
                raw_markets = bookmaker.get("markets", [])
                if not isinstance(raw_markets, list):
                    continue
                for market_index, market in enumerate(raw_markets):
                    if not isinstance(market, dict):
                        continue
                    market_type = market.get("key")
                    if market_type not in ALLOWED_MARKETS:
                        continue
                    market_updated_at = cls._parse_timestamp(market.get("last_update")) or book_updated_at
                    outcomes = market.get("outcomes", [])
                    if not isinstance(outcomes, list):
                        continue
                    for outcome_index, outcome in enumerate(outcomes):
                        if not isinstance(outcome, dict):
                            continue
                        offers.append(
                            MarketOffer(
                                book=book_name if isinstance(book_name, str) else None,
                                market_type=market_type,
                                selection=outcome.get("name"),
                                odds=outcome.get("price"),
                                point=outcome.get("point"),
                                has_point="point" in outcome,
                                book_key=book_key if isinstance(book_key, str) else None,
                                provider_updated_at=market_updated_at,
                                raw_source={
                                    "event_index": game_index,
                                    "book_index": book_index,
                                    "market_index": market_index,
                                    "outcome_index": outcome_index,
                                },
                            )
                        )
            games.append(
                MarketGame(
                    provider_event_id=raw_game.get("id") if isinstance(raw_game.get("id"), str) else None,
                    sport=sport,
                    home_team=raw_game.get("home_team") if isinstance(raw_game.get("home_team"), str) else None,
                    away_team=raw_game.get("away_team") if isinstance(raw_game.get("away_team"), str) else None,
                    commence_time=(
                        raw_game.get("commence_time") if isinstance(raw_game.get("commence_time"), str) else None
                    ),
                    offers=tuple(offers),
                    status=raw_game.get("status") if isinstance(raw_game.get("status"), str) else None,
                    provider_updated_at=cls._parse_timestamp(raw_game.get("last_update")),
                    raw_source={"event_index": game_index},
                )
            )
        return games, warnings

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
