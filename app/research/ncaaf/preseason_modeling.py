from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import ResearchArtifactStore, schema_hash, table_content_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.modeling import (
    FrozenFold,
    _model_parameters,
    elo_predictions,
    feature_columns,
    fit_predict_fold,
    frozen_folds,
    make_pipeline,
    metrics,
    paired_season_bootstrap,
)
from app.research.ncaaf.preseason import PRESEASON_EXPERIMENT_VERSION
from app.research.ncaaf.strong_models import fit_predict_tree_fold

PRESEASON_MODEL_VERSION = "ncaaf-preseason-models-v1"
POWER_PRIOR_VERSION = "ncaaf-margin-power-preseason-prior-v1"
RIDGE_ALPHA = 100.0
POWER_PRIOR_ALPHA = 10.0
POWER_PRIOR_CAP = 7.5
CATBOOST_CONFIG: dict[str, Any] = {
    "name": "conservative",
    "n_estimators": 500,
    "learning_rate": 0.03,
    "max_depth": 3,
    "min_child_samples": 20,
    "row_subsample": 0.85,
    "feature_subsample": 0.85,
    "l2": 15.0,
    "num_leaves": 15,
}

FAMILY_TOKENS: dict[str, tuple[str, ...]] = {
    "returning": ("returning_",),
    "qb": ("leading_qb", "qb_continuity"),
    "transfers": ("transfer_",),
    "recruiting_talent": ("recruiting_", "talent_"),
    "coaching": ("head_coach_",),
    "roster": ("roster_", "offense_skill_continuity", "offensive_line_continuity", "defense_continuity"),
    "quality": ("available", "missing_family", "reconstructed", "strict_live", "source_count"),
}


def load_preseason_tables(store: ResearchArtifactStore, manifest: Mapping[str, Any]) -> dict[str, pa.Table]:
    tables: dict[str, pa.Table] = {}
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] != "model_ready_games_preseason":
            continue
        horizon = str(artifact["prediction_horizon"])
        table = store.read_table(str(artifact["uri"]))
        if table.num_rows and max(int(value) for value in table["season"].to_pylist()) >= 2025:
            raise ValueError("locked 2025 holdout cannot enter preseason modeling")
        tables[horizon] = table
    if set(tables) != set(manifest["feature_coverage"]):
        raise ValueError("preseason horizon artifacts do not match the manifest")
    return tables


def preseason_feature_columns(table: pa.Table, *, exclude_family: str | None = None) -> tuple[str, ...]:
    columns = []
    for field in table.schema:
        if "preseason_" not in field.name:
            continue
        if field.name.endswith("head_coach_id") or field.name.endswith("feature_set_version"):
            continue
        if not (pa.types.is_integer(field.type) or pa.types.is_floating(field.type) or pa.types.is_boolean(field.type)):
            continue
        if exclude_family is not None and any(token in field.name for token in FAMILY_TOKENS[exclude_family]):
            continue
        columns.append(field.name)
    return tuple(sorted(columns))


def combined_columns(table: pa.Table, target: str, *, exclude_family: str | None = None) -> tuple[str, ...]:
    variant = "full_v1" if target == "target_margin" else "full_without_opponent_adjustment"
    base = tuple(name for name in feature_columns(table, variant) if "preseason_" not in name)
    return tuple(sorted({*base, *preseason_feature_columns(table, exclude_family=exclude_family)}))


