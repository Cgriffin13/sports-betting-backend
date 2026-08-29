from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from statistics import fmean
from typing import Any

import pyarrow as pa

from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash
from app.research.ncaaf.contracts import (
    AVAILABILITY_POLICY_VERSION,
    DATASET_SCHEMA_VERSION,
    EARLY_SEASON_PRIOR_VERSION,
    FEATURE_SET_VERSION,
    FOLD_POLICY_VERSION,
    MORNING_TIMEZONE,
    MorningPolicy,
    OPPONENT_ADJUSTMENT_VERSION,
    PredictionHorizon,
    chronological_folds,
    feature_set_hash,
    fold_role,
    prediction_as_of,
)
from app.research.ncaaf.feature_registry import METRICS, feature_definitions

TEAM_GAME_SCHEMA_VERSION = "ncaaf-team-game-metrics-v1"
TEAM_GAME_TRANSFORMATION_VERSION = "cfbd-play-drive-aggregation-v1"
MIN_PRIOR_STRENGTH_GAMES = 1
PRIOR_PSEUDO_GAMES = 3.0

PASS_TYPES = frozenset(
    {
        "Pass Reception",
        "Pass Incompletion",
        "Passing Touchdown",
        "Sack",
        "Pass Interception Return",
        "Interception",
        "Interception Return Touchdown",
        "Two Point Pass",
    }
)
RUSH_TYPES = frozenset({"Rush", "Rushing Touchdown", "Two Point Rush"})
HAVOC_TYPES = frozenset(
    {
        "Sack",
        "Pass Interception Return",
        "Interception",
        "Interception Return Touchdown",
        "Fumble Recovery (Opponent)",
        "Fumble Return Touchdown",
    }
)


@dataclass(slots=True)
class Accumulator:
    off_ppa: list[float] = field(default_factory=list)
    def_ppa_allowed: list[float] = field(default_factory=list)
    pass_ppa: list[float] = field(default_factory=list)
    rush_ppa: list[float] = field(default_factory=list)
    successes: int = 0
    explosives: int = 0
    yards: int = 0
    offensive_plays: int = 0
    defensive_plays: int = 0
    havoc: int = 0
    drives: int = 0
    drive_yards: int = 0
    drive_points: int = 0
    wallclock_present: int = 0
    team_stats_present: bool = False


@dataclass(frozen=True, slots=True)
class TeamGameMetric:
    provider_game_id: int
    season: int
    week: int | None
    kickoff: datetime
    available_at: datetime
    program_id: str
    opponent_program_id: str
    is_home: bool
    metrics: Mapping[str, float | None]
    play_rows: int
    drive_rows: int
    wallclock_coverage: float | None
    team_stats_present: bool
    reconstructed_source: bool = True


