from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import requests

from app.domain.markets import ALLOWED_MARKETS
from app.providers.base import MarketDataProviderError, MarketGame, MarketOffer

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://api.the-odds-api.com/v4/sports"
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
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


Requester = Callable[..., ProviderResponse]


class TheOddsApiProvider:
    """The Odds API adapter; credentials and transport details stop at this boundary."""

    def __init__(
        self,
        api_key: str | None,
        *,
        timeout_seconds: float = 12.0,
        requester: Requester = requests.get,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._requester = requester

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def fetch_current_odds(self, sport: str, markets: list[str]) -> list[MarketGame]:
        if not self._api_key:
            raise MarketDataProviderError("Missing ODDS_API_KEY in server environment.")

        provider_key = SPORT_PROVIDER_KEYS[sport]
        url = f"{BASE_URL}/{provider_key}/odds"
        params = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": ",".join(markets),
            "oddsFormat": "american",
        }

        try:
            response = self._requester(url, params=params, timeout=self._timeout_seconds)
            response.raise_for_status()
        except Exception:
            LOGGER.warning("market_provider_request_failed", extra={"provider": "the_odds_api", "sport": sport})
            raise MarketDataProviderError("Provider request failed") from None

        try:
            payload = response.json()
        except Exception:
            LOGGER.warning("market_provider_invalid_response", extra={"provider": "the_odds_api", "sport": sport})
            raise MarketDataProviderError("Provider returned an invalid response") from None

        if not isinstance(payload, list):
            raise MarketDataProviderError("Provider returned an invalid response")
        return self._parse_games(payload, sport)

    @staticmethod
    def _parse_games(payload: list[Any], sport: str) -> list[MarketGame]:
        games: list[MarketGame] = []
        for raw_game in payload:
            if not isinstance(raw_game, dict):
                continue
            offers: list[MarketOffer] = []
            bookmakers = raw_game.get("bookmakers", [])
            if not isinstance(bookmakers, list):
                bookmakers = []
            for bookmaker in bookmakers:
                if not isinstance(bookmaker, dict):
                    continue
                book_name = bookmaker.get("title")
                raw_markets = bookmaker.get("markets", [])
                if not isinstance(raw_markets, list):
                    continue
                for market in raw_markets:
                    if not isinstance(market, dict):
                        continue
                    market_type = market.get("key")
                    if market_type not in ALLOWED_MARKETS:
                        continue
                    outcomes = market.get("outcomes", [])
                    if not isinstance(outcomes, list):
                        continue
                    for outcome in outcomes:
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
                            )
                        )
            games.append(
                MarketGame(
                    provider_event_id=raw_game.get("id"),
                    sport=sport,
                    home_team=raw_game.get("home_team"),
                    away_team=raw_game.get("away_team"),
                    commence_time=raw_game.get("commence_time"),
                    offers=tuple(offers),
                )
            )
        return games
