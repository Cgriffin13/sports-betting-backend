from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc

from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash
from app.research.ncaaf.contracts import stable_hash

PRESEASON_SCHEMA_VERSION = "ncaaf-preseason-facts-v1"
PRESEASON_TRANSFORMATION_VERSION = "cfbd-preseason-normalize-v1"
PRESEASON_FEATURE_SET_VERSION = "ncaaf-preseason-personnel-v1"
COMBINED_FEATURE_SET_VERSION = "ncaaf-efficiency-plus-preseason-v1"
PRESEASON_AVAILABILITY_POLICY_VERSION = "preseason-reconstructed-season-start-v1"
PORTAL_AVAILABILITY_POLICY_VERSION = "portal-transfer-date-v1"
COACH_AVAILABILITY_POLICY_VERSION = "coach-effective-season-v1"
PRESEASON_EXPERIMENT_VERSION = "ncaaf-preseason-experiment-v1"

SOURCE_ENDPOINTS = frozenset(
    {
        "player/returning",
        "player/portal",
        "recruiting/teams",
        "talent",
        "roster",
        "stats/player/season",
        "coaches",
    }
)

POSITION_GROUPS: dict[str, str] = {
    "QB": "qb",
    "RB": "offense_skill",
    "FB": "offense_skill",
    "WR": "offense_skill",
    "TE": "offense_skill",
    "OL": "offensive_line",
    "OT": "offensive_line",
    "OG": "offensive_line",
    "C": "offensive_line",
    "DL": "defense",
    "DE": "defense",
    "DT": "defense",
    "EDGE": "defense",
    "LB": "defense",
    "DB": "defense",
    "CB": "defense",
    "S": "defense",
}


@dataclass(frozen=True, slots=True)
class SourcePart:
    manifest_id: str
    endpoint: str
    parameters: Mapping[str, Any]
    content_hash: str
    retrieved_at: datetime
    response_bytes: int
    records: Sequence[Mapping[str, Any]]


def normalize_team_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("&", "and").split())


def build_team_name_map(normalized_games: pa.Table) -> dict[str, str]:
    result: dict[str, str] = {}
    conflicts: set[str] = set()
    for row in normalized_games.select(
        ["home_program_id", "away_program_id", "home_team", "away_team"]
    ).to_pylist():
        for side in ("home", "away"):
            program_id = row[f"{side}_program_id"]
            name = normalize_team_name(row[f"{side}_team"])
            if not name or program_id is None:
                continue
            existing = result.get(name)
            if existing is not None and existing != str(program_id):
                conflicts.add(name)
            else:
                result[name] = str(program_id)
    for conflict in conflicts:
        result.pop(conflict, None)
    return result


