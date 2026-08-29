from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.providers.base import ProviderFetchResult


@dataclass(frozen=True, slots=True)
class PersistedMarketSnapshot:
    snapshot_id: UUID
    events_created: int
    observations_created: int
    warnings: tuple[dict[str, object], ...]


class MarketDataRepository(Protocol):
    def persist_fetch(self, fetch: ProviderFetchResult) -> PersistedMarketSnapshot: ...

    def persist_failure(
        self,
        *,
        provider_name: str,
        provider_sport_key: str,
        canonical_league: str,
        request_parameters: dict[str, object],
        public_error: str,
    ) -> UUID: ...
