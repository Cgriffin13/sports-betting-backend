from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.domain.pricing import PricingObservation


@dataclass(frozen=True, slots=True)
class PricingObservationQuery:
    leagues: tuple[str, ...]
    market_types: tuple[str, ...]
    as_of: datetime
    event_date: date | None = None


class PricingObservationRepository(Protocol):
    def list_for_pricing(self, query: PricingObservationQuery) -> tuple[PricingObservation, ...]: ...


class EmptyPricingObservationRepository:
    """Compatibility fallback for applications assembled without a database read repository."""

    def list_for_pricing(self, query: PricingObservationQuery) -> tuple[PricingObservation, ...]:
        del query
        return ()