def run_preseason_experiment(
    store: ResearchArtifactStore,
    manifest: Mapping[str, Any],
    *,
    baseline_predictions_path: Path,
    output_root: Path,
    selected_horizons: Sequence[str] = (),
    include_catboost: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    tables = load_preseason_tables(store, manifest)
    if selected_horizons:
        unknown = set(selected_horizons) - set(tables)
        if unknown:
            raise ValueError(f"unknown horizons: {sorted(unknown)}")
        tables = {name: table for name, table in tables.items() if name in selected_horizons}
    baseline = pq.ParquetFile(baseline_predictions_path).read().to_pylist()
    folds = frozen_folds()
    predictions: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    ablations: dict[str, Any] = {}

    for horizon, table in sorted(tables.items()):
        elo_all = np.asarray(elo_predictions(table.to_pylist()), dtype=float)
        for target in ("target_margin", "target_total"):
            columns = combined_columns(table, target)
            for fold in folds:
                predicted, artifact = fit_predict_fold(
                    table,
                    fold,
                    target,
                    "ridge",
                    {"alpha": RIDGE_ALPHA},
                    columns,
                )
                artifacts.append({**artifact, "variant": "preseason_full", "horizon": horizon})
                predictions.extend(
                    _rows(table, fold, target, predicted, "ridge", "preseason_full", manifest)
                )

            if target == "target_margin":
                prior_columns = preseason_feature_columns(table)
                for fold in folds:
                    predicted, artifact = _fit_power_prior(table, fold, prior_columns, elo_all)
                    artifacts.append({**artifact, "variant": POWER_PRIOR_VERSION, "horizon": horizon})
                    predictions.extend(
                        _rows(table, fold, target, predicted, "power", POWER_PRIOR_VERSION, manifest)
                    )
            elif include_catboost:
                for fold in folds:
                    predicted, artifact = fit_predict_tree_fold(
                        table,
                        fold,
                        target,
                        "catboost",
                        CATBOOST_CONFIG,
                        columns,
                    )
                    artifacts.append({**artifact, "variant": "preseason_full", "horizon": horizon})
                    predictions.extend(
                        _rows(table, fold, target, predicted, "catboost", "preseason_full", manifest)
                    )

        if horizon == "24_hours_before_kickoff":
            for target in ("target_margin", "target_total"):
                ablations[target] = {}
                for family in FAMILY_TOKENS:
                    columns = combined_columns(table, target, exclude_family=family)
                    family_rows: list[dict[str, Any]] = []
                    for fold in folds:
                        predicted, _ = fit_predict_fold(
                            table, fold, target, "ridge", {"alpha": RIDGE_ALPHA}, columns
                        )
                        family_rows.extend(
                            _rows(table, fold, target, predicted, "ridge", f"without_{family}", manifest)
                        )
                    ablations[target][family] = _segments(family_rows)

    prediction_table = pa.Table.from_pylist(
        sorted(
            predictions,
            key=lambda row: (
                row["horizon"], row["target"], row["model_family"], row["variant"],
                row["kickoff"], row["provider_game_id"],
            ),
        )
    )
    output_root.mkdir(parents=True, exist_ok=True)
    prediction_path = output_root / "oof_preseason_predictions.parquet"
    pq.write_table(prediction_table, prediction_path, compression="zstd", compression_level=9)
    report = _build_report(predictions, baseline, ablations)
    deterministic = {
        "experiment_version": PRESEASON_EXPERIMENT_VERSION,
        "model_version": PRESEASON_MODEL_VERSION,
        "input_manifest_id": manifest["manifest_id"],
        "input_dataset_hash": manifest["dataset_hash"],
        "preseason_feature_set_hash": manifest["preseason_feature_set_hash"],
        "base_dataset_hash": manifest["base_dataset_hash"],
        "base_feature_set_hash": manifest["base_feature_set_hash"],
        "folds": [fold.fold_id for fold in folds],
        "ridge_alpha": RIDGE_ALPHA,
        "power_prior_alpha": POWER_PRIOR_ALPHA,
        "power_prior_cap": POWER_PRIOR_CAP,
        "catboost_config": CATBOOST_CONFIG if include_catboost else None,
        "horizons": sorted(tables),
        "prediction_rows": prediction_table.num_rows,
        "prediction_content_hash": table_content_hash(prediction_table),
        "prediction_file_hash": _file_hash(prediction_path),
        "prediction_schema_hash": schema_hash(prediction_table.schema),
        "model_artifact_hash": stable_hash(artifacts),
        "report": report,
        "holdout_accessed": False,
        "provider_calls": 0,
    }
    deterministic["run_hash"] = stable_hash(deterministic)
    deterministic["elapsed_seconds"] = time.perf_counter() - started
    (output_root / "run_manifest.json").write_text(
        json.dumps(deterministic, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return deterministic


def _fit_power_prior(
    table: pa.Table,
    fold: FrozenFold,
    columns: Sequence[str],
    elo_all: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    seasons = np.asarray(table["season"].to_pylist(), dtype=int)
    train_idx = np.where((seasons >= fold.train_start) & (seasons <= fold.train_end))[0]
    evaluation_idx = np.where(seasons == fold.evaluation_season)[0]
    target = np.asarray(table["target_margin"].to_pylist(), dtype=float)
    matrix = _matrix(table, columns)
    pipeline = make_pipeline("ridge", {"alpha": POWER_PRIOR_ALPHA})
    pipeline.fit(matrix[train_idx], target[train_idx] - elo_all[train_idx])
    adjustment = np.clip(pipeline.predict(matrix[evaluation_idx]), -POWER_PRIOR_CAP, POWER_PRIOR_CAP)
    artifact = {
        "model_family": "power",
        "model_version": POWER_PRIOR_VERSION,
        "fold_id": fold.fold_id,
        "training_cutoff": fold.train_end,
        "training_rows": len(train_idx),
        "feature_count": len(columns),
        "feature_columns_hash": stable_hash(list(columns)),
        "alpha": POWER_PRIOR_ALPHA,
        "adjustment_cap": POWER_PRIOR_CAP,
        "pipeline": _model_parameters(pipeline, columns),
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return elo_all[evaluation_idx] + adjustment, artifact


def _matrix(table: pa.Table, columns: Sequence[str]) -> np.ndarray:
    rows = table.select(columns).to_pylist()
    return np.asarray(
        [[np.nan if row[name] is None else float(row[name]) for name in columns] for row in rows],
        dtype=np.float64,
    )


def _rows(
    table: pa.Table,
    fold: FrozenFold,
    target: str,
    predicted: Sequence[float] | np.ndarray,
    family: str,
    variant: str,
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected = table.filter(pc.equal(table["season"], fold.evaluation_season)).to_pylist()
    rows: list[dict[str, Any]] = []
    for row, value in zip(selected, predicted, strict=True):
        actual = float(row[target])
        rows.append(
            {
                "provider_game_id": int(row["provider_game_id"]),
                "canonical_event_id": row["canonical_event_id"],
                "season": int(row["season"]),
                "week": int(row["week"]),
                "kickoff": row["kickoff"],
                "horizon": row["prediction_horizon"],
                "target": target.removeprefix("target_"),
                "actual": actual,
                "prediction": float(value),
                "residual": actual - float(value),
                "model_family": family,
                "model_version": PRESEASON_MODEL_VERSION,
                "variant": variant,
                "fold_id": fold.fold_id,
                "training_cutoff": fold.train_end,
                "dataset_hash": manifest["dataset_hash"],
                "feature_set_hash": manifest["preseason_feature_set_hash"],
                "home_preseason_available": bool(row["home_preseason_available"]),
                "away_preseason_available": bool(row["away_preseason_available"]),
                "home_missing_family_count": row.get("home_preseason_missing_family_count"),
                "away_missing_family_count": row.get("away_preseason_missing_family_count"),
            }
        )
    return rows


def _build_report(
    predictions: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    ablations: Mapping[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {"candidates": {}, "comparisons": {}, "ablations_24h": ablations}
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in predictions:
        groups[(str(row["horizon"]), str(row["target"]), str(row["model_family"]), str(row["variant"]))].append(row)
    for key, rows in sorted(groups.items()):
        label = "|".join(key)
        report["candidates"][label] = _segments(rows)
        baseline_rows = _baseline_rows(baseline, key[0], key[1], key[2])
        if baseline_rows:
            comparison = paired_season_bootstrap(rows, baseline_rows)
            report["comparisons"][label] = {
                "baseline": _baseline_label(key[1], key[2]),
                "paired": comparison,
                "advancement": _advancement(rows, baseline_rows, comparison),
            }
    return report


def _baseline_rows(
    rows: Sequence[Mapping[str, Any]], horizon: str, target: str, candidate_family: str
) -> list[Mapping[str, Any]]:
    family, variant = (
        ("elo", "ncaaf-margin-power-v1")
        if target == "margin" and candidate_family == "power"
        else ("ridge", "full_v1")
        if target == "margin"
        else ("ridge", "full_without_opponent_adjustment")
    )
    return [
        row for row in rows
        if row["horizon"] == horizon and row["target"] == target
        and row["model_family"] == family and row["variant"] == variant
    ]


def _baseline_label(target: str, candidate_family: str) -> str:
    if target == "margin" and candidate_family == "power":
        return "chronological_power_rating"
    return "ridge_full_v1" if target == "margin" else "ridge_without_opponent_adjustment"


def _segments(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def score(selected: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
        if not selected:
            return None
        return metrics(
            np.asarray([row["actual"] for row in selected], dtype=float),
            np.asarray([row["prediction"] for row in selected], dtype=float),
        ) | {"n": float(len(selected))}

    return {
        "overall": score(rows),
        "weeks_0_1": score([row for row in rows if int(row["week"]) <= 1]),
        "weeks_2_3": score([row for row in rows if 2 <= int(row["week"]) <= 3]),
        "weeks_0_3": score([row for row in rows if int(row["week"]) <= 3]),
        "weeks_4_6": score([row for row in rows if 4 <= int(row["week"]) <= 6]),
        "weeks_7_plus": score([row for row in rows if int(row["week"]) >= 7]),
        "validation_2024": score([row for row in rows if int(row["season"]) == 2024]),
        "regime_2020": score([row for row in rows if int(row["season"]) == 2020]),
        "pbp_2021_2022": score([row for row in rows if int(row["season"]) in {2021, 2022}]),
        "complete_preseason": score(
            [
                row for row in rows
                if bool(row.get("home_preseason_available")) and bool(row.get("away_preseason_available"))
                and int(row.get("home_missing_family_count") or 0) <= 2
                and int(row.get("away_missing_family_count") or 0) <= 2
            ]
        ),
    }


def _advancement(
    challenger: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    comparison: Mapping[str, float],
) -> dict[str, Any]:
    challenger_segments = _segments(challenger)
    baseline_segments = _segments(baseline)
    gates: dict[str, bool] = {
        "weeks_0_3_mae_improves_0_20": False,
        "overall_rmse_not_worse": False,
        "paired_direction_or_0_35_gain": False,
        "early_subsegments_not_worse_0_15": False,
        "validation_directionally_consistent": False,
    }
    if challenger_segments["weeks_0_3"] and baseline_segments["weeks_0_3"]:
        gain = baseline_segments["weeks_0_3"]["mae"] - challenger_segments["weeks_0_3"]["mae"]
        gates["weeks_0_3_mae_improves_0_20"] = gain >= 0.20
        gates["paired_direction_or_0_35_gain"] = float(comparison["ci_97_5"]) < 0 or gain >= 0.35
    gates["overall_rmse_not_worse"] = (
        challenger_segments["overall"]["rmse"] <= baseline_segments["overall"]["rmse"]
    )
    gates["early_subsegments_not_worse_0_15"] = all(
        challenger_segments[name] is not None
        and baseline_segments[name] is not None
        and challenger_segments[name]["mae"] <= baseline_segments[name]["mae"] + 0.15
        for name in ("weeks_0_1", "weeks_2_3")
    )
    gates["validation_directionally_consistent"] = (
        challenger_segments["validation_2024"]["mae"]
        <= baseline_segments["validation_2024"]["mae"]
    )
    return {"gates": gates, "advances": all(gates.values())}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
