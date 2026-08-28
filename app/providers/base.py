from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MarketOffer:
    book: str | None
    market_type: str | None
    selection: str | None
    odds: Any
    point: Any | None = None
    has_point: bool = False


@dataclass(frozen=True, slots=True)
class MarketGame:
    provider_event_id: str | None
    sport: str
    home_team: str | None
    away_team: str | None
    commence_time: str | None
    offers: tuple[MarketOffer, ...]


class MarketDataProviderError(Exception):
    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


class MarketDataProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    def fetch_current_odds(self, sport: str, markets: list[str]) -> list[MarketGame]: ...
