from dataclasses import dataclass

from app.persistence.market_base import MarketDataRepository, PersistedMarketSnapshot
from app.providers.base import MarketDataProvider, MarketDataProviderError, ProviderFetchResult


@dataclass(frozen=True, slots=True)
class MarketIngestionResult:
    fetch: ProviderFetchResult
    persisted: PersistedMarketSnapshot | None


class MarketIngestionService:
    """Provider-neutral callable ingestion orchestration, independent of FastAPI."""

    def __init__(
        self,
        provider: MarketDataProvider,
        repository: MarketDataRepository | None = None,
    ) -> None:
        self._provider = provider
        self._repository = repository

    @property
    def provider_configured(self) -> bool:
        return self._provider.configured

    def ingest(self, sport: str, markets: list[str]) -> MarketIngestionResult:
        try:
            fetch = self._provider.fetch_current_odds(sport, markets)
        except MarketDataProviderError as exc:
            if self._repository is not None and exc.context is not None:
                self._repository.persist_failure(
                    provider_name=exc.context.provider_name,
                    provider_sport_key=exc.context.provider_sport_key,
                    canonical_league=exc.context.canonical_league,
                    request_parameters=exc.context.request_parameters,
                    public_error=exc.public_message,
                )
            raise
        persisted = self._repository.persist_fetch(fetch) if self._repository is not None else None
        return MarketIngestionResult(fetch=fetch, persisted=persisted)
