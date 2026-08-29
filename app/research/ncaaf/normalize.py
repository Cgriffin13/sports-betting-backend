from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import pyarrow as pa
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.ncaaf_store import ImmutableArtifactStore
from app.db.ncaaf_models import (
    FootballGameFact,
    ProgramSeasonMembership,
    ProviderProgramMapping,
    SourceManifest,
)
from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash
from app.research.ncaaf.contracts import (
    AVAILABILITY_POLICY_VERSION,
    NORMALIZATION_VERSION,
    NORMALIZED_SCHEMA_VERSION,
    reconstructed_available_at,
    source_manifest_fingerprint,
)

UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")

GAME_SCHEMA = pa.schema(
    [
        ("provider_game_id", pa.int64()),
        ("canonical_event_id", pa.string()),
        ("season", pa.int16()),
        ("week", pa.int16()),
        ("season_type", pa.string()),
        ("kickoff", UTC_TIMESTAMP),
        ("completed", pa.bool_()),
        ("home_program_id", pa.string()),
        ("away_program_id", pa.string()),
        ("home_provider_team_id", pa.int32()),
        ("away_provider_team_id", pa.int32()),
        ("home_team", pa.string()),
        ("away_team", pa.string()),
        ("home_classification", pa.string()),
        ("away_classification", pa.string()),
        ("home_conference", pa.string()),
        ("away_conference", pa.string()),
        ("neutral_site", pa.bool_()),
        ("conference_game", pa.bool_()),
        ("postseason", pa.bool_()),
        ("venue_id", pa.int32()),
        ("home_points", pa.int16()),
        ("away_points", pa.int16()),
        ("target_margin", pa.int16()),
        ("target_total", pa.int16()),
        ("model_eligible", pa.bool_()),
        ("exclusion_reason", pa.string()),
        ("effective_at", UTC_TIMESTAMP),
        ("available_at", UTC_TIMESTAMP),
        ("local_ingested_at", UTC_TIMESTAMP),
        ("availability_mode", pa.string()),
        ("availability_policy_version", pa.string()),
        ("source_manifest_id", pa.string()),
        ("source_content_hash", pa.string()),
    ]
)

PLAY_SCHEMA = pa.schema(
    [
        ("provider_game_id", pa.int64()),
        ("play_id", pa.string()),
        ("drive_id", pa.string()),
        ("season", pa.int16()),
        ("week", pa.int16()),
        ("season_type", pa.string()),
        ("kickoff", UTC_TIMESTAMP),
        ("offense_program_id", pa.string()),
        ("defense_program_id", pa.string()),
        ("offense", pa.string()),
        ("defense", pa.string()),
        ("period", pa.int8()),
        ("clock_minutes", pa.int8()),
        ("clock_seconds", pa.int8()),
        ("down", pa.int8()),
        ("distance", pa.int16()),
        ("yards_to_goal", pa.int16()),
        ("yards_gained", pa.int16()),
        ("play_type", pa.string()),
        ("play_text", pa.string()),
        ("ppa", pa.float64()),
        ("wallclock", pa.string()),
        ("scoring", pa.bool_()),
        ("effective_at", UTC_TIMESTAMP),
        ("available_at", UTC_TIMESTAMP),
        ("local_ingested_at", UTC_TIMESTAMP),
        ("availability_mode", pa.string()),
        ("source_manifest_id", pa.string()),
        ("source_content_hash", pa.string()),
        ("identity_resolved", pa.bool_()),
    ]
)

DRIVE_SCHEMA = pa.schema(
    [
        ("provider_game_id", pa.int64()),
        ("drive_id", pa.string()),
        ("season", pa.int16()),
        ("kickoff", UTC_TIMESTAMP),
        ("offense_program_id", pa.string()),
        ("defense_program_id", pa.string()),
        ("offense", pa.string()),
        ("defense", pa.string()),
        ("drive_number", pa.int16()),
        ("start_period", pa.int8()),
        ("end_period", pa.int8()),
        ("plays", pa.int16()),
        ("yards", pa.int16()),
        ("points", pa.int16()),
        ("drive_result", pa.string()),
        ("scoring", pa.bool_()),
        ("effective_at", UTC_TIMESTAMP),
        ("available_at", UTC_TIMESTAMP),
        ("local_ingested_at", UTC_TIMESTAMP),
        ("availability_mode", pa.string()),
        ("source_manifest_id", pa.string()),
        ("source_content_hash", pa.string()),
        ("identity_resolved", pa.bool_()),
    ]
)