def aggregate_team_games(
    games: Sequence[Mapping[str, Any]],
    plays: Iterable[Mapping[str, Any]],
    drives: Iterable[Mapping[str, Any]],
    team_stats: Iterable[Mapping[str, Any]],
) -> list[TeamGameMetric]:
    game_map = {int(game["provider_game_id"]): game for game in games}
    accumulators: dict[tuple[int, str], Accumulator] = defaultdict(Accumulator)
    for game in games:
        game_id = int(game["provider_game_id"])
        for key in ("home_program_id", "away_program_id"):
            if game.get(key):
                accumulators[(game_id, str(game[key]))]
    for play in plays:
        if not play.get("identity_resolved"):
            continue
        game_id = int(play["provider_game_id"])
        offense = str(play["offense_program_id"])
        defense = str(play["defense_program_id"])
        play_type = str(play.get("play_type") or "")
        if play_type not in PASS_TYPES | RUSH_TYPES:
            continue
        value = _finite(play.get("ppa"))
        yards = int(play.get("yards_gained") or 0)
        success = _success(play.get("down"), play.get("distance"), yards)
        offense_acc = accumulators[(game_id, offense)]
        defense_acc = accumulators[(game_id, defense)]
        offense_acc.offensive_plays += 1
        offense_acc.yards += yards
        offense_acc.wallclock_present += int(bool(play.get("wallclock")))
        defense_acc.defensive_plays += 1
        if value is not None:
            offense_acc.off_ppa.append(value)
            defense_acc.def_ppa_allowed.append(value)
            if play_type in PASS_TYPES:
                offense_acc.pass_ppa.append(value)
            if play_type in RUSH_TYPES:
                offense_acc.rush_ppa.append(value)
        offense_acc.successes += int(success)
        explosive = (play_type in PASS_TYPES and yards >= 20) or (play_type in RUSH_TYPES and yards >= 10)
        offense_acc.explosives += int(explosive)
        defense_acc.havoc += int(play_type in HAVOC_TYPES)
    for drive in drives:
        if not drive.get("identity_resolved") or not drive.get("offense_program_id"):
            continue
        acc = accumulators[(int(drive["provider_game_id"]), str(drive["offense_program_id"]))]
        acc.drives += 1
        acc.drive_yards += int(drive.get("yards") or 0)
        acc.drive_points += int(drive.get("points") or 0)
    for stat in team_stats:
        if stat.get("program_id"):
            accumulators[(int(stat["provider_game_id"]), str(stat["program_id"]))].team_stats_present = True

    results: list[TeamGameMetric] = []
    for (game_id, program_id), acc in sorted(accumulators.items()):
        candidate_game = game_map.get(game_id)
        if candidate_game is None:
            continue
        game = candidate_game
        home = str(game.get("home_program_id") or "")
        away = str(game.get("away_program_id") or "")
        if program_id not in {home, away} or not home or not away:
            continue
        opponent = away if program_id == home else home
        is_home = program_id == home
        own = acc
        results.append(
            TeamGameMetric(
                provider_game_id=game_id,
                season=int(game["season"]),
                week=_integer(game.get("week")),
                kickoff=_timestamp(game["kickoff"]),
                available_at=_timestamp(game["available_at"]),
                program_id=program_id,
                opponent_program_id=opponent,
                is_home=is_home,
                metrics={
                    "off_ppa": _mean(own.off_ppa),
                    "def_ppa_allowed": _mean(own.def_ppa_allowed),
                    "pass_ppa": _mean(own.pass_ppa),
                    "rush_ppa": _mean(own.rush_ppa),
                    "success_rate": _ratio(own.successes, own.offensive_plays),
                    "explosive_rate": _ratio(own.explosives, own.offensive_plays),
                    "yards_per_play": _ratio(own.yards, own.offensive_plays),
                    "yards_per_drive": _ratio(own.drive_yards, own.drives),
                    "points_per_drive": _ratio(own.drive_points, own.drives),
                    "plays_per_game": float(own.offensive_plays) if own.offensive_plays else None,
                    "drives_per_game": float(own.drives) if own.drives else None,
                    "havoc_rate": _ratio(own.havoc, own.defensive_plays),
                },
                play_rows=own.offensive_plays,
                drive_rows=own.drives,
                wallclock_coverage=_ratio(own.wallclock_present, own.offensive_plays),
                team_stats_present=own.team_stats_present,
            )
        )
    return results


def _success(down: Any, distance: Any, yards: int) -> bool:
    try:
        down_i = int(down)
        distance_i = int(distance)
    except (TypeError, ValueError):
        return False
    if distance_i <= 0:
        return yards >= 0
    threshold = 0.5 if down_i == 1 else 0.7 if down_i == 2 else 1.0
    return yards >= math.ceil(distance_i * threshold)


