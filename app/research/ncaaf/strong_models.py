from __future__ import annotations

import gc
import hashlib
import json
import platform
import time
import warnings
from pathlib import Path
from typing import Any, Mapping, Sequence

import catboost
import lightgbm
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sklearn
import xgboost
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor
from sklearn.inspection import permutation_importance
from xgboost import XGBRegressor

from app.research.ncaaf.artifacts import ResearchArtifactStore, schema_hash, table_content_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.modeling import (
    FrozenFold,
    audit_input,
    feature_columns,
    frozen_folds,
    metrics,
    residual_diagnostics,
    summarize_predictions,
)

TOURNAMENT_VERSION = "ncaaf-strong-model-tournament-v1"
PREPROCESSING_VERSION = "native-missing-float32-v1"
SEED = 53105
REFERENCE_HORIZON = "24_hours_before_kickoff"
FAMILIES = ("xgboost", "lightgbm", "catboost")
TARGETS = ("target_margin", "target_total")
ABLATIONS = ("full_without_opponent_adjustment", "raw_efficiency", "context_prior")

CONFIGURATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "conservative", "max_depth": 3, "num_leaves": 15, "learning_rate": 0.03,
        "n_estimators": 500, "row_subsample": 0.85, "feature_subsample": 0.85,
        "min_child_samples": 20, "l2": 15.0,
    },
    {
        "name": "balanced", "max_depth": 5, "num_leaves": 31, "learning_rate": 0.05,
        "n_estimators": 300, "row_subsample": 0.85, "feature_subsample": 0.85,
        "min_child_samples": 20, "l2": 8.0,
    },
    {
        "name": "flexible", "max_depth": 7, "num_leaves": 63, "learning_rate": 0.07,
        "n_estimators": 200, "row_subsample": 0.80, "feature_subsample": 0.80,
        "min_child_samples": 30, "l2": 15.0,
    },
)


