from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.market_models import CanonicalEvent, ProviderEventMapping
from app.db.ncaaf_models import (
    CanonicalProgram,
    CanonicalVenue,
    FootballGameFact,
    ProgramAlias,
    ProgramSeasonMembership,
    ProviderProgramMapping,
    ProviderVenueMapping,
    SourceArtifactIndex,
    SourceManifest,
)
from app.domain.ncaaf import CFBD_PROVIDER, NCAAF_LEAGUE, SOURCE_SCHEMA_VERSION, build_game_eligibility
from app.time import utc_now


class NcaafRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_manifest(self, request_hash: str) -> SourceManifest | None:
        return self.session.scalar(
            select(SourceManifest)
            .where(SourceManifest.provider == CFBD_PROVIDER, SourceManifest.request_hash == request_hash)
            .order_by(desc(SourceManifest.retrieved_at))
            .limit(1)
        )

    def same_manifest(self, request_hash: str, digest: str) -> SourceManifest | None:
        return self.session.scalar(
            select(SourceManifest).where(
                SourceManifest.provider == CFBD_PROVIDER,
                SourceManifest.request_hash == request_hash,
                SourceManifest.content_hash == digest,
            )
        )

    def add_manifest(self, manifest: SourceManifest) -> SourceManifest:
        self.session.add(manifest)
        self.session.flush()
        return manifest

    def add_artifact_index(
        self,
        manifest: SourceManifest,
        *,
        season: int | None,
        week: int | None,
        artifact_kind: str,
        records: list[dict[str, Any]],
    ) -> None:
        game_ids = sorted(
            {
                int(value)
                for record in records
                if (
                    value := record.get(
                        "gameId",
                        record.get("id") if artifact_kind in {"games", "games_teams"} else None,
                    )
                )
                is not None
            }
        )
        existing = self.session.scalar(
            select(SourceArtifactIndex).where(SourceArtifactIndex.manifest_id == manifest.id)
        )
        if existing is not None:
            if existing.included_game_ids != game_ids:
                existing.included_game_ids = game_ids
            return
        self.session.add(
            SourceArtifactIndex(
                manifest_id=manifest.id,
                league=NCAAF_LEAGUE,
                season=season,
                week=week,
                artifact_kind=artifact_kind,
                included_game_ids=game_ids,
                row_count=len(records),
                schema_version=SOURCE_SCHEMA_VERSION,
            )
        )

    def upsert_programs(self, records: list[dict[str, Any]], *, season: int, manifest_id: UUID) -> int:
        changed = 0
        for record in records:
            provider_id = record.get("id")
            name = record.get("school")
            if provider_id is None or not name:
                continue
            mapping = self.session.scalar(
                select(ProviderProgramMapping).where(
                    ProviderProgramMapping.provider == CFBD_PROVIDER,
                    ProviderProgramMapping.provider_team_id == str(provider_id),
                )
            )
            if mapping is None:
                program = CanonicalProgram(
                    canonical_name=str(name),
                    provenance={"provider": CFBD_PROVIDER, "manifest_id": str(manifest_id)},
                    review_status="matched",
                )
                self.session.add(program)
                self.session.flush()
                mapping = ProviderProgramMapping(
                    provider=CFBD_PROVIDER,
                    provider_team_id=str(provider_id),
                    canonical_program_id=program.id,
                    provenance={"match": "exact_provider_id", "manifest_id": str(manifest_id)},
                )
                self.session.add(mapping)
                self.session.add(
                    ProgramAlias(
                        canonical_program_id=program.id,
                        alias=str(name),
                        effective_start_season=season,
                        effective_end_season=season,
                        provider=CFBD_PROVIDER,
                        provenance={"manifest_id": str(manifest_id)},
                    )
                )
                changed += 1
            program_id = mapping.canonical_program_id
            alias = self.session.scalar(
                select(ProgramAlias).where(
                    ProgramAlias.canonical_program_id == program_id,
                    ProgramAlias.alias == str(name),
                    ProgramAlias.effective_start_season == season,
                    ProgramAlias.effective_end_season == season,
                )
            )
            if alias is None:
                self.session.add(
                    ProgramAlias(
                        canonical_program_id=program_id,
                        alias=str(name),
                        effective_start_season=season,
                        effective_end_season=season,
                        provider=CFBD_PROVIDER,
                        provenance={"manifest_id": str(manifest_id)},
                    )
                )
            membership = self.session.scalar(
                select(ProgramSeasonMembership).where(
                    ProgramSeasonMembership.canonical_program_id == program_id,
                    ProgramSeasonMembership.season == season,
                )
            )
            if membership is None:
                self.session.add(
                    ProgramSeasonMembership(
                        canonical_program_id=program_id,
                        season=season,
                        classification=(str(record["classification"]).lower() if record.get("classification") else "fbs"),
                        conference_name=record.get("conference"),
                        provenance={"provider": CFBD_PROVIDER, "manifest_id": str(manifest_id)},
                        review_status="matched",
                    )
                )
        self.session.flush()
        return changed

    def upsert_venues(self, records: list[dict[str, Any]], *, manifest_id: UUID, retrieved_at: datetime) -> int:
        changed = 0
        for record in records:
            provider_id = record.get("id")
            name = record.get("name")
            if provider_id is None or not name:
                continue
            mapping = self.session.scalar(
                select(ProviderVenueMapping).where(
                    ProviderVenueMapping.provider == CFBD_PROVIDER,
                    ProviderVenueMapping.provider_venue_id == str(provider_id),
                )
            )
            if mapping is not None:
                continue
            location = record.get("location") or {}
            venue = CanonicalVenue(
                canonical_name=str(name),
                timezone=record.get("timezone") or location.get("timezone"),
                latitude=_string_or_none(record.get("latitude", location.get("latitude"))),
                longitude=_string_or_none(record.get("longitude", location.get("longitude"))),
                elevation=_string_or_none(record.get("elevation", location.get("elevation"))),
                dome=record.get("dome"),
                surface=record.get("grass") and "grass" or record.get("surface"),
                source_vintage=retrieved_at,
                provenance={"provider": CFBD_PROVIDER, "manifest_id": str(manifest_id), "current_vintage": True},
                review_status="matched",
            )
            self.session.add(venue)
            self.session.flush()
            self.session.add(
                ProviderVenueMapping(
                    provider=CFBD_PROVIDER,
                    provider_venue_id=str(provider_id),
                    canonical_venue_id=venue.id,
                    provenance={"match": "exact_provider_id", "manifest_id": str(manifest_id)},
                )
            )
            changed += 1
        self.session.flush()
        return changed

    def ingest_games(self, records: list[dict[str, Any]], *, manifest_id: UUID, season: int) -> int:
        inserted = 0
        for game in records:
            provider_game_id = game.get("id")
            if provider_game_id is None:
                continue
            existing = self.session.scalar(
                select(FootballGameFact).where(
                    FootballGameFact.manifest_id == manifest_id,
                    FootballGameFact.provider == CFBD_PROVIDER,
                    FootballGameFact.provider_game_id == str(provider_game_id),
                )
            )
            if existing is not None:
                home_program_id = self._program_id(game.get("homeId"))
                away_program_id = self._program_id(game.get("awayId"))
                normalized = dict(game)
                if home_program_id is None or away_program_id is None:
                    normalized["homeId"] = None if home_program_id is None else game.get("homeId")
                    normalized["awayId"] = None if away_program_id is None else game.get("awayId")
                eligibility = build_game_eligibility(normalized)
                existing.home_program_id = home_program_id
                existing.away_program_id = away_program_id
                existing.model_eligible = eligibility.eligible
                existing.exclusion_reason = eligibility.exclusion_reason
                existing.target_margin = eligibility.margin
                existing.target_total = eligibility.total
                if existing.canonical_event_id is None:
                    event = self._event_for_game(game, home_program_id, away_program_id, manifest_id)
                    existing.canonical_event_id = event.id if event else None
                continue
            home_program_id = self._program_id(game.get("homeId"))
            away_program_id = self._program_id(game.get("awayId"))
            normalized = dict(game)
            if home_program_id is None or away_program_id is None:
                normalized["homeId"] = None if home_program_id is None else game.get("homeId")
                normalized["awayId"] = None if away_program_id is None else game.get("awayId")
            eligibility = build_game_eligibility(normalized)
            event = self._event_for_game(game, home_program_id, away_program_id, manifest_id)
            previous = self.session.scalar(
                select(FootballGameFact)
                .where(
                    FootballGameFact.provider == CFBD_PROVIDER,
                    FootballGameFact.provider_game_id == str(provider_game_id),
                )
                .order_by(desc(FootballGameFact.created_at))
                .limit(1)
            )
            self.session.add(
                FootballGameFact(
                    manifest_id=manifest_id,
                    provider=CFBD_PROVIDER,
                    provider_game_id=str(provider_game_id),
                    canonical_event_id=event.id if event else None,
                    season=season,
                    week=game.get("week"),
                    season_type=game.get("seasonType"),
                    completed=game.get("completed") is True,
                    overtime_periods=game.get("overtimePeriods"),
                    neutral_site=game.get("neutralSite"),
                    home_program_id=home_program_id,
                    away_program_id=away_program_id,
                    home_classification=_lower_or_none(game.get("homeClassification")),
                    away_classification=_lower_or_none(game.get("awayClassification")),
                    final_home_points=game.get("homePoints"),
                    final_away_points=game.get("awayPoints"),
                    target_margin=eligibility.margin,
                    target_total=eligibility.total,
                    model_eligible=eligibility.eligible,
                    exclusion_reason=eligibility.exclusion_reason,
                    provenance={"provider": CFBD_PROVIDER, "manifest_id": str(manifest_id), "availability": "reconstructed"},
                    supersedes_game_fact_id=previous.id if previous else None,
                )
            )
            inserted += 1
        self.session.flush()
        return inserted

    def _program_id(self, provider_id: Any) -> UUID | None:
        if provider_id is None:
            return None
        return self.session.scalar(
            select(ProviderProgramMapping.canonical_program_id).where(
                ProviderProgramMapping.provider == CFBD_PROVIDER,
                ProviderProgramMapping.provider_team_id == str(provider_id),
                ProviderProgramMapping.review_status == "matched",
            )
        )

    def _event_for_game(
        self,
        game: dict[str, Any],
        home_program_id: UUID | None,
        away_program_id: UUID | None,
        manifest_id: UUID,
    ) -> CanonicalEvent | None:
        provider_game_id = str(game["id"])
        mappings = self.session.scalars(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider_name == CFBD_PROVIDER,
                ProviderEventMapping.provider_sport_key == "americanfootball_ncaaf",
                ProviderEventMapping.provider_event_id == provider_game_id,
            )
        ).all()
        if len(mappings) == 1:
            return self.session.get(CanonicalEvent, mappings[0].canonical_event_id)
        if mappings or home_program_id is None or away_program_id is None or not game.get("startDate"):
            return None
        start = datetime.fromisoformat(str(game["startDate"]).replace("Z", "+00:00"))
        venue_id = self._venue_id(game.get("venueId"))
        event = CanonicalEvent(
            league=NCAAF_LEAGUE,
            home_team=str(game.get("homeTeam") or "Unknown"),
            away_team=str(game.get("awayTeam") or "Unknown"),
            scheduled_start_utc=start,
            event_status="final" if game.get("completed") else "scheduled",
            match_confidence=Decimal("1.0000"),
            review_status="matched",
            match_provenance={"provider": CFBD_PROVIDER, "match": "exact_provider_id"},
            home_program_id=home_program_id,
            away_program_id=away_program_id,
            venue_id=venue_id,
            season=game.get("season"),
            week=game.get("week"),
            season_type=game.get("seasonType"),
            neutral_site=game.get("neutralSite"),
            schedule_revision=str(manifest_id),
            schedule_provenance={"manifest_id": str(manifest_id), "availability": "reconstructed"},
        )
        self.session.add(event)
        self.session.flush()
        self.session.add(
            ProviderEventMapping(
                provider_name=CFBD_PROVIDER,
                provider_sport_key="americanfootball_ncaaf",
                provider_event_id=provider_game_id,
                canonical_event_id=event.id,
                match_confidence=Decimal("1.0000"),
                review_status="matched",
                provenance={"match": "exact_provider_id", "manifest_id": str(manifest_id)},
                updated_at=utc_now(),
            )
        )
        return event

    def _venue_id(self, provider_id: Any) -> UUID | None:
        if provider_id is None:
            return None
        return self.session.scalar(
            select(ProviderVenueMapping.canonical_venue_id).where(
                ProviderVenueMapping.provider == CFBD_PROVIDER,
                ProviderVenueMapping.provider_venue_id == str(provider_id),
            )
        )


def _string_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _lower_or_none(value: Any) -> str | None:
    return None if value is None else str(value).lower()
