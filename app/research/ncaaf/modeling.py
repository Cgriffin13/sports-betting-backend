from __future__ import annotations

import hashlib
import json
import math
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import sklearn
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.research.ncaaf.artifacts import ResearchArtifactStore, schema_hash, table_content_hash
from app.research.ncaaf.contracts import FOLD_POLICY_VERSION, chronological_folds, stable_hash

MODEL_INPUT_VERSION = "ncaaf-model-input-v1"
PREPROCESSING_VERSION = "median-indicator-variance-standardize-v1"
TOURNAMENT_VERSION = "ncaaf-baseline-tournament-v1"
ELO_VERSION = "ncaaf-margin-power-v1"
SEED = 53103
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0)
ELASTIC_GRID = ((0.001, 0.1), (0.001, 0.5), (0.01, 0.1), (0.01, 0.5), (0.1, 0.1), (0.1, 0.5))

IDENTIFIERS = (
    "canonical_event_id", "provider_game_id", "season", "week", "kickoff", "prediction_as_of",
    "prediction_horizon", "home_program_id", "away_program_id",
)
TARGETS = ("target_margin", "target_total")
EXCLUDED_METADATA = frozenset(
    {
        *IDENTIFIERS, *TARGETS, "morning_policy", "home_conference", "away_conference",
        "home_classification", "away_classification", "venue_id", "feature_set_version", "feature_set_hash",
        "source_corpus_version", "availability_policy_version", "opponent_adjustment_version",
        "early_season_prior_version", "fold_role",
    }
)
QUALITY_TOKENS = ("games_available", "coverage", "reconstructed", "adjustment_available", "current_weight", "prior_weight")


@dataclass(frozen=True, slots=True)
class FrozenFold:
    fold_id: str
    role: str
    train_start: int
    train_end: int
    evaluation_season: int
    policy_version: str = FOLD_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class EloConfig:
    offseason_carry: float = 0.65
    home_field_points: float = 2.5
    update_rate: float = 0.15
    error_cap: float = 35.0
    version: str = ELO_VERSION


def frozen_folds() -> tuple[FrozenFold, ...]:
    return tuple(
        FrozenFold(item.name, item.role, min(item.train_seasons), max(item.train_seasons), item.evaluation_season)
        for item in chronological_folds()
    )


def feature_columns(table: pa.Table, ablation: str = "full_v1") -> tuple[str, ...]:
    columns = [
        field.name for field in table.schema
        if field.name not in EXCLUDED_METADATA and (pa.types.is_integer(field.type) or pa.types.is_floating(field.type) or pa.types.is_boolean(field.type))
    ]
    if ablation == "context_prior":
        columns = [c for c in columns if c in {"week", "neutral_site", "conference_game", "postseason", "covid_2020_regime", "home_rest_days", "away_rest_days"} or "_prior" in c]
    elif ablation == "raw_efficiency":
        columns = [c for c in columns if "opponent_adjusted" not in c and not any(t in c for t in QUALITY_TOKENS)]
    elif ablation == "opponent_adjusted":
        columns = [c for c in columns if "opponent_adjusted" in c or "_prior" in c or c in {"week", "neutral_site", "postseason"}]
    elif ablation == "full_without_opponent_adjustment":
        columns = [c for c in columns if "opponent_adjusted" not in c]
    elif ablation == "full_without_quality":
        columns = [c for c in columns if not any(t in c for t in QUALITY_TOKENS)]
    elif ablation != "full_v1":
        raise ValueError(f"unknown ablation: {ablation}")
    return tuple(sorted(columns))


