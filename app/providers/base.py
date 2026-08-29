from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class MarketOffer:
    book: str | None
    market_type: str | None
    selection: str | None
    odds: Any
    point: Any | None = None
    has_point: bool = False
    book_key: str | None = None
    provider_updated_at: datetime | None = None
    raw_source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MarketGame:
    provider_event_id: str | None
    sport: str
    home_team: str | None
    away_team: str | None
    commence_time: str | None
    offers: tuple[MarketOffer, ...]
    status: str | None = None
    provider_updated_at: datetime | None = None
    raw_source: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderFetchResult:
    provider_name: str
    provider_sport_key: str
    canonical_league: str
    requested_at: datetime
    provider_retrieved_at: datetime | None
    request_parameters: dict[str, Any]
    raw_payload: list[Any]
    response_metadata: dict[str, Any]
    warnings: tuple[dict[str, Any], ...]
    games: tuple[MarketGame, ...]
    from_cache: bool = False


@dataclass(frozen=True, slots=True)
class ProviderRequestContext:
    provider_name: str
    provider_sport_key: str
    canonical_league: str
    request_parameters: dict[str, object]


class MarketDataProviderError(Exception):
    def __init__(self, public_message: str, *, context: ProviderRequestContext | None = None) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.context = context


class MarketDataProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    def fetch_current_odds(self, sport: str, markets: list[str]) -> ProviderFetchResult: ...