def tree_configuration(family: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """Translate one equal-budget generic configuration into library-native parameters."""
    if family == "xgboost":
        return {
            "objective": "reg:squarederror", "tree_method": "hist", "max_depth": config["max_depth"],
            "learning_rate": config["learning_rate"], "n_estimators": config["n_estimators"],
            "subsample": config["row_subsample"], "colsample_bytree": config["feature_subsample"],
            "min_child_weight": max(1.0, config["min_child_samples"] / 10), "reg_lambda": config["l2"],
            "random_state": SEED, "n_jobs": 1, "verbosity": 0,
        }
    if family == "lightgbm":
        return {
            "objective": "regression", "max_depth": config["max_depth"], "num_leaves": config["num_leaves"],
            "learning_rate": config["learning_rate"], "n_estimators": config["n_estimators"],
            "subsample": config["row_subsample"], "subsample_freq": 1,
            "colsample_bytree": config["feature_subsample"], "min_child_samples": config["min_child_samples"],
            "reg_lambda": config["l2"], "random_state": SEED, "n_jobs": 1,
            "deterministic": True, "force_col_wise": True, "verbosity": -1,
        }
    if family == "catboost":
        return {
            "loss_function": "RMSE", "depth": config["max_depth"], "learning_rate": config["learning_rate"],
            "iterations": config["n_estimators"], "subsample": config["row_subsample"],
            "rsm": config["feature_subsample"], "l2_leaf_reg": config["l2"],
            "random_seed": SEED, "thread_count": 1, "bootstrap_type": "Bernoulli",
            "allow_writing_files": False, "verbose": False,
        }
    raise ValueError(f"unsupported strong-model family: {family}")


def make_tree_model(family: str, config: Mapping[str, Any]) -> Any:
    parameters = tree_configuration(family, config)
    if family == "xgboost":
        return XGBRegressor(**parameters)
    if family == "lightgbm":
        return LGBMRegressor(**parameters)
    if family == "catboost":
        return CatBoostRegressor(**parameters)
    raise ValueError(f"unsupported strong-model family: {family}")


def _matrix(table: pa.Table, columns: Sequence[str]) -> np.ndarray:
    result = np.empty((table.num_rows, len(columns)), dtype=np.float32)
    for index, name in enumerate(columns):
        column = pc.cast(table[name], pa.float32())
        result[:, index] = pc.fill_null(column, np.nan).to_numpy(zero_copy_only=False)
    return result


def _indices(table: pa.Table, fold: FrozenFold, excluded: Sequence[int] = ()) -> tuple[np.ndarray, np.ndarray]:
    seasons = np.asarray(table["season"].to_numpy(zero_copy_only=False), dtype=int)
    train = (seasons >= fold.train_start) & (seasons <= fold.train_end)
    if excluded:
        train &= ~np.isin(seasons, np.asarray(excluded))
    return np.flatnonzero(train), np.flatnonzero(seasons == fold.evaluation_season)


def fit_predict_tree_fold(
    table: pa.Table,
    fold: FrozenFold,
    target: str,
    family: str,
    config: Mapping[str, Any],
    columns: Sequence[str],
    *,
    excluded_train_seasons: Sequence[int] = (),
    prepared_matrix: np.ndarray | None = None,
    prepared_target: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    if max(table["season"].to_pylist()) >= 2025:
        raise ValueError("locked 2025 holdout cannot enter strong-model fitting")
    train_idx, evaluation_idx = _indices(table, fold, excluded_train_seasons)
    if not len(train_idx) or not len(evaluation_idx):
        raise ValueError(f"empty chronological fold: {fold.fold_id}")
    matrix = prepared_matrix if prepared_matrix is not None else _matrix(table, columns)
    values = (
        prepared_target
        if prepared_target is not None
        else np.asarray(table[target].to_numpy(zero_copy_only=False), dtype=np.float32)
    )
    if matrix.shape != (table.num_rows, len(columns)) or len(values) != table.num_rows:
        raise ValueError("prepared tree matrix does not match the fold table")
    model = make_tree_model(family, config)
    model.fit(matrix[train_idx], values[train_idx])
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names, but LGBMRegressor was fitted with feature names",
            category=UserWarning,
        )
        prediction = np.asarray(model.predict(matrix[evaluation_idx]), dtype=np.float64)
    artifact = {
        "family": family, "version": TOURNAMENT_VERSION, "configuration": dict(config),
        "native_parameters": tree_configuration(family, config), "target": target,
        "fold_id": fold.fold_id, "training_cutoff": fold.train_end, "training_rows": int(len(train_idx)),
        "evaluation_rows": int(len(evaluation_idx)), "feature_count": len(columns),
        "feature_columns_hash": stable_hash(list(columns)), "excluded_train_seasons": list(excluded_train_seasons),
        "preprocessing_version": PREPROCESSING_VERSION,
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    del model
    gc.collect()
    return prediction, artifact


def _prediction_rows(
    table: pa.Table,
    fold: FrozenFold,
    target: str,
    family: str,
    variant: str,
    prediction: Sequence[float],
    manifest: Mapping[str, Any],
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = table.filter(pc.equal(table["season"], fold.evaluation_season)).select(
        [
            "canonical_event_id", "provider_game_id", "season", "week", "kickoff", "prediction_horizon",
            target, "home_pbp_coverage_ratio", "away_pbp_coverage_ratio", "home_current_season_games",
            "away_current_season_games", "covid_2020_regime",
        ]
    ).to_pylist()
    output = []
    for row, value in zip(rows, prediction, strict=True):
        actual = float(row[target])
        output.append(
            {
                "canonical_event_id": row["canonical_event_id"], "provider_game_id": row["provider_game_id"],
                "season": row["season"], "week": row["week"], "kickoff": row["kickoff"],
                "horizon": row["prediction_horizon"], "target": target.removeprefix("target_"),
                "actual": actual, "prediction": float(value), "residual": actual - float(value),
                "model_family": family, "model_version": TOURNAMENT_VERSION, "variant": variant,
                "fold_id": fold.fold_id, "training_cutoff": fold.train_end,
                "feature_set_hash": manifest["feature_set_hash"], "dataset_hash": manifest["dataset_hash"],
                "preprocessing_version": PREPROCESSING_VERSION,
                "model_parameters": json.dumps(config, sort_keys=True),
                "home_pbp_coverage_ratio": row["home_pbp_coverage_ratio"],
                "away_pbp_coverage_ratio": row["away_pbp_coverage_ratio"],
                "home_current_season_games": row["home_current_season_games"],
                "away_current_season_games": row["away_current_season_games"],
                "covid_2020_regime": row["covid_2020_regime"],
            }
        )
    return output


def _feature_artifact(manifest: Mapping[str, Any], horizon: str) -> Mapping[str, Any]:
    matches = [
        item for item in manifest["artifacts"]
        if item["dataset"] == "model_ready_games" and item.get("prediction_horizon") == horizon
    ]
    if len(matches) != 1:
        raise ValueError(f"feature artifact unavailable for horizon: {horizon}")
    return matches[0]


def load_horizon_table(
    store: ResearchArtifactStore,
    manifest: Mapping[str, Any],
    horizon: str,
    *,
    end_season: int = 2024,
) -> pa.Table:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter strong-model loading")
    table = store.read_table(str(_feature_artifact(manifest, horizon)["uri"]))
    return table.filter(pc.less_equal(table["season"], end_season))


def tune_family(
    table: pa.Table,
    target: str,
    family: str,
    *,
    configurations: Sequence[Mapping[str, Any]] = CONFIGURATIONS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    columns = feature_columns(table, "full_v1")
    matrix = _matrix(table, columns)
    values = np.asarray(table[target].to_numpy(zero_copy_only=False), dtype=np.float32)
    trials: list[dict[str, Any]] = []
    for config in configurations:
        absolute_errors: list[float] = []
        squared_errors: list[float] = []
        for fold in frozen_folds():
            if fold.role != "development":
                continue
            prediction, _ = fit_predict_tree_fold(
                table, fold, target, family, config, columns,
                prepared_matrix=matrix, prepared_target=values,
            )
            actual = np.asarray(
                table.filter(pc.equal(table["season"], fold.evaluation_season))[target].to_numpy(zero_copy_only=False),
                dtype=float,
            )
            residual = actual - prediction
            absolute_errors.extend(np.abs(residual).tolist())
            squared_errors.extend((residual**2).tolist())
        trials.append(
            {
                "family": family, "target": target, "configuration": dict(config),
                "development_folds": 5, "fit_count": 5,
                "development_mae": float(np.mean(absolute_errors)),
                "development_rmse": float(np.sqrt(np.mean(squared_errors))),
            }
        )
    selected = min(trials, key=lambda item: (item["development_mae"], stable_hash(item["configuration"])))
    del matrix, values
    gc.collect()
    return dict(selected["configuration"]), trials


def paired_block_comparison(
    challenger: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    *,
    iterations: int = 2_000,
) -> dict[str, Any]:
    left = {(int(row["provider_game_id"]), int(row["season"])): row for row in challenger}
    right = {(int(row["provider_game_id"]), int(row["season"])): row for row in baseline}
    keys = sorted(left.keys() & right.keys(), key=lambda item: (item[1], item[0]))
    if not keys:
        raise ValueError("paired model comparison has no shared games")
    seasons = sorted({season for _, season in keys})
    absolute = {
        season: np.asarray(
            [abs(float(left[key]["residual"])) - abs(float(right[key]["residual"])) for key in keys if key[1] == season]
        ) for season in seasons
    }
    squared = {
        season: np.asarray(
            [float(left[key]["residual"]) ** 2 - float(right[key]["residual"]) ** 2 for key in keys if key[1] == season]
        ) for season in seasons
    }
    rng = np.random.default_rng(SEED)
    mae_samples = np.empty(iterations)
    mse_samples = np.empty(iterations)
    for index in range(iterations):
        chosen = rng.choice(seasons, len(seasons), replace=True)
        mae_samples[index] = np.mean(np.concatenate([absolute[int(season)] for season in chosen]))
        mse_samples[index] = np.mean(np.concatenate([squared[int(season)] for season in chosen]))
    return {
        "paired_games": len(keys), "seasons": seasons,
        "mae_difference": float(np.mean(np.concatenate(list(absolute.values())))),
        "mae_ci_2_5": float(np.quantile(mae_samples, 0.025)),
        "mae_ci_97_5": float(np.quantile(mae_samples, 0.975)),
        "mse_difference": float(np.mean(np.concatenate(list(squared.values())))),
        "mse_ci_2_5": float(np.quantile(mse_samples, 0.025)),
        "mse_ci_97_5": float(np.quantile(mse_samples, 0.975)),
    }


def _rows(table: pa.Table, family: str, variant: str, target: str, horizon: str) -> list[dict[str, Any]]:
    mask = pc.and_(
        pc.and_(pc.equal(table["model_family"], family), pc.equal(table["variant"], variant)),
        pc.and_(pc.equal(table["target"], target), pc.equal(table["horizon"], horizon)),
    )
    return table.filter(mask).to_pylist()


def _segment_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def scored(selected: Sequence[Mapping[str, Any]]) -> Mapping[str, float] | None:
        if not selected:
            return None
        return metrics(
            np.asarray([row["actual"] for row in selected], dtype=float),
            np.asarray([row["prediction"] for row in selected], dtype=float),
        )

    high = [
        row for row in rows
        if float(row.get("home_pbp_coverage_ratio") or 0) >= 0.8
        and float(row.get("away_pbp_coverage_ratio") or 0) >= 0.8
    ]
    high_keys = {(row["provider_game_id"], row["season"]) for row in high}
    return {
        "overall": scored(rows), "validation_2024": scored([r for r in rows if int(r["season"]) == 2024]),
        "weeks_0_3": scored([r for r in rows if int(r.get("week") or 0) <= 3]),
        "later": scored([r for r in rows if int(r.get("week") or 0) > 3]),
        "regime_2020": scored([r for r in rows if int(r["season"]) == 2020]),
        "pbp_2021_2022": scored([r for r in rows if int(r["season"]) in {2021, 2022}]),
        "outside_2021_2022": scored([r for r in rows if int(r["season"]) not in {2021, 2022}]),
        "high_quality": scored(high),
        "low_quality": scored([r for r in rows if (r["provider_game_id"], r["season"]) not in high_keys]),
        "residuals": residual_diagnostics(
            np.asarray([row["actual"] for row in rows], dtype=float),
            np.asarray([row["prediction"] for row in rows], dtype=float),
        ),
    }


def _advancement(
    challenger: Sequence[Mapping[str, Any]],
    baseline: Sequence[Mapping[str, Any]],
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    challenger_segments = _segment_metrics(challenger)
    baseline_segments = _segment_metrics(baseline)
    assert challenger_segments["overall"] and baseline_segments["overall"]
    assert challenger_segments["validation_2024"] and baseline_segments["validation_2024"]
    gates = {
        "mae_improvement_at_least_0_10": float(comparison["mae_difference"]) <= -0.10,
        "bootstrap_upper_below_zero": float(comparison["mae_ci_97_5"]) < 0,
        "validation_not_worse_by_0_15": (
            challenger_segments["validation_2024"]["mae"]
            <= baseline_segments["validation_2024"]["mae"] + 0.15
        ),
        "rmse_not_materially_worse": (
            challenger_segments["overall"]["rmse"] <= baseline_segments["overall"]["rmse"] + 0.05
        ),
    }
    for segment in ("weeks_0_3", "low_quality"):
        challenger_value = challenger_segments[segment]
        baseline_value = baseline_segments[segment]
        gates[f"{segment}_not_worse_by_0_25"] = bool(
            challenger_value and baseline_value and challenger_value["mae"] <= baseline_value["mae"] + 0.25
        )
    gates["advances"] = all(gates.values())
    return {"gates": gates, "challenger": challenger_segments, "baseline": baseline_segments}


def _permutation_diagnostics(
    table: pa.Table,
    target: str,
    family: str,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fold = next(item for item in frozen_folds() if item.role == "validation")
    columns = feature_columns(table, "full_v1")
    train_idx, evaluation_idx = _indices(table, fold)
    matrix = _matrix(table, columns)
    values = np.asarray(table[target].to_numpy(zero_copy_only=False), dtype=np.float32)
    model = make_tree_model(family, config)
    model.fit(matrix[train_idx], values[train_idx])
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="X does not have valid feature names, but LGBMRegressor was fitted with feature names",
            category=UserWarning,
        )
        result = permutation_importance(
            model, matrix[evaluation_idx], values[evaluation_idx], scoring="neg_mean_absolute_error",
            n_repeats=3, random_state=SEED, n_jobs=1,
        )
    output: list[dict[str, Any]] = [
        {"feature": name, "mean_mae_increase": float(result.importances_mean[index]),
         "standard_deviation": float(result.importances_std[index])}
        for index, name in enumerate(columns)
    ]
    del model, matrix, values
    gc.collect()
    return sorted(output, key=lambda row: (-float(row["mean_mae_increase"]), str(row["feature"])))[:30]


def run_strong_model_tournament(
    store: ResearchArtifactStore,
    feature_manifest: Mapping[str, Any],
    *,
    baseline_root: Path,
    output_root: Path,
    end_season: int = 2024,
    selected_families: Sequence[str] = (),
    selected_targets: Sequence[str] = (),
    selected_horizons: Sequence[str] = (),
    configurations: Sequence[Mapping[str, Any]] = CONFIGURATIONS,
) -> dict[str, Any]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter strong-model tournament")
    started = time.perf_counter()
    families = tuple(selected_families) or FAMILIES
    targets = tuple(selected_targets) or TARGETS
    horizons = tuple(selected_horizons) or tuple(feature_manifest["horizons"])
    if not set(families) <= set(FAMILIES) or not set(targets) <= set(TARGETS):
        raise ValueError("unsupported family or target")
    reference = load_horizon_table(store, feature_manifest, REFERENCE_HORIZON, end_season=end_season)
    audit = audit_input(reference, feature_manifest, REFERENCE_HORIZON)
    selections: dict[str, dict[str, Any]] = {}
    tuning_trials: list[dict[str, Any]] = []
    for target in targets:
        selections[target] = {}
        for family in families:
            selected, trials = tune_family(reference, target, family, configurations=configurations)
            selections[target][family] = selected
            tuning_trials.extend(trials)
    strongest = {
        target: min(
            families,
            key=lambda family: next(
                row["development_mae"] for row in tuning_trials
                if row["target"] == target and row["family"] == family
                and row["configuration"]["name"] == selections[target][family]["name"]
            ),
        ) for target in targets
    }
    predictions: list[dict[str, Any]] = []
    fold_artifacts: list[dict[str, Any]] = []
    audits = {REFERENCE_HORIZON: audit}
    for horizon in horizons:
        table = reference if horizon == REFERENCE_HORIZON else load_horizon_table(
            store, feature_manifest, horizon, end_season=end_season
        )
        audits[horizon] = audit_input(table, feature_manifest, horizon)
        full_columns = feature_columns(table, "full_v1")
        full_matrix = _matrix(table, full_columns)
        for target in targets:
            target_values = np.asarray(table[target].to_numpy(zero_copy_only=False), dtype=np.float32)
            for family in families:
                config = selections[target][family]
                for fold in frozen_folds():
                    prediction, artifact = fit_predict_tree_fold(
                        table, fold, target, family, config, full_columns,
                        prepared_matrix=full_matrix, prepared_target=target_values,
                    )
                    artifact.update({"horizon": horizon, "variant": "full_v1"})
                    fold_artifacts.append(artifact)
                    predictions.extend(
                        _prediction_rows(
                            table, fold, target, family, "full_v1", prediction.tolist(), feature_manifest, config
                        )
                    )
            del target_values
        del full_matrix
        if table is not reference:
            del table
            gc.collect()
    for target in targets:
        family = strongest[target]
        config = selections[target][family]
        for ablation in ABLATIONS:
            columns = feature_columns(reference, ablation)
            matrix = _matrix(reference, columns)
            values = np.asarray(reference[target].to_numpy(zero_copy_only=False), dtype=np.float32)
            for fold in frozen_folds():
                prediction, artifact = fit_predict_tree_fold(
                    reference, fold, target, family, config, columns,
                    prepared_matrix=matrix, prepared_target=values,
                )
                artifact.update({"horizon": REFERENCE_HORIZON, "variant": ablation})
                fold_artifacts.append(artifact)
                predictions.extend(
                    _prediction_rows(
                        reference, fold, target, family, ablation, prediction.tolist(), feature_manifest, config
                    )
                )
            del matrix, values
        validation = next(item for item in frozen_folds() if item.role == "validation")
        columns = feature_columns(reference)
        matrix = _matrix(reference, columns)
        values = np.asarray(reference[target].to_numpy(zero_copy_only=False), dtype=np.float32)
        prediction, artifact = fit_predict_tree_fold(
            reference, validation, target, family, config, feature_columns(reference),
            excluded_train_seasons=(2021, 2022),
            prepared_matrix=matrix, prepared_target=values,
        )
        artifact.update({"horizon": REFERENCE_HORIZON, "variant": "full_v1_exclude_2021_2022_train"})
        fold_artifacts.append(artifact)
        predictions.extend(
            _prediction_rows(
                reference, validation, target, family, "full_v1_exclude_2021_2022_train",
                prediction.tolist(), feature_manifest, {**config, "excluded_train_seasons": [2021, 2022]},
            )
        )
        del matrix, values
    prediction_table = pa.Table.from_pylist(predictions).sort_by(
        [(name, "ascending") for name in ("horizon", "target", "model_family", "variant", "kickoff", "provider_game_id")]
    )
    baseline_table = pq.read_table(baseline_root / "oof_predictions.parquet")
    comparisons: dict[str, Any] = {}
    advancement: dict[str, Any] = {}
    for horizon in horizons:
        for target_name in ("margin", "total"):
            if f"target_{target_name}" not in targets:
                continue
            baseline_family = "elo" if target_name == "margin" else "ridge"
            baseline_variant = "ncaaf-margin-power-v1" if target_name == "margin" else "full_without_opponent_adjustment"
            baseline_rows = _rows(baseline_table, baseline_family, baseline_variant, target_name, horizon)
            for family in families:
                challenger_rows = _rows(prediction_table, family, "full_v1", target_name, horizon)
                comparison = paired_block_comparison(challenger_rows, baseline_rows)
                key = f"{horizon}|{target_name}|{family}"
                comparisons[key] = comparison
                advancement[key] = _advancement(challenger_rows, baseline_rows, comparison)
    importances = {
        target.removeprefix("target_"): _permutation_diagnostics(
            reference, target, strongest[target], selections[target][strongest[target]]
        ) for target in targets
    }
    output_root.mkdir(parents=True, exist_ok=True)
    predictions_path = output_root / "oof_predictions.parquet"
    pq.write_table(prediction_table, predictions_path, compression="zstd")
    artifacts_path = output_root / "fold_model_manifests.json"
    artifacts_path.write_text(json.dumps(fold_artifacts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "summary": summarize_predictions(prediction_table), "comparisons": comparisons,
        "advancement": advancement, "feature_importance": importances,
    }
    baseline_manifest = json.loads((baseline_root / "run_manifest.json").read_text(encoding="utf-8"))
    manifest: dict[str, Any] = {
        "tournament_version": TOURNAMENT_VERSION, "experiment_plan": "docs/NCAAF_STRONG_MODEL_EXPERIMENT_PLAN.md",
        "dataset_hash": feature_manifest["dataset_hash"], "feature_set_hash": feature_manifest["feature_set_hash"],
        "availability_policy_version": feature_manifest["availability_policy_version"],
        "baseline_run_hash": baseline_manifest["run_hash"], "seed": SEED,
        "families": list(families), "targets": list(targets), "horizons": list(horizons),
        "configurations": [dict(item) for item in configurations], "tuning_trials": tuning_trials,
        "selected_configurations": selections, "strongest_development_family": strongest,
        "fit_budget": {
            "tuning": len(tuning_trials) * 5,
            "primary_oof": len(families) * len(targets) * len(horizons) * len(frozen_folds()),
            "ablation": len(targets) * len(ABLATIONS) * len(frozen_folds()),
            "sensitivity": len(targets),
            "actual_total": len(fold_artifacts) + len(tuning_trials) * 5 + len(targets),
        },
        "input_audits": audits, "preprocessing_version": PREPROCESSING_VERSION,
        "prediction_rows": prediction_table.num_rows, "prediction_schema_hash": schema_hash(prediction_table.schema),
        "prediction_content_hash": table_content_hash(prediction_table),
        "prediction_file_sha256": _sha256(predictions_path), "model_manifests_sha256": _sha256(artifacts_path),
        "report": report, "provider_calls": 0, "holdout_accessed": False,
        "package_versions": {
            "python": platform.python_version(), "numpy": np.__version__, "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__, "lightgbm": lightgbm.__version__, "catboost": catboost.__version__,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    deterministic = {key: value for key, value in manifest.items() if key != "elapsed_seconds"}
    manifest["run_hash"] = stable_hash(deterministic)
    (output_root / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_strong_model_run(output_root: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    predictions = pq.read_table(output_root / "oof_predictions.parquet")
    if predictions.num_rows != manifest["prediction_rows"]:
        errors.append("prediction row count mismatch")
    if max(predictions["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked holdout accessed")
    if table_content_hash(predictions) != manifest["prediction_content_hash"]:
        errors.append("prediction content mismatch")
    if _sha256(output_root / "oof_predictions.parquet") != manifest["prediction_file_sha256"]:
        errors.append("prediction file hash mismatch")
    keys = list(
        zip(
            predictions["provider_game_id"].to_pylist(), predictions["horizon"].to_pylist(),
            predictions["target"].to_pylist(), predictions["model_family"].to_pylist(),
            predictions["variant"].to_pylist(), predictions["season"].to_pylist(), strict=True,
        )
    )
    if len(keys) != len(set(keys)):
        errors.append("duplicate OOF prediction keys")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