def audit_input(table: pa.Table, manifest: Mapping[str, Any], horizon: str) -> dict[str, Any]:
    if table.num_rows == 0:
        raise ValueError("model input is empty")
    seasons = [int(v) for v in table["season"].to_pylist()]
    if max(seasons) >= 2025:
        raise ValueError("locked 2025 holdout cannot enter baseline modeling")
    keys = list(zip(table["provider_game_id"].to_pylist(), table["prediction_horizon"].to_pylist(), strict=True))
    features = feature_columns(table)
    nonfinite: dict[str, int] = {}
    missing: dict[str, int] = {}
    for name in features:
        values = table[name].to_pylist()
        missing[name] = sum(v is None for v in values)
        bad = sum(isinstance(v, float) and not math.isfinite(v) for v in values)
        if bad:
            nonfinite[name] = bad
    for target in TARGETS:
        if table[target].null_count:
            raise ValueError(f"missing target values: {target}")
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate game/horizon rows")
    ordered = list(zip(table["kickoff"].to_pylist(), table["provider_game_id"].to_pylist(), strict=True))
    if ordered != sorted(ordered):
        raise ValueError("model input is not chronologically ordered")
    return {
        "version": MODEL_INPUT_VERSION,
        "dataset_hash": manifest["dataset_hash"], "feature_set_hash": manifest["feature_set_hash"],
        "availability_policy_version": manifest["availability_policy_version"], "horizon": horizon,
        "eligible_rows": table.num_rows, "seasons": [min(seasons), max(seasons)],
        "identifiers": list(IDENTIFIERS), "targets": list(TARGETS), "features": list(features),
        "quality_indicators": [c for c in features if any(t in c for t in QUALITY_TOKENS)],
        "excluded_metadata": sorted(EXCLUDED_METADATA - set(TARGETS) - set(IDENTIFIERS)),
        "missingness": missing, "nonfinite": nonfinite, "duplicate_rows": 0,
        "manifest_hash": stable_hash({"dataset_hash": manifest["dataset_hash"], "horizon": horizon, "features": features}),
    }


def load_feature_tables(store: ResearchArtifactStore, manifest: Mapping[str, Any]) -> dict[str, pa.Table]:
    result: dict[str, pa.Table] = {}
    for artifact in manifest["artifacts"]:
        if artifact["dataset"] != "model_ready_games":
            continue
        table = store.read_table(artifact["uri"])
        horizon = str(table["prediction_horizon"][0].as_py())
        result[horizon] = table
    expected = set(manifest["horizons"])
    if set(result) != expected:
        raise ValueError("feature horizon artifacts do not match manifest")
    return result


def horizon_features_identical(tables: Mapping[str, pa.Table], columns: Sequence[str]) -> bool:
    reference: list[tuple[Any, ...]] | None = None
    for table in tables.values():
        ordered = table.select(["provider_game_id", *columns]).sort_by([("provider_game_id", "ascending")]).to_pylist()
        rows = [tuple(row.get(c) for c in ("provider_game_id", *columns)) for row in ordered]
        if reference is None:
            reference = rows
        elif rows != reference:
            return False
    return True


def make_pipeline(family: str, parameters: Mapping[str, float]) -> Pipeline:
    estimator: Ridge | ElasticNet
    if family == "ridge":
        estimator = Ridge(alpha=float(parameters["alpha"]), solver="cholesky")
    elif family == "elastic_net":
        estimator = ElasticNet(alpha=float(parameters["alpha"]), l1_ratio=float(parameters["l1_ratio"]), max_iter=20000, random_state=SEED)
    else:
        raise ValueError(f"unsupported family: {family}")
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("variance", VarianceThreshold()), ("scaler", StandardScaler()), ("model", estimator),
        ]
    )


def _matrix(table: pa.Table, columns: Sequence[str]) -> np.ndarray:
    rows = table.select(columns).to_pylist()
    return np.asarray([[np.nan if row[c] is None else float(row[c]) for c in columns] for row in rows], dtype=np.float64)


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    residual = actual - predicted
    ss_total = float(np.sum((actual - np.mean(actual)) ** 2))
    return {
        "mae": float(np.mean(np.abs(residual))), "rmse": float(np.sqrt(np.mean(residual**2))),
        "bias": float(np.mean(predicted - actual)), "median_absolute_error": float(np.median(np.abs(residual))),
        "r2": 1.0 - float(np.sum(residual**2)) / ss_total if ss_total else 0.0,
    }