class PointInTimeFeatureBuilder:
    def __init__(self, store: ResearchArtifactStore, normalized_manifest: Mapping[str, Any]) -> None:
        self.store = store
        self.normalized_manifest = normalized_manifest

    def build(
        self,
        start_season: int,
        end_season: int,
        *,
        horizons: Sequence[PredictionHorizon],
        morning_policy: MorningPolicy,
    ) -> dict[str, Any]:
        games = self._read("games", start_season, end_season)
        team_games: list[TeamGameMetric] = []
        metric_artifacts: list[dict[str, Any]] = []
        for season in range(start_season, end_season + 1):
            season_games = [game for game in games if int(game["season"]) == season]
            metrics = aggregate_team_games(
                season_games,
                self._read(
                    "plays",
                    season,
                    season,
                    columns=(
                        "provider_game_id",
                        "offense_program_id",
                        "defense_program_id",
                        "identity_resolved",
                        "play_type",
                        "ppa",
                        "yards_gained",
                        "down",
                        "distance",
                        "wallclock",
                    ),
                ),
                self._read(
                    "drives",
                    season,
                    season,
                    columns=(
                        "provider_game_id",
                        "offense_program_id",
                        "defense_program_id",
                        "identity_resolved",
                        "yards",
                        "points",
                    ),
                ),
                self._read("team_game_statistics", season, season, columns=("provider_game_id", "program_id")),
            )
            team_games.extend(metrics)
            table = team_game_table(metrics)
            source_artifacts = [
                item
                for item in self.normalized_manifest["artifacts"]
                if item.get("season") == season
                and item["dataset"] in {"games", "plays", "drives", "team_game_statistics"}
            ]
            artifact = self.store.write_parquet(
                table,
                namespace="features",
                dataset="team_game_metrics",
                season=season,
                schema_version=TEAM_GAME_SCHEMA_VERSION,
                transformation_version=TEAM_GAME_TRANSFORMATION_VERSION,
                source_manifests=[
                    {"id": item["content_hash"], "content_hash": item["content_hash"]} for item in source_artifacts
                ],
                sort_by=(("available_at", "ascending"), ("provider_game_id", "ascending"), ("program_id", "ascending")),
            )
            metric_artifacts.append(artifact_dict(artifact))

        eligible = [
            game
            for game in games
            if bool(game.get("model_eligible"))
            and int(game["season"]) >= start_season
            and int(game["season"]) <= end_season
        ]
        definitions = feature_definitions()
        feature_hash = feature_set_hash(definitions)
        source_inputs = [
            {"id": item["content_hash"], "content_hash": item["content_hash"]}
            for item in self.normalized_manifest["artifacts"]
        ]
        feature_artifacts: list[dict[str, Any]] = []
        total_rows = 0
        for horizon in sorted(horizons, key=str):
            rows = build_feature_rows(
                eligible,
                team_games,
                horizons=(horizon,),
                morning_policy=morning_policy,
                source_corpus_version=str(self.normalized_manifest["dataset_hash"]),
                feature_hash=feature_hash,
            )
            total_rows += len(rows)
            feature_artifact = self.store.write_parquet(
                feature_table(rows),
                namespace="features",
                dataset="model_ready_games",
                season=None,
                schema_version=DATASET_SCHEMA_VERSION,
                transformation_version=FEATURE_SET_VERSION,
                source_manifests=source_inputs,
                sort_by=(("season", "ascending"), ("kickoff", "ascending"), ("provider_game_id", "ascending")),
            )
            feature_artifact_dict = artifact_dict(feature_artifact)
            feature_artifact_dict["prediction_horizon"] = str(horizon)
            feature_artifacts.append(feature_artifact_dict)
            del rows
        artifacts = [*metric_artifacts, *feature_artifacts]
        configuration = {
            "league": "NCAAF",
            "start_season": start_season,
            "end_season": end_season,
            "horizons": sorted(str(item) for item in horizons),
            "morning_policy": str(morning_policy),
            "feature_set_version": FEATURE_SET_VERSION,
            "feature_set_hash": feature_hash,
            "availability_policy_version": AVAILABILITY_POLICY_VERSION,
            "opponent_adjustment_version": OPPONENT_ADJUSTMENT_VERSION,
            "early_season_prior_version": EARLY_SEASON_PRIOR_VERSION,
            "fold_policy_version": FOLD_POLICY_VERSION,
            "normalized_dataset_hash": self.normalized_manifest["dataset_hash"],
        }
        manifest: dict[str, Any] = {
            **configuration,
            "artifacts": artifacts,
            "dataset_hash": dataset_hash(artifacts, configuration),
            "row_count": total_rows,
            "eligible_game_count": len(eligible),
            "excluded_game_count": len(games) - len(eligible),
            "folds": [asdict(item) for item in chronological_folds()],
            "feature_definitions": [asdict(item) for item in definitions],
            "network_calls": 0,
        }
        manifest_id, _ = self.store.write_manifest("features", manifest)
        manifest["manifest_id"] = manifest_id
        return manifest

    def _read(
        self, dataset: str, start: int, end: int, *, columns: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for artifact in self.normalized_manifest["artifacts"]:
            season = artifact.get("season")
            if artifact["dataset"] == dataset and season is not None and start <= int(season) <= end:
                rows.extend(self.store.read_table(artifact["uri"], columns=columns).to_pylist())
        return rows


def build_feature_rows(
    games: Sequence[Mapping[str, Any]],
    team_games: Sequence[TeamGameMetric],
    *,
    horizons: Sequence[PredictionHorizon],
    morning_policy: MorningPolicy,
    source_corpus_version: str = "synthetic-or-unspecified",
    feature_hash: str | None = None,
) -> list[dict[str, Any]]:
    first_by_day: dict[str, datetime] = {}
    for game in games:
        kickoff = _timestamp(game["kickoff"])
        day = kickoff.astimezone(MORNING_TIMEZONE).date().isoformat()
        first_by_day[day] = min(kickoff, first_by_day.get(day, kickoff))
    requests: list[tuple[datetime, Mapping[str, Any], PredictionHorizon]] = []
    for game in games:
        kickoff = _timestamp(game["kickoff"])
        slate_day = kickoff.astimezone(MORNING_TIMEZONE).date().isoformat()
        for horizon in horizons:
            as_of = prediction_as_of(
                kickoff,
                horizon,
                first_kickoff_of_day=first_by_day[slate_day],
                morning_policy=morning_policy,
            )
            requests.append((as_of, game, horizon))
    requests.sort(key=lambda item: (item[0], int(item[1]["provider_game_id"]), str(item[2])))
    available = sorted(team_games, key=lambda item: (item.available_at, item.provider_game_id, item.program_id))
    state: dict[str, list[TeamGameMetric]] = defaultdict(list)
    team_totals: dict[str, dict[str, tuple[float, int]]] = defaultdict(dict)
    population: dict[str, tuple[float, int]] = {}
    cursor = 0
    rows: list[dict[str, Any]] = []
    for as_of, game, horizon in requests:
        while cursor < len(available) and available[cursor].available_at <= as_of:
            record = available[cursor]
            state[record.program_id].append(record)
            for metric, value in record.metrics.items():
                if value is not None:
                    total, count = population.get(metric, (0.0, 0))
                    population[metric] = (total + value, count + 1)
                    team_total, team_count = team_totals[record.program_id].get(metric, (0.0, 0))
                    team_totals[record.program_id][metric] = (team_total + value, team_count + 1)
            cursor += 1
        rows.append(
            _feature_row(
                game,
                horizon,
                as_of,
                state,
                team_totals,
                population,
                morning_policy,
                source_corpus_version,
                feature_hash or feature_set_hash(feature_definitions()),
            )
        )
    return sorted(
        rows, key=lambda row: (row["season"], row["kickoff"], row["provider_game_id"], row["prediction_horizon"])
    )


def _feature_row(
    game: Mapping[str, Any],
    horizon: PredictionHorizon,
    as_of: datetime,
    state: Mapping[str, list[TeamGameMetric]],
    team_totals: Mapping[str, Mapping[str, tuple[float, int]]],
    population: Mapping[str, tuple[float, int]],
    morning_policy: MorningPolicy,
    source_corpus_version: str,
    feature_hash: str,
) -> dict[str, Any]:
    season = int(game["season"])
    home = str(game["home_program_id"])
    away = str(game["away_program_id"])
    row: dict[str, Any] = {
        "canonical_event_id": game.get("canonical_event_id"),
        "provider_game_id": int(game["provider_game_id"]),
        "season": season,
        "week": _integer(game.get("week")),
        "kickoff": _timestamp(game["kickoff"]),
        "prediction_as_of": as_of,
        "prediction_horizon": str(horizon),
        "morning_policy": str(morning_policy) if horizon == PredictionHorizon.GAME_DAY_MORNING else None,
        "home_program_id": home,
        "away_program_id": away,
        "neutral_site": game.get("neutral_site"),
        "home_conference": game.get("home_conference"),
        "away_conference": game.get("away_conference"),
        "home_classification": game.get("home_classification"),
        "away_classification": game.get("away_classification"),
        "conference_game": game.get("conference_game"),
        "venue_id": game.get("venue_id"),
        "postseason": game.get("postseason"),
        "covid_2020_regime": season == 2020,
        "target_margin": game.get("target_margin"),
        "target_total": game.get("target_total"),
        "feature_set_version": FEATURE_SET_VERSION,
        "feature_set_hash": feature_hash,
        "source_corpus_version": source_corpus_version,
        "availability_policy_version": AVAILABILITY_POLICY_VERSION,
        "opponent_adjustment_version": OPPONENT_ADJUSTMENT_VERSION,
        "early_season_prior_version": EARLY_SEASON_PRIOR_VERSION,
        "fold_role": fold_role(season),
    }
    side_summaries: dict[str, dict[str, float | None]] = {}
    for side, program in (("home", home), ("away", away)):
        history = [
            record
            for record in state.get(program, [])
            if record.available_at <= as_of and record.provider_game_id != int(game["provider_game_id"])
        ]
        current = [record for record in history if record.season == season]
        prior = [record for record in history if season - 3 <= record.season < season]
        row[f"{side}_prior_games_available"] = len(history)
        row[f"{side}_current_season_games"] = len(current)
        row[f"{side}_pbp_games_available"] = sum(record.play_rows > 0 for record in history)
        row[f"{side}_drive_games_available"] = sum(record.drive_rows > 0 for record in history)
        row[f"{side}_team_stat_games_available"] = sum(record.team_stats_present for record in history)
        row[f"{side}_pbp_coverage_ratio"] = _ratio(sum(record.play_rows > 0 for record in history), len(history))
        row[f"{side}_drive_coverage_ratio"] = _ratio(sum(record.drive_rows > 0 for record in history), len(history))
        row[f"{side}_team_stat_coverage_ratio"] = _ratio(
            sum(record.team_stats_present for record in history), len(history)
        )
        row[f"{side}_wallclock_coverage"] = _mean(
            [record.wallclock_coverage for record in history if record.wallclock_coverage is not None]
        )
        row[f"{side}_reconstructed_source"] = any(record.reconstructed_source for record in history)
        row[f"{side}_opponent_adjustment_available"] = bool(
            current and all(record.opponent_program_id in state for record in current[-5:])
        )
        row[f"{side}_rest_days"] = (
            None if not history else (_timestamp(game["kickoff"]) - history[-1].kickoff).total_seconds() / 86400
        )
        current_weight = len(current) / (len(current) + PRIOR_PSEUDO_GAMES)
        row[f"{side}_current_weight"] = current_weight
        row[f"{side}_prior_weight"] = 1.0 - current_weight
        summary: dict[str, float | None] = {}
        for metric in METRICS:
            values = [record.metrics.get(metric) for record in history]
            clean = [float(value) for value in values if value is not None]
            current_values = _metric_values(current, metric)
            prior_values = _metric_values(prior, metric)
            population_mean = _population_mean(population, metric)
            prior_mean = _mean(prior_values)
            if prior_mean is None:
                prior_mean = population_mean
            current_mean = _mean(current_values)
            blended = (
                prior_mean
                if current_mean is None
                else current_mean
                if prior_mean is None
                else current_weight * current_mean + (1 - current_weight) * prior_mean
            )
            row[f"{side}_{metric}_last3"] = _mean(clean[-3:])
            row[f"{side}_{metric}_last5"] = _mean(clean[-5:])
            row[f"{side}_{metric}_season"] = current_mean
            row[f"{side}_{metric}_prior"] = prior_mean
            row[f"{side}_{metric}_blended"] = blended
            summary[metric] = blended
        for metric in ("off_ppa", "def_ppa_allowed", "success_rate", "yards_per_play"):
            raw = row[f"{side}_{metric}_last5"]
            opponent_metric = (
                "def_ppa_allowed" if metric == "off_ppa" else "off_ppa" if metric == "def_ppa_allowed" else metric
            )
            opponent_values: list[float] = []
            for record in current[-5:]:
                value = _team_mean(team_totals, record.opponent_program_id, opponent_metric)
                if value is not None:
                    opponent_values.append(value)
            schedule_strength = _mean(opponent_values)
            population_mean = _population_mean(population, opponent_metric)
            adjusted = (
                None
                if raw is None or schedule_strength is None or population_mean is None
                else float(raw) - schedule_strength + population_mean
            )
            row[f"{side}_{metric}_opponent_adjusted"] = adjusted
        side_summaries[side] = summary
    for metric in METRICS:
        home_value = side_summaries["home"].get(metric)
        away_value = side_summaries["away"].get(metric)
        row[f"home_minus_away_{metric}"] = None if home_value is None or away_value is None else home_value - away_value
    return row


def team_game_table(records: Sequence[TeamGameMetric]) -> pa.Table:
    rows = []
    for record in records:
        row = {key: value for key, value in asdict(record).items() if key != "metrics"}
        row.update(record.metrics)
        rows.append(row)
    return pa.Table.from_pylist(rows)


def feature_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    table = pa.Table.from_pylist(list(rows))
    index = table.schema.get_field_index("morning_policy")
    if index >= 0 and pa.types.is_null(table.schema.field(index).type):
        table = table.set_column(index, "morning_policy", pa.array([None] * table.num_rows, type=pa.string()))
    return table


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return fmean(clean) if clean else None


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return None if not denominator else float(numerator) / float(denominator)


def _metric_values(records: Iterable[TeamGameMetric], metric: str) -> list[float]:
    values: list[float] = []
    for record in records:
        value = record.metrics.get(metric)
        if value is not None:
            values.append(float(value))
    return values


def _population_mean(population: Mapping[str, tuple[float, int]], metric: str) -> float | None:
    total, count = population.get(metric, (0.0, 0))
    return None if count == 0 else total / count


def _team_mean(
    team_totals: Mapping[str, Mapping[str, tuple[float, int]]], program_id: str, metric: str
) -> float | None:
    total, count = team_totals.get(program_id, {}).get(metric, (0.0, 0))
    return None if count == 0 else total / count


def _integer(value: Any) -> int | None:
    return None if value is None else int(value)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
