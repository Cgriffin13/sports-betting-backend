from datetime import date
from typing import Any, Final

from app.domain.markets import normalize_markets
from app.domain.sports import DEFAULT_SPORTS, SUPPORTED_SPORTS, normalize_sport
from app.providers.base import MarketDataProvider, MarketDataProviderError, MarketGame
from app.time import commence_date_utc

DEFAULT_ALLOWED_BOOKS: Final = frozenset({"DraftKings", "FanDuel", "BetMGM"})


class OddsService:
    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider

    @property
    def provider_configured(self) -> bool:
        return self._provider.configured

    def get_odds(
        self,
        *,
        requested_date: date,
        sports: list[str] | None,
        markets: list[str] | None,
        allowed_books: list[str] | None,
        max_games_per_sport: int,
    ) -> dict[str, Any]:
        if not self._provider.configured:
            return {
                "error": "Missing ODDS_API_KEY in server environment.",
                "date": str(requested_date),
                "date_timezone": "UTC",
                "games": [],
            }

        sports_to_query = [normalize_sport(sport) for sport in (sports or list(DEFAULT_SPORTS))]
        normalized_markets = normalize_markets(markets)
        selected_books = set(allowed_books) if allowed_books else set(DEFAULT_ALLOWED_BOOKS)
        all_games: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for sport in sports_to_query:
            if sport not in SUPPORTED_SPORTS:
                errors.append({"sport": sport, "error": f"Unsupported sport '{sport}'"})
                continue
            try:
                games = self._provider.fetch_current_odds(sport, normalized_markets)
            except MarketDataProviderError as exc:
                errors.append({"sport": sport, "error": exc.public_message})
                continue
            matching_games = [
                game for game in games if commence_date_utc(game.commence_time) == requested_date
            ][:max_games_per_sport]
            all_games.extend(self._serialize_games(matching_games, selected_books))

        return {
            "date": str(requested_date),
            "date_timezone": "UTC",
            "sports": sports_to_query,
            "markets": normalized_markets,
            "allowed_books": sorted(selected_books),
            "games": all_games,
            "errors": errors,
        }

    @staticmethod
    def _serialize_games(games: list[MarketGame], selected_books: set[str]) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for game in games:
            offers: list[dict[str, Any]] = []
            for offer in game.offers:
                if offer.book not in selected_books:
                    continue
                output = {
                    "book": offer.book,
                    "market_type": offer.market_type,
                    "selection": offer.selection,
                    "odds": offer.odds,
                }
                if offer.has_point:
                    output["point"] = offer.point
                offers.append(output)
            if not offers:
                continue
            serialized.append(
                {
                    "game_id": game.provider_event_id,
                    "sport": game.sport,
                    "league": game.sport,
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "commence_time": game.commence_time,
                    "offers": offers,
                }
            )
        return serialized