def normalize_preseason_facts(
    parts: Sequence[SourcePart],
    *,
    normalized_games: pa.Table,
    start_season: int = 2014,
    end_season: int = 2024,
) -> tuple[pa.Table, dict[str, Any]]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter preseason normalization")
    unique_parts: dict[str, SourcePart] = {}
    for part in parts:
        existing_part = unique_parts.get(part.manifest_id)
        if existing_part is not None and (
            existing_part.endpoint != part.endpoint
            or existing_part.parameters != part.parameters
            or existing_part.content_hash != part.content_hash
        ):
            raise ValueError(f"conflicting source manifest ID: {part.manifest_id}")
        unique_parts[part.manifest_id] = part
    parts = tuple(unique_parts.values())
    name_map = build_team_name_map(normalized_games)
    id_map: dict[int, str] = {}
    first_kickoff: dict[int, datetime] = {}
    for row in normalized_games.select(
        ["season", "kickoff", "home_provider_team_id", "away_provider_team_id", "home_program_id", "away_program_id"]
    ).to_pylist():
        season = int(row["season"])
        kickoff = _utc(row["kickoff"])
        first_kickoff[season] = min(first_kickoff.get(season, kickoff), kickoff)
        for side in ("home", "away"):
            team_id, program_id = row[f"{side}_provider_team_id"], row[f"{side}_program_id"]
            if team_id is not None and program_id is not None:
                id_map[int(team_id)] = str(program_id)

    by_endpoint: dict[str, list[SourcePart]] = defaultdict(list)
    for part in parts:
        if part.endpoint in SOURCE_ENDPOINTS:
            by_endpoint[part.endpoint].append(part)

    facts: dict[tuple[str, int], dict[str, Any]] = {}
    source_meta: dict[tuple[str, int], set[tuple[str, str, str, datetime]]] = defaultdict(set)

    def fact(program_id: str, season: int) -> dict[str, Any]:
        key = (program_id, season)
        if key not in facts:
            facts[key] = _empty_fact(program_id, season, first_kickoff.get(season))
        return facts[key]

    def mapped(name: Any) -> str | None:
        return name_map.get(normalize_team_name(name))

    for part in by_endpoint["player/returning"]:
        for raw in part.records:
            season = int(raw.get("season") or part.parameters.get("year") or 0)
            program_id = mapped(raw.get("team"))
            if program_id is None or not start_season <= season <= end_season:
                continue
            row = fact(program_id, season)
            for source, target in (
                ("percentPPA", "returning_percent_ppa"),
                ("percentPassingPPA", "returning_percent_passing_ppa"),
                ("percentReceivingPPA", "returning_percent_receiving_ppa"),
                ("percentRushingPPA", "returning_percent_rushing_ppa"),
                ("usage", "returning_usage"),
                ("passingUsage", "returning_passing_usage"),
                ("receivingUsage", "returning_receiving_usage"),
                ("rushingUsage", "returning_rushing_usage"),
            ):
                row[target] = _float(raw.get(source))
            row["returning_available"] = True
            _source(source_meta, program_id, season, part)

    for endpoint, field_map in (
        ("recruiting/teams", (("rank", "recruiting_rank"), ("points", "recruiting_points"))),
        ("talent", (("talent", "talent_composite"),)),
    ):
        for part in by_endpoint[endpoint]:
            for raw in part.records:
                season = int(raw.get("year") or part.parameters.get("year") or 0)
                program_id = mapped(raw.get("team"))
                if program_id is None or not start_season <= season <= end_season:
                    continue
                row = fact(program_id, season)
                for source, target in field_map:
                    row[target] = _float(raw.get(source))
                row["recruiting_available" if endpoint.startswith("recruiting") else "talent_available"] = True
                _source(source_meta, program_id, season, part)

    rosters: dict[tuple[str, int], dict[str, str]] = defaultdict(dict)
    for part in by_endpoint["roster"]:
        season = int(part.parameters.get("year") or 0)
        for raw in part.records:
            program_id = mapped(raw.get("team"))
            player_id = str(raw.get("id") or "").strip()
            if program_id is None or not player_id or not start_season <= season <= end_season:
                continue
            rosters[(program_id, season)][player_id] = str(raw.get("position") or "").upper()
            _source(source_meta, program_id, season, part)

    passing: dict[tuple[str, int, str], dict[str, float]] = defaultdict(dict)
    for part in by_endpoint["stats/player/season"]:
        for raw in part.records:
            season = int(raw.get("season") or part.parameters.get("year") or 0)
            program_id = mapped(raw.get("team"))
            player_id = str(raw.get("playerId") or "").strip()
            if program_id is None or not player_id:
                continue
            passing[(program_id, season, player_id)][str(raw.get("statType") or "").upper()] = _float(
                raw.get("stat")
            ) or 0.0
            if season + 1 <= end_season:
                _source(source_meta, program_id, season + 1, part)

    for (program_id, season), players in rosters.items():
        row = fact(program_id, season)
        current_ids = set(players)
        prior = rosters.get((program_id, season - 1), {})
        prior_ids = set(prior)
        overlap = current_ids & prior_ids
        row["roster_count"] = len(current_ids)
        row["prior_roster_count"] = len(prior_ids)
        row["roster_returning_count"] = len(overlap)
        row["roster_continuity_ratio"] = _ratio(len(overlap), len(prior_ids))
        for group in ("qb", "offense_skill", "offensive_line", "defense"):
            prior_group = {pid for pid, pos in prior.items() if _position_group(pos) == group}
            current_group = {pid for pid, pos in players.items() if _position_group(pos) == group}
            row[f"{group}_continuity_ratio"] = _ratio(len(prior_group & current_group), len(prior_group))
        row["roster_available"] = True

        prior_passers = [
            (pid, values.get("ATT", 0.0), values.get("YDS", 0.0))
            for (pid_program, pid_season, pid), values in passing.items()
            if pid_program == program_id and pid_season == season - 1
        ]
        if prior_passers:
            prior_passers.sort(key=lambda item: (-item[1], -item[2], item[0]))
            leader, leader_att, leader_yards = prior_passers[0]
            total_att = sum(item[1] for item in prior_passers)
            total_yards = sum(item[2] for item in prior_passers)
            row["prior_leading_qb_attempts"] = leader_att
            row["prior_leading_qb_attempt_share"] = _ratio(leader_att, total_att)
            row["prior_leading_qb_yards_share"] = _ratio(leader_yards, total_yards)
            row["prior_leading_qb_returns"] = leader in current_ids
            row["qb_continuity_known"] = True

    for part in by_endpoint["player/portal"]:
        season = int(part.parameters.get("year") or 0)
        season_start = first_kickoff.get(season)
        for raw in part.records:
            transfer_at = _parse_datetime(raw.get("transferDate"))
            if transfer_at is None or season_start is None or transfer_at > season_start:
                continue
            rating = _float(raw.get("rating"))
            position = str(raw.get("position") or "").upper()
            for direction, team in (("out", raw.get("origin")), ("in", raw.get("destination"))):
                program_id = mapped(team)
                if program_id is None:
                    continue
                row = fact(program_id, season)
                if not row["portal_available"]:
                    for name in _PORTAL_COUNT_FIELDS:
                        row[name] = 0
                    for name in _PORTAL_SUM_FIELDS:
                        row[name] = 0.0
                row[f"transfer_{direction}_count"] += 1
                if rating is not None:
                    row[f"transfer_{direction}_rating_sum"] += rating
                    row[f"transfer_{direction}_rated_count"] += 1
                group = _position_group(position)
                if group in {"qb", "offense_skill", "offensive_line", "defense"}:
                    row[f"transfer_{direction}_{group}_count"] += 1
                row["portal_available"] = True
                _source(source_meta, program_id, season, part)

    coaches: dict[tuple[str, int], int] = {}
    for part in by_endpoint["coaches"]:
        for raw in part.records:
            coach_id = int(raw.get("id") or 0)
            for season_row in raw.get("seasons") or []:
                season = int(season_row.get("year") or 0)
                program_id = id_map.get(int(season_row.get("teamId") or 0)) or mapped(season_row.get("school"))
                if program_id is None or not start_season <= season <= end_season:
                    continue
                coaches[(program_id, season)] = coach_id
                _source(source_meta, program_id, season, part)
    for (program_id, season), coach_id in coaches.items():
        row = fact(program_id, season)
        previous = coaches.get((program_id, season - 1))
        consecutive = 1
        cursor = season - 1
        while coaches.get((program_id, cursor)) == coach_id:
            consecutive += 1
            cursor -= 1
        row["head_coach_id"] = coach_id
        row["head_coach_change"] = previous is not None and previous != coach_id
        row["head_coach_continuity_known"] = previous is not None
        row["head_coach_tenure_seasons"] = consecutive
        row["coach_available"] = True

    output: list[dict[str, Any]] = []
    for key, row in sorted(facts.items(), key=lambda item: (item[0][1], item[0][0])):
        meta = sorted(source_meta.get(key, set()), key=lambda item: (item[0], item[1]))
        row["source_manifest_ids"] = json.dumps([item[0] for item in meta])
        row["source_content_hashes"] = json.dumps([item[1] for item in meta])
        row["source_endpoints"] = json.dumps(sorted({item[2] for item in meta}))
        row["ingested_at"] = max((item[3] for item in meta), default=None)
        row["source_count"] = len(meta)
        row["missing_family_count"] = sum(
            not bool(row[name])
            for name in (
                "returning_available",
                "recruiting_available",
                "talent_available",
                "roster_available",
                "portal_available",
                "coach_available",
                "qb_continuity_known",
            )
        )
        row["strict_live_fidelity"] = False
        row["reconstructed_source"] = True
        row["availability_policy_version"] = PRESEASON_AVAILABILITY_POLICY_VERSION
        row["feature_set_version"] = PRESEASON_FEATURE_SET_VERSION
        output.append(row)
    table = pa.Table.from_pylist(output)
    report = _coverage_report(output, parts, name_map, start_season, end_season)
    return table, report