def residual_diagnostics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    residual = actual - predicted
    centered = residual - np.mean(residual)
    sd = float(np.std(residual))
    return {
        "mean": float(np.mean(residual)), "standard_deviation": sd,
        "quantiles": {str(q): float(np.quantile(residual, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
        "skewness": float(np.mean(centered**3) / sd**3) if sd else 0.0,
        "excess_kurtosis": float(np.mean(centered**4) / sd**4 - 3.0) if sd else 0.0,
        "heavy_tail_indicator": bool(sd and np.quantile(np.abs(centered), 0.95) > 2 * sd),
    }


def paired_season_bootstrap(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    *,
    iterations: int = 2000,
    seed: int = SEED,
) -> dict[str, float]:
    """Paired MAE(A)-MAE(B) uncertainty by resampling whole season blocks."""
    index_a = {(row["provider_game_id"], row["season"]): row for row in rows_a}
    index_b = {(row["provider_game_id"], row["season"]): row for row in rows_b}
    keys = sorted(index_a.keys() & index_b.keys(), key=lambda item: (item[1], item[0]))
    if not keys:
        raise ValueError("paired comparison has no shared games")
    seasons = sorted({int(season) for _, season in keys})
    by_season = {
        season: np.asarray(
            [abs(float(index_a[key]["residual"])) - abs(float(index_b[key]["residual"])) for key in keys if int(key[1]) == season]
        )
        for season in seasons
    }
    observed = float(np.mean(np.concatenate(list(by_season.values()))))
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations)
    for index in range(iterations):
        selected = rng.choice(seasons, size=len(seasons), replace=True)
        samples[index] = np.mean(np.concatenate([by_season[int(season)] for season in selected]))
    return {
        "paired_games": float(len(keys)), "mae_difference": observed,
        "ci_2_5": float(np.quantile(samples, 0.025)), "ci_97_5": float(np.quantile(samples, 0.975)),
    }


def elo_predictions(rows: Sequence[Mapping[str, Any]], config: EloConfig = EloConfig()) -> list[float]:
    ratings: dict[str, float] = {}
    previous_season: int | None = None
    predictions: list[float] = []
    for row in sorted(rows, key=lambda r: (r["kickoff"], r["provider_game_id"])):
        season = int(row["season"])
        if previous_season is not None and season != previous_season:
            ratings = {team: rating * config.offseason_carry for team, rating in ratings.items()}
        previous_season = season
        home, away = str(row["home_program_id"]), str(row["away_program_id"])
        hfa = 0.0 if row["neutral_site"] else config.home_field_points
        prediction = ratings.get(home, 0.0) - ratings.get(away, 0.0) + hfa
        predictions.append(prediction)
        error = max(-config.error_cap, min(config.error_cap, float(row["target_margin"]) - prediction))
        adjustment = config.update_rate * error / 2.0
        ratings[home] = ratings.get(home, 0.0) + adjustment
        ratings[away] = ratings.get(away, 0.0) - adjustment
    return predictions


def _model_parameters(pipeline: Pipeline, columns: Sequence[str]) -> dict[str, Any]:
    imputer = pipeline.named_steps["imputer"]
    variance = pipeline.named_steps["variance"]
    scaler = pipeline.named_steps["scaler"]
    model = pipeline.named_steps["model"]
    return {
        "feature_columns": list(columns), "imputer_statistics": imputer.statistics_.tolist(),
        "variance_support": variance.get_support().tolist(), "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(), "coefficients": model.coef_.tolist(),
        "intercept": float(model.intercept_),
    }


def fit_predict_fold(
    table: pa.Table,
    fold: FrozenFold,
    target: str,
    family: str,
    params: Mapping[str, float],
    columns: Sequence[str],
    *,
    excluded_train_seasons: Sequence[int] = (),
) -> tuple[np.ndarray, dict[str, Any]]:
    seasons = np.asarray(table["season"].to_pylist())
    train_mask = (seasons >= fold.train_start) & (seasons <= fold.train_end)
    if excluded_train_seasons:
        train_mask &= ~np.isin(seasons, np.asarray(excluded_train_seasons))
    train_idx = np.where(train_mask)[0]
    eval_idx = np.where(seasons == fold.evaluation_season)[0]
    if not len(train_idx) or not len(eval_idx):
        raise ValueError(f"empty fold: {fold.fold_id}")
    pipeline = make_pipeline(family, params)
    pipeline.fit(_matrix(table.take(pa.array(train_idx)), columns), np.asarray(table[target].to_pylist(), dtype=float)[train_idx])
    prediction = pipeline.predict(_matrix(table.take(pa.array(eval_idx)), columns))
    artifact = {
        "model_family": family, "model_version": TOURNAMENT_VERSION, "target": target,
        "fold_id": fold.fold_id, "training_cutoff": fold.train_end, "training_rows": len(train_idx),
        "preprocessing_version": PREPROCESSING_VERSION, "parameters": dict(params),
        "excluded_train_seasons": list(excluded_train_seasons),
        "pipeline": _model_parameters(pipeline, columns),
        "package_versions": {"python": platform.python_version(), "numpy": np.__version__, "scikit_learn": sklearn.__version__},
    }
    artifact["artifact_hash"] = stable_hash(artifact)
    return prediction, artifact


def _prediction_rows(table: pa.Table, fold: FrozenFold, target: str, family: str, variant: str, prediction: Sequence[float], manifest: Mapping[str, Any], parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    eval_rows = table.filter(pc.equal(table["season"], fold.evaluation_season)).to_pylist()
    result = []
    for row, value in zip(eval_rows, prediction, strict=True):
        actual = float(row[target])
        result.append(
            {
                "canonical_event_id": row["canonical_event_id"], "provider_game_id": row["provider_game_id"],
                "season": row["season"], "week": row["week"], "kickoff": row["kickoff"],
                "horizon": row["prediction_horizon"], "target": target.removeprefix("target_"), "actual": actual,
                "prediction": float(value), "residual": actual - float(value), "model_family": family,
                "model_version": TOURNAMENT_VERSION, "variant": variant, "fold_id": fold.fold_id,
                "training_cutoff": fold.train_end, "feature_set_hash": manifest["feature_set_hash"],
                "dataset_hash": manifest["dataset_hash"], "preprocessing_version": PREPROCESSING_VERSION,
                "model_parameters": json.dumps(parameters, sort_keys=True),
                "home_pbp_coverage_ratio": row["home_pbp_coverage_ratio"], "away_pbp_coverage_ratio": row["away_pbp_coverage_ratio"],
                "home_current_season_games": row["home_current_season_games"], "away_current_season_games": row["away_current_season_games"],
                "covid_2020_regime": row["covid_2020_regime"],
            }
        )
    return result


def _mean_baseline(table: pa.Table, fold: FrozenFold, target: str, variant: str) -> np.ndarray:
    seasons = np.asarray(table["season"].to_pylist())
    values = np.asarray(table[target].to_pylist(), dtype=float)
    train = values[(seasons >= fold.train_start) & (seasons <= fold.train_end)]
    eval_rows = table.filter(pc.equal(table["season"], fold.evaluation_season)).to_pylist()
    if variant == "training_mean":
        return np.full(len(eval_rows), np.mean(train))
    neutral = np.asarray(table["neutral_site"].to_pylist(), dtype=bool)
    if target == "target_margin":
        neutral_mean = float(np.mean(values[(seasons <= fold.train_end) & neutral]))
        home_mean = float(np.mean(values[(seasons <= fold.train_end) & ~neutral]))
        return np.asarray([neutral_mean if row["neutral_site"] else home_mean for row in eval_rows])
    return np.full(len(eval_rows), np.mean(train))


def _prior_team_baseline(table: pa.Table, fold: FrozenFold, target: str) -> np.ndarray:
    narrow = table.select(["season", "home_program_id", "away_program_id", target])
    rows = narrow.to_pylist()
    history = [row for row in rows if fold.train_start <= int(row["season"]) <= fold.train_end]
    eval_rows = [row for row in rows if int(row["season"]) == fold.evaluation_season]
    team_values: dict[str, list[float]] = {}
    for row in history:
        value = float(row[target])
        if target == "target_margin":
            team_values.setdefault(str(row["home_program_id"]), []).append(value)
            team_values.setdefault(str(row["away_program_id"]), []).append(-value)
        else:
            team_values.setdefault(str(row["home_program_id"]), []).append(value)
            team_values.setdefault(str(row["away_program_id"]), []).append(value)
    overall = float(np.mean([float(row[target]) for row in history]))
    result = []
    for row in eval_rows:
        home = team_values.get(str(row["home_program_id"]), [])
        away = team_values.get(str(row["away_program_id"]), [])
        if target == "target_margin":
            result.append((float(np.mean(home)) if home else 0.0) - (float(np.mean(away)) if away else 0.0))
        else:
            values = [*(home[-20:]), *(away[-20:])]
            result.append(float(np.mean(values)) if values else overall)
    return np.asarray(result)


def prediction_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    return pa.Table.from_pylist(sorted(rows, key=lambda r: (r["horizon"], r["target"], r["model_family"], r["variant"], r["kickoff"], r["provider_game_id"])))


def run_tournament(
    store: ResearchArtifactStore,
    manifest: Mapping[str, Any],
    *,
    output_root: Path,
    bounded_end_season: int = 2024,
    selected_horizons: Sequence[str] = (),
    selected_targets: Sequence[str] = (),
    selected_families: Sequence[str] = (),
) -> dict[str, Any]:
    if bounded_end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter baseline modeling")
    started = time.perf_counter()
    tables = load_feature_tables(store, manifest)
    if selected_horizons:
        unknown = set(selected_horizons) - set(tables)
        if unknown:
            raise ValueError(f"unknown horizons: {sorted(unknown)}")
        tables = {key: value for key, value in tables.items() if key in selected_horizons}
    targets = tuple(selected_targets) or TARGETS
    families = frozenset(selected_families or ("naive", "elo", "ridge"))
    if not set(targets) <= set(TARGETS) or not families <= {"naive", "elo", "ridge"}:
        raise ValueError("unsupported target or family selection")
    audits = {h: audit_input(t, manifest, h) for h, t in tables.items()}
    folds = tuple(f for f in frozen_folds() if f.evaluation_season <= bounded_end_season)
    ablations = ("context_prior", "raw_efficiency", "opponent_adjusted", "full_v1", "full_without_opponent_adjustment")
    all_predictions: list[dict[str, Any]] = []
    model_artifacts: list[dict[str, Any]] = []
    selection: dict[str, Any] = {}
    for horizon, horizon_table in sorted(tables.items()):
        reference = horizon_table.filter(pc.less_equal(horizon_table["season"], bounded_end_season))
        selection[horizon] = {}
        for target in targets:
        # Select modest hyperparameters on development folds only (2019-2023).
            candidates: list[tuple[float, str, dict[str, float]]] = []
            grids = (("ridge", tuple({"alpha": alpha} for alpha in RIDGE_ALPHAS)),) if "ridge" in families else ()
            for family, grid in grids:
                for params in grid:
                    errors: list[float] = []
                    cols = feature_columns(reference, "full_v1")
                    for fold in folds:
                        if fold.role != "development":
                            continue
                        predicted, _ = fit_predict_fold(reference, fold, target, family, params, cols)
                        actual = np.asarray(reference.filter(pc.equal(reference["season"], fold.evaluation_season))[target].to_pylist(), dtype=float)
                        errors.extend(np.abs(actual - predicted).tolist())
                    candidates.append((float(np.mean(errors)), family, params))
            best_by_family: dict[str, dict[str, float]] = {}
            for _, family, params in sorted(candidates, key=lambda x: (x[0], x[1], stable_hash(x[2]))):
                best_by_family.setdefault(family, params)
            selection[horizon][target] = {
                "development_selection_only": best_by_family,
                "elastic_net": {
                    "status": "deferred",
                    "reason": "The bounded predeclared grid failed to converge reliably on the wide v1 matrix; Phase 5B-3 does not promote unstable complexity.",
                    "attempted_grid": ELASTIC_GRID,
                },
            }
            for fold in folds:
                if "naive" in families:
                    for variant in ("training_mean", "home_field", "prior_team_average"):
                        pred = _prior_team_baseline(reference, fold, target) if variant == "prior_team_average" else _mean_baseline(reference, fold, target, variant)
                        all_predictions.extend(_prediction_rows(reference, fold, target, "naive", variant, pred.tolist(), manifest, {}))
                if "elo" in families and target == "target_margin":
                    prefix = reference.filter(pc.less_equal(reference["season"], fold.evaluation_season))
                    elo_columns = ["kickoff", "provider_game_id", "season", "home_program_id", "away_program_id", "neutral_site", "target_margin"]
                    elo = elo_predictions(prefix.select(elo_columns).to_pylist())[-reference.filter(pc.equal(reference["season"], fold.evaluation_season)).num_rows :]
                    all_predictions.extend(_prediction_rows(reference, fold, target, "elo", ELO_VERSION, elo, manifest, asdict(EloConfig())))
                for family, params in best_by_family.items():
                    for ablation in ablations:
                        cols = feature_columns(reference, ablation)
                        pred, artifact = fit_predict_fold(reference, fold, target, family, params, cols)
                        artifact.update({"horizon": horizon, "ablation": ablation, "dataset_hash": manifest["dataset_hash"], "feature_set_hash": manifest["feature_set_hash"]})
                        artifact["artifact_hash"] = stable_hash(artifact)
                        model_artifacts.append(artifact)
                        all_predictions.extend(_prediction_rows(reference, fold, target, family, ablation, pred.tolist(), manifest, params))
                    for variant, excluded in (
                        ("full_v1_exclude_2014_train", (2014,)),
                        ("full_v1_exclude_2021_2022_train", (2021, 2022)),
                    ):
                        if not any(season <= fold.train_end for season in excluded):
                            continue
                        cols = feature_columns(reference, "full_v1")
                        pred, artifact = fit_predict_fold(
                            reference, fold, target, family, params, cols, excluded_train_seasons=excluded
                        )
                        artifact.update({"horizon": horizon, "ablation": variant, "dataset_hash": manifest["dataset_hash"], "feature_set_hash": manifest["feature_set_hash"]})
                        artifact["artifact_hash"] = stable_hash(artifact)
                        model_artifacts.append(artifact)
                        all_predictions.extend(_prediction_rows(reference, fold, target, family, variant, pred.tolist(), manifest, {**params, "excluded_train_seasons": excluded}))
    identical = len(tables) == 1 or horizon_features_identical(tables, feature_columns(next(iter(tables.values()))))
    output_root.mkdir(parents=True, exist_ok=True)
    pred_table = prediction_table(all_predictions)
    predictions_path = output_root / "oof_predictions.parquet"
    pq.write_table(pred_table, predictions_path, compression="zstd")
    models_path = output_root / "fold_models.json"
    models_path.write_text(json.dumps(model_artifacts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = summarize_predictions(pred_table)
    run_manifest: dict[str, Any] = {
        "tournament_version": TOURNAMENT_VERSION, "seed": SEED, "network_calls": 0,
        "selected_horizons": sorted(tables), "selected_targets": list(targets), "selected_families": sorted(families),
        "dataset_hash": manifest["dataset_hash"], "feature_set_hash": manifest["feature_set_hash"],
        "availability_policy_version": manifest["availability_policy_version"], "input_audits": audits,
        "folds": [asdict(f) for f in folds], "preprocessing_version": PREPROCESSING_VERSION,
        "hyperparameter_grids": {"ridge_alpha": RIDGE_ALPHAS, "elastic_net": ELASTIC_GRID},
        "candidate_advancement_rule": {
            "primary": "2024 validation MAE and RMSE plus 2019-2023 OOF stability",
            "minimum_practical_mae_improvement": 0.10,
            "constraints": ["non-worse RMSE", "no material segment degradation", "prefer Ridge when indistinguishable"],
            "scope": "advance only to Phase 5B-4 residual/distribution research; never production or betting",
        },
        "selection": selection, "horizon_inputs_identical": identical, "predictions_rows": pred_table.num_rows,
        "predictions_schema_hash": schema_hash(pred_table.schema), "predictions_content_hash": table_content_hash(pred_table),
        "predictions_file_sha256": _sha256(predictions_path), "model_artifacts_sha256": _sha256(models_path),
        "summary": summary, "elapsed_seconds": round(time.perf_counter() - started, 3),
        "holdout_accessed": False, "provider_calls": 0,
    }
    deterministic_manifest = {key: value for key, value in run_manifest.items() if key != "elapsed_seconds"}
    run_manifest["run_hash"] = stable_hash(deterministic_manifest)
    (output_root / "run_manifest.json").write_text(json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return run_manifest


def summarize_predictions(table: pa.Table) -> dict[str, Any]:
    rows = table.to_pylist()
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["horizon"], row["target"], row["model_family"], row["variant"]), []).append(row)
    result: dict[str, Any] = {}
    for key, values in sorted(groups.items()):
        actual = np.asarray([r["actual"] for r in values], dtype=float)
        predicted = np.asarray([r["prediction"] for r in values], dtype=float)
        name = "|".join(key)
        by_season = {}
        for season in sorted({int(r["season"]) for r in values}):
            selected = [r for r in values if int(r["season"]) == season]
            by_season[str(season)] = metrics(np.asarray([r["actual"] for r in selected]), np.asarray([r["prediction"] for r in selected]))
        early = [r for r in values if int(r["week"] or 0) <= 3]
        sensitivity = [r for r in values if int(r["season"]) in {2021, 2022}]
        high_quality = [
            r for r in values
            if float(r["home_pbp_coverage_ratio"] or 0) >= 0.8
            and float(r["away_pbp_coverage_ratio"] or 0) >= 0.8
        ]
        low_quality = [
            r for r in values
            if float(r["home_pbp_coverage_ratio"] or 0) < 0.8
            or float(r["away_pbp_coverage_ratio"] or 0) < 0.8
        ]
        week_buckets = {
            "weeks_0_3": early,
            "weeks_4_8": [r for r in values if 4 <= int(r["week"] or 0) <= 8],
            "weeks_9_plus": [r for r in values if int(r["week"] or 0) >= 9],
        }
        result[name] = {
            "rows": len(values), "overall": metrics(actual, predicted), "by_season": by_season,
            "weeks_0_3": metrics(np.asarray([r["actual"] for r in early]), np.asarray([r["prediction"] for r in early])) if early else None,
            "pbp_2021_2022": metrics(np.asarray([r["actual"] for r in sensitivity]), np.asarray([r["prediction"] for r in sensitivity])) if sensitivity else None,
            "by_week_bucket": {
                name: metrics(np.asarray([r["actual"] for r in selected]), np.asarray([r["prediction"] for r in selected]))
                for name, selected in week_buckets.items() if selected
            },
            "feature_quality": {
                "high": metrics(np.asarray([r["actual"] for r in high_quality]), np.asarray([r["prediction"] for r in high_quality])) if high_quality else None,
                "low": metrics(np.asarray([r["actual"] for r in low_quality]), np.asarray([r["prediction"] for r in low_quality])) if low_quality else None,
                "high_rows": len(high_quality), "low_rows": len(low_quality),
            },
            "residuals": residual_diagnostics(actual, predicted),
        }
    return result


def validate_run(output_root: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    predictions = pq.read_table(output_root / "oof_predictions.parquet")
    if max(predictions["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked holdout accessed")
    if predictions.num_rows != manifest["predictions_rows"]:
        errors.append("prediction row count mismatch")
    if schema_hash(predictions.schema) != manifest["predictions_schema_hash"]:
        errors.append("prediction schema mismatch")
    if table_content_hash(predictions) != manifest["predictions_content_hash"]:
        errors.append("prediction content mismatch")
    if _sha256(output_root / "oof_predictions.parquet") != manifest["predictions_file_sha256"]:
        errors.append("prediction file hash mismatch")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
