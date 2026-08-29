from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

import pyarrow as pa

from app.research.ncaaf.artifacts import ResearchArtifactStore

REPORT_VERSION = "ncaaf-feature-dataset-report-v1"

FAMILIES = {
    "epa": (
        "home_off_ppa_blended",
        "away_off_ppa_blended",
        "home_def_ppa_allowed_blended",
        "away_def_ppa_allowed_blended",
    ),
    "success_explosiveness": (
        "home_success_rate_blended",
        "away_success_rate_blended",
        "home_explosive_rate_blended",
        "away_explosive_rate_blended",
    ),
    "yards": ("home_yards_per_play_blended", "away_yards_per_play_blended"),
    "drives": (
        "home_yards_per_drive_blended",
        "away_yards_per_drive_blended",
        "home_points_per_drive_blended",
        "away_points_per_drive_blended",
    ),
    "pace": (
        "home_plays_per_game_blended",
        "away_plays_per_game_blended",
        "home_drives_per_game_blended",
        "away_drives_per_game_blended",
    ),
    "opponent_adjustment": (
        "home_off_ppa_opponent_adjusted",
        "away_off_ppa_opponent_adjusted",
        "home_def_ppa_allowed_opponent_adjusted",
        "away_def_ppa_allowed_opponent_adjusted",
    ),
}


def feature_dataset_report(
    store: ResearchArtifactStore,
    normalized_manifest: Mapping[str, Any],
    feature_manifest: Mapping[str, Any],
    *,
    run_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    feature_tables = [
        store.read_table(item["uri"])
        for item in feature_manifest["artifacts"]
        if item["dataset"] == "model_ready_games"
    ]
    table = pa.concat_tables(feature_tables, promote_options="default")
    metadata_columns = [
        "season",
        "week",
        "prediction_horizon",
        "home_current_season_games",
        "away_current_season_games",
        "home_pbp_coverage_ratio",
        "away_pbp_coverage_ratio",
        "home_drive_coverage_ratio",
        "away_drive_coverage_ratio",
        "home_team_stat_coverage_ratio",
        "away_team_stat_coverage_ratio",
        "home_opponent_adjustment_available",
        "away_opponent_adjustment_available",
        "covid_2020_regime",
    ]
    rows = table.select(metadata_columns).to_pylist()
    by_season = Counter(int(row["season"]) for row in rows)
    by_horizon = Counter(str(row["prediction_horizon"]) for row in rows)
    early_depth: Counter[str] = Counter()
    for row in rows:
        if row["week"] is not None and int(row["week"]) <= 3:
            for side in ("home", "away"):
                count = int(row[f"{side}_current_season_games"])
                early_depth[str(min(count, 4)) if count < 4 else "4_plus"] += 1
    family_coverage: dict[str, dict[str, float | int]] = {}
    for family, columns in FAMILIES.items():
        total = table.num_rows * len(columns)
        present = sum(table[column].length() - table[column].null_count for column in columns)
        family_coverage[family] = {
            "present_cells": present,
            "total_cells": total,
            "coverage_fraction": round(present / total, 6) if total else 0.0,
            "missing_cells": total - present,
        }
    games = _normalized_games(store, normalized_manifest)
    exclusions = Counter(str(row.get("exclusion_reason") or "eligible") for row in games)
    normalized_bytes = sum(int(item["stored_bytes"]) for item in normalized_manifest["artifacts"])
    feature_bytes = sum(int(item["stored_bytes"]) for item in feature_manifest["artifacts"])
    opponent_rows = sum(
        bool(row["home_opponent_adjustment_available"]) and bool(row["away_opponent_adjustment_available"])
        for row in rows
    )
    quality = {
        key: round(sum(float(row[key] or 0.0) for row in rows) / len(rows), 6) if rows else 0.0
        for key in (
            "home_pbp_coverage_ratio",
            "away_pbp_coverage_ratio",
            "home_drive_coverage_ratio",
            "away_drive_coverage_ratio",
            "home_team_stat_coverage_ratio",
            "away_team_stat_coverage_ratio",
        )
    }
    return {
        "report_version": REPORT_VERSION,
        "feature_manifest_id": feature_manifest["manifest_id"],
        "dataset_hash": feature_manifest["dataset_hash"],
        "feature_set_version": feature_manifest["feature_set_version"],
        "feature_set_hash": feature_manifest["feature_set_hash"],
        "normalized_manifest_id": normalized_manifest["manifest_id"],
        "normalized_dataset_hash": normalized_manifest["dataset_hash"],
        "target_rows": table.num_rows,
        "eligible_games": feature_manifest["eligible_game_count"],
        "rows_by_season": dict(sorted(by_season.items())),
        "rows_by_horizon": dict(sorted(by_horizon.items())),
        "fbs_vs_fbs_games": feature_manifest["eligible_game_count"],
        "excluded_rows_by_reason": dict(sorted(exclusions.items())),
        "feature_family_coverage": family_coverage,
        "quality_mean_ratios": quality,
        "early_season_current_game_depth": dict(sorted(early_depth.items())),
        "opponent_adjustment_rows_both_sides": opponent_rows,
        "opponent_adjustment_coverage_fraction": round(opponent_rows / len(rows), 6) if rows else 0.0,
        "regime_2020_rows": sum(bool(row["covid_2020_regime"]) for row in rows),
        "normalized_artifact_bytes": normalized_bytes,
        "feature_artifact_bytes": feature_bytes,
        "build_runtime_seconds": None if run_report is None else run_report.get("elapsed_seconds"),
        "peak_rss_bytes": None if run_report is None else run_report.get("peak_rss_bytes"),
        "historical_provider_calls": 0,
        "predictive_performance": "not_applicable_no_model_trained",
    }


def _normalized_games(store: ResearchArtifactStore, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] == "games":
            rows.extend(store.read_table(artifact["uri"], columns=("exclusion_reason", "model_eligible")).to_pylist())
    return rows