def augment_feature_tables(
    base_tables: Mapping[str, pa.Table],
    preseason_facts: pa.Table,
) -> tuple[dict[str, pa.Table], dict[str, Any]]:
    facts = {(str(row["program_id"]), int(row["season"])): row for row in preseason_facts.to_pylist()}
    numeric = tuple(
        field.name
        for field in preseason_facts.schema
        if field.name not in _FACT_METADATA and (
            pa.types.is_integer(field.type) or pa.types.is_floating(field.type) or pa.types.is_boolean(field.type)
        )
    )
    output: dict[str, pa.Table] = {}
    coverage: dict[str, Any] = {}
    for horizon, table in sorted(base_tables.items()):
        rows: list[dict[str, Any]] = []
        available_sides = 0
        for base in table.to_pylist():
            row = dict(base)
            as_of = _utc(row["prediction_as_of"])
            for side in ("home", "away"):
                context = facts.get((str(row[f"{side}_program_id"]), int(row["season"])))
                usable = context is not None and context.get("available_at") is not None and _utc(context["available_at"]) <= as_of
                if usable:
                    available_sides += 1
                for name in numeric:
                    row[f"{side}_preseason_{name}"] = context.get(name) if usable and context else None
                row[f"{side}_preseason_available"] = usable
            for name in numeric:
                home = row.get(f"home_preseason_{name}")
                away = row.get(f"away_preseason_{name}")
                row[f"home_minus_away_preseason_{name}"] = (
                    float(home) - float(away)
                    if home is not None and away is not None and not isinstance(home, bool) and not isinstance(away, bool)
                    else None
                )
            row["preseason_feature_set_version"] = PRESEASON_FEATURE_SET_VERSION
            rows.append(row)
        result = pa.Table.from_pylist(rows)
        output[horizon] = result.sort_by([("kickoff", "ascending"), ("provider_game_id", "ascending")])
        coverage[horizon] = {
            "rows": len(rows),
            "available_team_sides": available_sides,
            "team_side_coverage": available_sides / (2 * len(rows)) if rows else 0.0,
        }
    return output, coverage


