from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.market_models import (
    CanonicalEvent,
    MarketObservation,
    MarketSnapshot,
    ProviderEventMapping,
    ProviderSportsbook,
    Sportsbook,
)
from app.domain.books import normalize_book
from app.domain.market_identity import (
    FRESHNESS_POLICY_VERSION,
    FULL_GAME_PERIOD,
    canonical_market_type,
    exact_point,
    point_identity,
    selection_side,
)
from app.domain.validation import validate_american_odds
from app.persistence.market_base import PersistedMarketSnapshot
from app.providers.base import MarketGame, MarketOffer, ProviderFetchResult
from app.time import utc_now


class SqlAlchemyMarketDataRepository:
    """Persists a raw fetch and every valid normalized row in one transaction."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        freshness_seconds: int,
        provider_quote_max_age_seconds: int = 604_800,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._freshness_seconds = freshness_seconds
        self._provider_quote_max_age_seconds = provider_quote_max_age_seconds
        self._clock = clock
        self._id_factory = id_factory

    def persist_fetch(self, fetch: ProviderFetchResult) -> PersistedMarketSnapshot:
        self._assert_safe_metadata(fetch.request_parameters)
        warnings: list[dict[str, Any]] = [dict(warning) for warning in fetch.warnings]
        events_created = 0
        observations_created = 0
        ingested_at = self._clock()

        with self._session_factory() as session, session.begin():
            snapshot = MarketSnapshot(
                id=self._id_factory(),
                provider_name=fetch.provider_name,
                provider_sport_key=fetch.provider_sport_key,
                canonical_league=fetch.canonical_league,
                requested_at=fetch.requested_at,
                provider_retrieved_at=fetch.provider_retrieved_at,
                request_parameters=fetch.request_parameters,
                raw_payload=fetch.raw_payload,
                response_metadata=fetch.response_metadata,
                ingestion_status="success",
                warning_metadata=list(warnings) or None,
                created_at=ingested_at,
            )
            session.add(snapshot)
            session.flush()
            seen_observations: set[tuple[UUID, UUID, str, str, str, str]] = set()

            for game in fetch.games:
                try:
                    event, created = self._resolve_event(session, fetch, game, ingested_at)
                except ValueError as exc:
                    warnings.append(
                        {
                            "code": "event_not_normalized",
                            "provider_event_id": game.provider_event_id,
                            "reason": str(exc),
                        }
                    )
                    continue
                events_created += int(created)
                for offer in game.offers:
                    try:
                        book, provider_book = self._resolve_book(session, fetch.provider_name, offer, ingested_at)
                        observation = self._build_observation(
                            snapshot,
                            event,
                            book,
                            provider_book,
                            game,
                            offer,
                            ingested_at,
                        )
                    except (TypeError, ValueError) as exc:
                        warnings.append(
                            {
                                "code": "observation_not_normalized",
                                "provider_event_id": game.provider_event_id,
                                "raw_source": offer.raw_source,
                                "reason": str(exc),
                            }
                        )
                        continue
                    identity = (
                        event.id,
                        book.id,
                        observation.market_type,
                        observation.period,
                        observation.selection_side,
                        observation.point_key,
                    )
                    if identity in seen_observations:
                        warnings.append(
                            {
                                "code": "duplicate_observation_skipped",
                                "provider_event_id": game.provider_event_id,
                                "raw_source": offer.raw_source,
                            }
                        )
                        continue
                    seen_observations.add(identity)
                    session.add(observation)
                    observations_created += 1

            snapshot.warning_metadata = list(warnings) or None
            snapshot.ingestion_status = "partial" if warnings else "success"
            session.flush()
            snapshot_id = snapshot.id

        ingestion_completed_at = self._as_utc(self._clock())
        return PersistedMarketSnapshot(
            snapshot_id,
            events_created,
            observations_created,
            tuple(warnings),
            ingestion_completed_at,
        )

    def persist_failure(
        self,
        *,
        provider_name: str,
        provider_sport_key: str,
        canonical_league: str,
        request_parameters: dict[str, object],
        public_error: str,
    ) -> UUID:
        self._assert_safe_metadata(request_parameters)
        with self._session_factory() as session, session.begin():
            snapshot = MarketSnapshot(
                id=self._id_factory(),
                provider_name=provider_name,
                provider_sport_key=provider_sport_key,
                canonical_league=canonical_league,
                requested_at=self._clock(),
                request_parameters=request_parameters,
                raw_payload=None,
                response_metadata=None,
                ingestion_status="failed",
                error_metadata={"public_error": public_error},
                created_at=self._clock(),
            )
            session.add(snapshot)
            session.flush()
            return snapshot.id

    def _resolve_event(
        self,
        session: Session,
        fetch: ProviderFetchResult,
        game: MarketGame,
        now: datetime,
    ) -> tuple[CanonicalEvent, bool]:
        if not game.home_team or not game.away_team:
            raise ValueError("Event requires home and away teams")
        scheduled = self._parse_timestamp(game.commence_time)
        if scheduled is None:
            raise ValueError("Event requires a timezone-aware scheduled start")

        candidates: list[tuple[ProviderEventMapping, CanonicalEvent]] = []
        if game.provider_event_id:
            mappings = session.scalars(
                select(ProviderEventMapping).where(
                    ProviderEventMapping.provider_name == fetch.provider_name,
                    ProviderEventMapping.provider_sport_key == fetch.provider_sport_key,
                    ProviderEventMapping.provider_event_id == game.provider_event_id,
                )
            )
            for mapping in mappings:
                event = session.get(CanonicalEvent, mapping.canonical_event_id)
                if event is not None:
                    candidates.append((mapping, event))
            for mapping, event in candidates:
                if self._same_event(event, fetch.canonical_league, game.home_team, game.away_team, scheduled):
                    event.updated_at = now
                    if game.status:
                        event.event_status = game.status
                    mapping.updated_at = now
                    return event, False

        has_conflict = bool(candidates)
        review_status = "conflict" if has_conflict else ("matched" if game.provider_event_id else "needs_review")
        confidence = Decimal("0.0000") if has_conflict else Decimal("1.0000" if game.provider_event_id else "0.5000")
        event = CanonicalEvent(
            id=self._id_factory(),
            league=fetch.canonical_league,
            home_team=game.home_team.strip(),
            away_team=game.away_team.strip(),
            scheduled_start_utc=scheduled,
            event_status=game.status or "scheduled",
            match_confidence=confidence,
            review_status=review_status,
            match_provenance={
                "method": "provider_event_id" if game.provider_event_id else "unmapped_provider_event",
                "provider": fetch.provider_name,
                "provider_event_id": game.provider_event_id,
                "conflicting_candidate_ids": [str(candidate.id) for _, candidate in candidates],
            },
            created_at=now,
            updated_at=now,
        )
        session.add(event)
        session.flush()

        if game.provider_event_id:
            mapping = ProviderEventMapping(
                id=self._id_factory(),
                provider_name=fetch.provider_name,
                provider_sport_key=fetch.provider_sport_key,
                provider_event_id=game.provider_event_id,
                canonical_event_id=event.id,
                match_confidence=confidence,
                review_status=review_status,
                provenance={"method": "exact_provider_id", "conflict": has_conflict},
                created_at=now,
                updated_at=now,
            )
            session.add(mapping)
            if has_conflict:
                for existing_mapping, existing_event in candidates:
                    existing_mapping.review_status = "conflict"
                    existing_mapping.match_confidence = Decimal("0.0000")
                    existing_mapping.updated_at = now
                    existing_event.review_status = "conflict"
                    existing_event.match_confidence = Decimal("0.0000")
                    existing_event.updated_at = now
        return event, True

    def _resolve_book(
        self,
        session: Session,
        provider_name: str,
        offer: MarketOffer,
        now: datetime,
    ) -> tuple[Sportsbook, ProviderSportsbook]:
        canonical_key, display_name = normalize_book(offer.book_key, offer.book)
        provider_identifier = (offer.book_key or offer.book or canonical_key).strip().lower()
        provider_book = session.scalar(
            select(ProviderSportsbook).where(
                ProviderSportsbook.provider_name == provider_name,
                ProviderSportsbook.provider_identifier == provider_identifier,
            )
        )
        if provider_book is not None:
            book = session.get(Sportsbook, provider_book.sportsbook_id)
            if book is None:
                raise ValueError("Provider sportsbook mapping is invalid")
            return book, provider_book

        book = session.scalar(select(Sportsbook).where(Sportsbook.canonical_key == canonical_key))
        if book is None:
            book = Sportsbook(
                id=self._id_factory(),
                canonical_key=canonical_key,
                display_name=display_name,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(book)
            session.flush()
        provider_book = ProviderSportsbook(
            id=self._id_factory(),
            provider_name=provider_name,
            provider_identifier=provider_identifier,
            provider_display_name=offer.book or display_name,
            sportsbook_id=book.id,
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(provider_book)
        session.flush()
        return book, provider_book

    def _build_observation(
        self,
        snapshot: MarketSnapshot,
        event: CanonicalEvent,
        book: Sportsbook,
        provider_book: ProviderSportsbook,
        game: MarketGame,
        offer: MarketOffer,
        ingested_at: datetime,
    ) -> MarketObservation:
        if not offer.market_type or not isinstance(offer.selection, str):
            raise ValueError("Observation requires market and selection")
        market_type = canonical_market_type(offer.market_type)
        side = selection_side(
            market_type,
            offer.selection,
            home_team=event.home_team,
            away_team=event.away_team,
        )
        point = exact_point(offer.point, required=market_type in {"spread", "total"})
        odds = validate_american_odds(offer.odds)
        observed_at = (
            offer.provider_updated_at
            or game.provider_updated_at
            or snapshot.provider_retrieved_at
            or snapshot.requested_at
        )
        age_seconds = max(0, int((ingested_at - self._as_utc(observed_at)).total_seconds()))
        return MarketObservation(
            id=self._id_factory(),
            snapshot_id=snapshot.id,
            event_id=event.id,
            sportsbook_id=book.id,
            provider_sportsbook_id=provider_book.id,
            market_type=market_type,
            period=FULL_GAME_PERIOD,
            selection_side=side,
            selection_name=offer.selection,
            point=point,
            point_key=point_identity(point),
            american_odds=odds,
            provider_updated_at=offer.provider_updated_at,
            observed_at=self._as_utc(observed_at),
            ingested_at=ingested_at,
            observation_age_seconds=age_seconds,
            freshness_policy_version=FRESHNESS_POLICY_VERSION,
            stale_after_seconds=self._freshness_seconds,
            is_stale=age_seconds > self._provider_quote_max_age_seconds,
            observation_status="active",
            match_review_status=event.review_status,
            raw_source={
                "provider": snapshot.provider_name,
                "provider_event_id": game.provider_event_id,
                **offer.raw_source,
            },
            created_at=ingested_at,
        )

    @classmethod
    def _same_event(
        cls,
        event: CanonicalEvent,
        league: str,
        home_team: str,
        away_team: str,
        scheduled: datetime,
    ) -> bool:
        return (
            event.league == league
            and event.home_team.casefold() == home_team.strip().casefold()
            and event.away_team.casefold() == away_team.strip().casefold()
            and cls._as_utc(event.scheduled_start_utc) == scheduled
        )

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @classmethod
    def _assert_safe_metadata(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).replace("-", "_").lower()
                if normalized in {"apikey", "api_key", "authorization", "password", "token"}:
                    raise ValueError("Credential-bearing metadata cannot be persisted")
                cls._assert_safe_metadata(nested)
        elif isinstance(value, list):
            for nested in value:
                cls._assert_safe_metadata(nested)