TEAM_STAT_SCHEMA = pa.schema(
    [
        ("provider_game_id", pa.int64()),
        ("season", pa.int16()),
        ("week", pa.int16()),
        ("kickoff", UTC_TIMESTAMP),
        ("program_id", pa.string()),
        ("provider_team_id", pa.int32()),
        ("home_away", pa.string()),
        ("category", pa.string()),
        ("value", pa.string()),
        ("effective_at", UTC_TIMESTAMP),
        ("available_at", UTC_TIMESTAMP),
        ("local_ingested_at", UTC_TIMESTAMP),
        ("availability_mode", pa.string()),
        ("source_manifest_id", pa.string()),
        ("source_content_hash", pa.string()),
    ]
)

MEMBERSHIP_SCHEMA = pa.schema(
    [
        ("program_id", pa.string()),
        ("provider_team_id", pa.int32()),
        ("season", pa.int16()),
        ("classification", pa.string()),
        ("conference", pa.string()),
        ("review_status", pa.string()),
        ("source_manifest_id", pa.string()),
    ]
)

VENUE_SCHEMA = pa.schema(
    [
        ("provider_venue_id", pa.int32()),
        ("name", pa.string()),
        ("timezone", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("elevation", pa.float64()),
        ("dome", pa.bool_()),
        ("grass", pa.bool_()),
        ("capacity", pa.int32()),
        ("source_vintage", UTC_TIMESTAMP),
        ("historical_validity", pa.string()),
        ("source_manifest_id", pa.string()),
        ("source_content_hash", pa.string()),
    ]
)


class NormalizedCorpusBuilder:
    def __init__(
        self,
        session: Session,
        source_store: ImmutableArtifactStore,
        research_store: ResearchArtifactStore,
    ) -> None:
        self.session = session
        self.source_store = source_store
        self.research_store = research_store

    def build(self, start_season: int, end_season: int) -> dict[str, Any]:
        manifests = self._latest_manifests(start_season, end_season)
        manifest_maps = [_manifest_map(item) for item in manifests]
        by_endpoint: dict[str, list[SourceManifest]] = defaultdict(list)
        for source_manifest in manifests:
            by_endpoint[source_manifest.endpoint].append(source_manifest)
        program_ids = {
            int(provider_id): str(program_id)
            for provider_id, program_id in self.session.execute(
                select(ProviderProgramMapping.provider_team_id, ProviderProgramMapping.canonical_program_id).where(
                    ProviderProgramMapping.provider == "cfbd", ProviderProgramMapping.review_status == "matched"
                )
            )
        }
        game_facts = self._latest_game_facts(start_season, end_season)
        artifacts: list[dict[str, Any]] = []
        games_by_season: dict[int, dict[int, dict[str, Any]]] = {}
        for season in range(start_season, end_season + 1):
            season_manifests = [item for item in by_endpoint["games"] if _season(item) == season]
            game_manifest = _prefer_manifest(season_manifests, prefer_unclassified=True)
            if game_manifest is None:
                raise ValueError(f"no cached games manifest for season {season}")
            records = _records(self.source_store, game_manifest)
            rows, lookup = _normalize_games(records, game_manifest, game_facts, program_ids)
            games_by_season[season] = lookup
            artifact = self.research_store.write_parquet(
                pa.Table.from_pylist(rows, schema=GAME_SCHEMA),
                namespace="normalized",
                dataset="games",
                season=season,
                schema_version=NORMALIZED_SCHEMA_VERSION,
                transformation_version=NORMALIZATION_VERSION,
                source_manifests=[_manifest_map(game_manifest)],
                sort_by=(("kickoff", "ascending"), ("provider_game_id", "ascending")),
            )
            artifacts.append(artifact_dict(artifact))

            for endpoint, dataset, schema, function in (
                ("plays", "plays", PLAY_SCHEMA, _normalize_plays),
                ("drives", "drives", DRIVE_SCHEMA, _normalize_drives),
                ("games/teams", "team_game_statistics", TEAM_STAT_SCHEMA, _normalize_team_stats),
            ):
                parts = [item for item in by_endpoint[endpoint] if _season(item) == season]
                rows_for_dataset: list[dict[str, Any]] = []
                used: list[dict[str, Any]] = []
                for source_manifest in sorted(parts, key=lambda item: (_week(item) or 0, item.request_hash)):
                    rows_for_dataset.extend(
                        function(_records(self.source_store, source_manifest), source_manifest, lookup, program_ids)
                    )
                    used.append(_manifest_map(source_manifest))
                artifact = self.research_store.write_parquet(
                    pa.Table.from_pylist(rows_for_dataset, schema=schema),
                    namespace="normalized",
                    dataset=dataset,
                    season=season,
                    schema_version=NORMALIZED_SCHEMA_VERSION,
                    transformation_version=NORMALIZATION_VERSION,
                    source_manifests=used,
                    sort_by=(("provider_game_id", "ascending"),),
                )
                artifacts.append(artifact_dict(artifact))

            team_parts = [item for item in by_endpoint["teams"] if _season(item) == season]
            membership_sources = [_manifest_map(item) for item in team_parts]
            membership_rows = self._memberships(season)
            artifact = self.research_store.write_parquet(
                pa.Table.from_pylist(membership_rows, schema=MEMBERSHIP_SCHEMA),
                namespace="normalized",
                dataset="program_season_membership",
                season=season,
                schema_version=NORMALIZED_SCHEMA_VERSION,
                transformation_version=NORMALIZATION_VERSION,
                source_manifests=membership_sources,
                sort_by=(("program_id", "ascending"),),
            )
            artifacts.append(artifact_dict(artifact))

        venue_manifest = _prefer_manifest(by_endpoint["venues"])
        if venue_manifest is not None:
            rows = _normalize_venues(_records(self.source_store, venue_manifest), venue_manifest)
            artifact = self.research_store.write_parquet(
                pa.Table.from_pylist(rows, schema=VENUE_SCHEMA),
                namespace="normalized",
                dataset="venues",
                season=None,
                schema_version=NORMALIZED_SCHEMA_VERSION,
                transformation_version=NORMALIZATION_VERSION,
                source_manifests=[_manifest_map(venue_manifest)],
                sort_by=(("provider_venue_id", "ascending"),),
            )
            artifacts.append(artifact_dict(artifact))

        configuration = {
            "league": "NCAAF",
            "start_season": start_season,
            "end_season": end_season,
            "schema_version": NORMALIZED_SCHEMA_VERSION,
            "transformation_version": NORMALIZATION_VERSION,
            "availability_policy_version": AVAILABILITY_POLICY_VERSION,
            "source_manifest_fingerprint": source_manifest_fingerprint(manifest_maps),
        }
        result_manifest: dict[str, Any] = {
            **configuration,
            "artifacts": artifacts,
            "dataset_hash": dataset_hash(artifacts, configuration),
            "source_manifest_count": len(manifest_maps),
            "network_calls": 0,
        }
        manifest_id, _ = self.research_store.write_manifest("normalized", result_manifest)
        result_manifest["manifest_id"] = manifest_id
        return result_manifest

    def _latest_manifests(self, start: int, end: int) -> list[SourceManifest]:
        candidates = self.session.scalars(
            select(SourceManifest).where(SourceManifest.provider == "cfbd").order_by(SourceManifest.retrieved_at)
        ).all()
        latest: dict[str, SourceManifest] = {}
        for item in candidates:
            season = _season(item)
            if item.endpoint in {"venues", "conferences"} or season is None or start <= season <= end:
                latest[item.request_hash] = item
        return sorted(latest.values(), key=lambda item: (item.endpoint, item.request_hash))

    def _latest_game_facts(self, start: int, end: int) -> dict[int, FootballGameFact]:
        facts = self.session.scalars(
            select(FootballGameFact)
            .where(FootballGameFact.season.between(start, end))
            .order_by(FootballGameFact.created_at)
        ).all()
        return {int(item.provider_game_id): item for item in facts}

    def _memberships(self, season: int) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(
                ProgramSeasonMembership,
                ProviderProgramMapping.provider_team_id,
            )
            .join(
                ProviderProgramMapping,
                ProviderProgramMapping.canonical_program_id == ProgramSeasonMembership.canonical_program_id,
            )
            .where(ProgramSeasonMembership.season == season, ProviderProgramMapping.provider == "cfbd")
        )
        return [
            {
                "program_id": str(membership.canonical_program_id),
                "provider_team_id": int(provider_id),
                "season": season,
                "classification": membership.classification,
                "conference": membership.conference_name,
                "review_status": membership.review_status,
                "source_manifest_id": str(membership.provenance.get("manifest_id", "")),
            }
            for membership, provider_id in rows
        ]