def build_preseason_artifacts(
    store: ResearchArtifactStore,
    *,
    parts: Sequence[SourcePart],
    normalized_games: pa.Table,
    base_tables: Mapping[str, pa.Table],
    base_manifest: Mapping[str, Any],
    start_season: int = 2014,
    end_season: int = 2024,
) -> dict[str, Any]:
    facts, source_report = normalize_preseason_facts(
        parts, normalized_games=normalized_games, start_season=start_season, end_season=end_season
    )
    source_manifests = [
        {"id": part.manifest_id, "content_hash": part.content_hash}
        for part in parts
    ]
    artifacts: list[dict[str, Any]] = []
    for season in range(start_season, end_season + 1):
        season_table = facts.filter(pc.equal(facts["season"], season))
        artifact = store.write_parquet(
            season_table,
            namespace="preseason-normalized",
            dataset="team_season_preseason_facts",
            season=season,
            schema_version=PRESEASON_SCHEMA_VERSION,
            transformation_version=PRESEASON_TRANSFORMATION_VERSION,
            source_manifests=source_manifests,
            sort_by=(("program_id", "ascending"),),
        )
        artifacts.append(artifact_dict(artifact))
    augmented, feature_coverage = augment_feature_tables(base_tables, facts)
    for horizon, table in augmented.items():
        artifact = store.write_parquet(
            table,
            namespace="preseason-features",
            dataset="model_ready_games_preseason",
            season=None,
            schema_version=COMBINED_FEATURE_SET_VERSION,
            transformation_version=PRESEASON_EXPERIMENT_VERSION,
            source_manifests=source_manifests,
            sort_by=(("kickoff", "ascending"), ("provider_game_id", "ascending")),
        )
        item = artifact_dict(artifact)
        item["prediction_horizon"] = horizon
        artifacts.append(item)
    configuration = {
        "base_dataset_hash": base_manifest["dataset_hash"],
        "base_feature_set_hash": base_manifest["feature_set_hash"],
        "preseason_feature_set_version": PRESEASON_FEATURE_SET_VERSION,
        "combined_feature_set_version": COMBINED_FEATURE_SET_VERSION,
        "availability_policy_version": PRESEASON_AVAILABILITY_POLICY_VERSION,
        "season_range": [start_season, end_season],
    }
    manifest = {
        **configuration,
        "source_manifest_ids": sorted(part.manifest_id for part in parts),
        "source_content_hashes": sorted(part.content_hash for part in parts),
        "source_report": source_report,
        "feature_coverage": feature_coverage,
        "artifacts": artifacts,
    }
    manifest["preseason_feature_set_hash"] = stable_hash(_feature_contract())
    manifest["dataset_hash"] = dataset_hash(artifacts, configuration)
    manifest_id, path = store.write_manifest("preseason-features", manifest)
    manifest["manifest_id"] = manifest_id
    manifest["manifest_uri"] = path.relative_to(store.root).as_posix()
    return manifest