def _manifest_map(item: SourceManifest) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "endpoint": item.endpoint,
        "request_hash": item.request_hash,
        "content_hash": item.content_hash,
        "schema_version": item.schema_version,
        "retrieved_at": _aware(item.retrieved_at),
        "artifact_uri": item.artifact_uri,
        "request_parameters": item.request_parameters,
        "availability_mode": item.availability_mode,
    }


def _season(item: SourceManifest) -> int | None:
    value = item.request_parameters.get("year")
    return None if value is None else int(value)


def _week(item: SourceManifest) -> int | None:
    value = item.request_parameters.get("week")
    return None if value is None else int(value)


def _prefer_manifest(items: Sequence[SourceManifest], *, prefer_unclassified: bool = False) -> SourceManifest | None:
    if not items:
        return None
    return sorted(
        items,
        key=lambda item: (
            1 if prefer_unclassified and "classification" not in item.request_parameters else 0,
            item.retrieved_at,
        ),
    )[-1]


def _records(store: ImmutableArtifactStore, manifest: SourceManifest) -> list[dict[str, Any]]:
    payload = json.loads(store.get(manifest.artifact_uri))
    if not isinstance(payload, list):
        payload = [payload]
    return [cast(dict[str, Any], item) for item in payload]


def _normalize_games(
    records: Iterable[dict[str, Any]],
    manifest: SourceManifest,
    facts: Mapping[int, FootballGameFact],
    program_ids: Mapping[int, str],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    lookup: dict[int, dict[str, Any]] = {}
    for raw in records:
        game_id = _int(raw.get("id"))
        kickoff = _datetime(raw.get("startDate"))
        if game_id is None or kickoff is None:
            continue
        fact = facts.get(game_id)
        row = {
            "provider_game_id": game_id,
            "canonical_event_id": str(fact.canonical_event_id) if fact and fact.canonical_event_id else None,
            "season": _int(raw.get("season")),
            "week": _int(raw.get("week")),
            "season_type": raw.get("seasonType"),
            "kickoff": kickoff,
            "completed": bool(raw.get("completed")),
            "home_program_id": program_ids.get(_int(raw.get("homeId")) or -1),
            "away_program_id": program_ids.get(_int(raw.get("awayId")) or -1),
            "home_provider_team_id": _int(raw.get("homeId")),
            "away_provider_team_id": _int(raw.get("awayId")),
            "home_team": raw.get("homeTeam"),
            "away_team": raw.get("awayTeam"),
            "home_classification": _lower(raw.get("homeClassification")),
            "away_classification": _lower(raw.get("awayClassification")),
            "home_conference": raw.get("homeConference"),
            "away_conference": raw.get("awayConference"),
            "neutral_site": raw.get("neutralSite"),
            "conference_game": raw.get("conferenceGame"),
            "postseason": str(raw.get("seasonType", "")).lower() != "regular",
            "venue_id": _int(raw.get("venueId")),
            "home_points": _int(raw.get("homePoints")),
            "away_points": _int(raw.get("awayPoints")),
            "target_margin": fact.target_margin if fact else None,
            "target_total": fact.target_total if fact else None,
            "model_eligible": bool(fact.model_eligible) if fact else False,
            "exclusion_reason": fact.exclusion_reason if fact else "missing_canonical_game_fact",
            "effective_at": kickoff,
            "available_at": reconstructed_available_at(kickoff),
            "local_ingested_at": _aware(manifest.retrieved_at),
            "availability_mode": manifest.availability_mode,
            "availability_policy_version": AVAILABILITY_POLICY_VERSION,
            "source_manifest_id": str(manifest.id),
            "source_content_hash": manifest.content_hash,
        }
        rows.append(row)
        lookup[game_id] = row
    return rows, lookup


def _identity(raw_name: Any, game: Mapping[str, Any], program_ids: Mapping[int, str]) -> str | None:
    if raw_name == game.get("home_team"):
        return program_ids.get(cast(int, game.get("home_provider_team_id")))
    if raw_name == game.get("away_team"):
        return program_ids.get(cast(int, game.get("away_provider_team_id")))
    return None


def _base_fact(raw: Mapping[str, Any], manifest: SourceManifest, game: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "provider_game_id": int(raw["gameId"]),
        "season": game["season"],
        "kickoff": game["kickoff"],
        "effective_at": game["kickoff"],
        "available_at": game["available_at"],
        "local_ingested_at": _aware(manifest.retrieved_at),
        "availability_mode": manifest.availability_mode,
        "source_manifest_id": str(manifest.id),
        "source_content_hash": manifest.content_hash,
    }


def _normalize_plays(
    records: Iterable[dict[str, Any]],
    manifest: SourceManifest,
    games: Mapping[int, dict[str, Any]],
    program_ids: Mapping[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in records:
        game = games.get(_int(raw.get("gameId")) or -1)
        if game is None:
            continue
        offense = _identity(raw.get("offense"), game, program_ids)
        defense = _identity(raw.get("defense"), game, program_ids)
        clock = raw.get("clock") or {}
        rows.append(
            {
                **_base_fact(raw, manifest, game),
                "play_id": str(raw.get("id")),
                "drive_id": _str(raw.get("driveId")),
                "week": game["week"],
                "season_type": game["season_type"],
                "offense_program_id": offense,
                "defense_program_id": defense,
                "offense": raw.get("offense"),
                "defense": raw.get("defense"),
                "period": _int(raw.get("period")),
                "clock_minutes": _int(clock.get("minutes")),
                "clock_seconds": _int(clock.get("seconds")),
                "down": _int(raw.get("down")),
                "distance": _int(raw.get("distance")),
                "yards_to_goal": _int(raw.get("yardsToGoal")),
                "yards_gained": _int(raw.get("yardsGained")),
                "play_type": raw.get("playType"),
                "play_text": raw.get("playText"),
                "ppa": _float(raw.get("ppa")),
                "wallclock": raw.get("wallclock"),
                "scoring": raw.get("scoring"),
                "identity_resolved": offense is not None and defense is not None,
            }
        )
    return rows


def _normalize_drives(
    records: Iterable[dict[str, Any]],
    manifest: SourceManifest,
    games: Mapping[int, dict[str, Any]],
    program_ids: Mapping[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in records:
        game = games.get(_int(raw.get("gameId")) or -1)
        if game is None:
            continue
        offense = _identity(raw.get("offense"), game, program_ids)
        defense = _identity(raw.get("defense"), game, program_ids)
        start_score = _int(raw.get("startOffenseScore"))
        end_score = _int(raw.get("endOffenseScore"))
        points = None if start_score is None or end_score is None else end_score - start_score
        rows.append(
            {
                **_base_fact(raw, manifest, game),
                "drive_id": str(raw.get("id")),
                "offense_program_id": offense,
                "defense_program_id": defense,
                "offense": raw.get("offense"),
                "defense": raw.get("defense"),
                "drive_number": _int(raw.get("driveNumber")),
                "start_period": _int(raw.get("startPeriod")),
                "end_period": _int(raw.get("endPeriod")),
                "plays": _int(raw.get("plays")),
                "yards": _int(raw.get("yards")),
                "points": points,
                "drive_result": raw.get("driveResult"),
                "scoring": raw.get("scoring"),
                "identity_resolved": offense is not None and defense is not None,
            }
        )
    return rows


def _normalize_team_stats(
    records: Iterable[dict[str, Any]],
    manifest: SourceManifest,
    games: Mapping[int, dict[str, Any]],
    program_ids: Mapping[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in records:
        game_id = _int(raw.get("id"))
        game = games.get(game_id or -1)
        if game is None:
            continue
        for team in raw.get("teams") or []:
            team_id = _int(team.get("teamId"))
            program_id = program_ids.get(team_id or -1)
            for stat in team.get("stats") or []:
                rows.append(
                    {
                        "provider_game_id": game_id,
                        "season": game["season"],
                        "week": game["week"],
                        "kickoff": game["kickoff"],
                        "program_id": program_id,
                        "provider_team_id": team_id,
                        "home_away": _lower(team.get("homeAway")),
                        "category": stat.get("category"),
                        "value": _str(stat.get("stat")),
                        "effective_at": game["kickoff"],
                        "available_at": game["available_at"],
                        "local_ingested_at": _aware(manifest.retrieved_at),
                        "availability_mode": manifest.availability_mode,
                        "source_manifest_id": str(manifest.id),
                        "source_content_hash": manifest.content_hash,
                    }
                )
    return rows


def _normalize_venues(records: Iterable[dict[str, Any]], manifest: SourceManifest) -> list[dict[str, Any]]:
    return [
        {
            "provider_venue_id": _int(raw.get("id")),
            "name": raw.get("name"),
            "timezone": raw.get("timezone"),
            "latitude": _float(raw.get("latitude")),
            "longitude": _float(raw.get("longitude")),
            "elevation": _float(raw.get("elevation")),
            "dome": raw.get("dome"),
            "grass": raw.get("grass"),
            "capacity": _int(raw.get("capacity")),
            "source_vintage": _aware(manifest.retrieved_at),
            "historical_validity": "current_vintage_not_assumed_historical",
            "source_manifest_id": str(manifest.id),
            "source_content_hash": manifest.content_hash,
        }
        for raw in records
        if raw.get("id") is not None
    ]


def _datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)


def _lower(value: Any) -> str | None:
    return None if value is None else str(value).lower()