def validate_preseason_manifest(store: ResearchArtifactStore, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(manifest["season_range"][1]) >= 2025:
        errors.append("locked 2025 holdout appears in preseason manifest")
    for artifact in manifest["artifacts"]:
        errors.extend(store.validate_artifact(artifact))
    if len(set(manifest["source_manifest_ids"])) != len(manifest["source_manifest_ids"]):
        errors.append("duplicate source manifest IDs")
    return errors


_FACT_METADATA = frozenset(
    {
        "program_id", "season", "effective_at", "available_at", "ingested_at",
        "source_manifest_ids", "source_content_hashes", "source_endpoints",
        "availability_policy_version", "feature_set_version",
    }
)


def _empty_fact(program_id: str, season: int, season_start: datetime | None) -> dict[str, Any]:
    return {
        "program_id": program_id,
        "season": season,
        "effective_at": season_start,
        "available_at": season_start,
        "returning_percent_ppa": None,
        "returning_percent_passing_ppa": None,
        "returning_percent_receiving_ppa": None,
        "returning_percent_rushing_ppa": None,
        "returning_usage": None,
        "returning_passing_usage": None,
        "returning_receiving_usage": None,
        "returning_rushing_usage": None,
        "recruiting_rank": None,
        "recruiting_points": None,
        "talent_composite": None,
        "roster_count": None,
        "prior_roster_count": None,
        "roster_returning_count": None,
        "roster_continuity_ratio": None,
        "qb_continuity_ratio": None,
        "offense_skill_continuity_ratio": None,
        "offensive_line_continuity_ratio": None,
        "defense_continuity_ratio": None,
        "prior_leading_qb_attempts": None,
        "prior_leading_qb_attempt_share": None,
        "prior_leading_qb_yards_share": None,
        "prior_leading_qb_returns": None,
        **{name: None for name in _PORTAL_COUNT_FIELDS},
        **{name: None for name in _PORTAL_SUM_FIELDS},
        "head_coach_id": None,
        "head_coach_change": None,
        "head_coach_continuity_known": False,
        "head_coach_tenure_seasons": None,
        "returning_available": False,
        "recruiting_available": False,
        "talent_available": False,
        "roster_available": False,
        "portal_available": False,
        "coach_available": False,
        "qb_continuity_known": False,
    }


_PORTAL_COUNT_FIELDS = (
    "transfer_in_count",
    "transfer_out_count",
    "transfer_in_rated_count",
    "transfer_out_rated_count",
    "transfer_in_qb_count",
    "transfer_out_qb_count",
    "transfer_in_offense_skill_count",
    "transfer_out_offense_skill_count",
    "transfer_in_offensive_line_count",
    "transfer_out_offensive_line_count",
    "transfer_in_defense_count",
    "transfer_out_defense_count",
)

_PORTAL_SUM_FIELDS = (
    "transfer_in_rating_sum",
    "transfer_out_rating_sum",
)


def _feature_contract() -> list[dict[str, Any]]:
    families = {
        "returning": "CFBD returning production percentages and usage",
        "qb": "prior leading passer share and current roster ID continuity",
        "transfers": "dated portal in/out counts and provider rating aggregates",
        "recruiting": "reconstructed team class rank and points",
        "talent": "reconstructed team talent composite",
        "coaching": "head-coach continuity and tenure",
        "roster": "provider-player-ID year-over-year overlap",
        "quality": "coverage, missing-family, and reconstruction indicators",
    }
    return [
        {
            "family": family,
            "description": description,
            "point_in_time_rule": PRESEASON_AVAILABILITY_POLICY_VERSION,
            "version": PRESEASON_FEATURE_SET_VERSION,
        }
        for family, description in sorted(families.items())
    ]


def _coverage_report(
    rows: Sequence[Mapping[str, Any]],
    parts: Sequence[SourcePart],
    name_map: Mapping[str, str],
    start: int,
    end: int,
) -> dict[str, Any]:
    by_season: dict[str, Any] = {}
    for season in range(start, end + 1):
        season_rows = [row for row in rows if int(row["season"]) == season]
        by_season[str(season)] = {
            "team_seasons": len(season_rows),
            **{
                name: sum(bool(row[field]) for row in season_rows)
                for name, field in (
                    ("returning", "returning_available"),
                    ("recruiting", "recruiting_available"),
                    ("talent", "talent_available"),
                    ("roster", "roster_available"),
                    ("portal", "portal_available"),
                    ("coach", "coach_available"),
                    ("qb", "qb_continuity_known"),
                )
            },
        }
    return {
        "version": PRESEASON_SCHEMA_VERSION,
        "season_range": [start, end],
        "team_name_mappings": len(name_map),
        "team_season_rows": len(rows),
        "source_rows": {endpoint: sum(len(part.records) for part in parts if part.endpoint == endpoint) for endpoint in sorted(SOURCE_ENDPOINTS)},
        "source_bytes": {endpoint: sum(part.response_bytes for part in parts if part.endpoint == endpoint) for endpoint in sorted(SOURCE_ENDPOINTS)},
        "by_season": by_season,
        "strict_live_fidelity": False,
        "coordinator_features": "deferred_no_structured_cfbd_history",
    }


def _source(
    meta: dict[tuple[str, int], set[tuple[str, str, str, datetime]]],
    program_id: str,
    season: int,
    part: SourcePart,
) -> None:
    meta[(program_id, season)].add((part.manifest_id, part.content_hash, part.endpoint, _utc(part.retrieved_at)))


def _position_group(position: str) -> str:
    return POSITION_GROUPS.get(position.upper(), "other")


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("preseason timestamps must be timezone-aware")
    return value.astimezone(UTC)
