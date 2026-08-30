from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import schema_hash, table_content_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.probability import (
    EMPIRICAL_DISCRETE_MARGIN_VERSION,
    HETEROSKEDASTIC_VERSION,
    EmpiricalDiscreteDistribution,
    discrete_crps,
    empirical_discrete_distribution,
    fit_empirical_discrete_ratios,
    grouped_scale,
    multiclass_scores,
    normal_integer_lattice,
    quality_group,
    spread_probabilities,
)

KEY_NUMBER_TOURNAMENT_VERSION = "ncaaf-key-number-tournament-v1"
SEED = 53106
FIRST_EVALUATION_SEASON = 2020
MIN_POOL_ROWS = 400
KEY_NUMBERS = (3, 7, 10, 14)
SPREAD_GRID = (-2.5, -3.0, -3.5, -6.5, -7.0, -7.5, -9.5, -10.0, -10.5, -13.5, -14.0, -14.5)
INTERVAL_LEVELS = (0.50, 0.80, 0.90, 0.95)


def _margin_rows(table: pa.Table, *, end_season: int = 2024) -> list[dict[str, Any]]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter key-number evaluation")
    mask = pc.and_(
        pc.and_(pc.equal(table["target"], "margin"), pc.equal(table["model_family"], "elo")),
        pc.and_(
            pc.equal(table["variant"], "ncaaf-margin-power-v1"),
            pc.less_equal(table["season"], end_season),
        ),
    )
    columns = (
        "canonical_event_id", "provider_game_id", "season", "week", "kickoff", "horizon", "actual",
        "prediction", "residual", "fold_id", "training_cutoff", "dataset_hash", "feature_set_hash",
        "home_pbp_coverage_ratio", "away_pbp_coverage_ratio", "covid_2020_regime",
    )
    rows = table.filter(mask).select(columns).to_pylist()
    if not rows or max(int(row["season"]) for row in rows) >= 2025:
        raise ValueError("valid sealed development margin rows are unavailable")
    return sorted(rows, key=lambda row: (row["horizon"], row["season"], row["kickoff"], row["provider_game_id"]))


def _quality_label(row: Mapping[str, Any]) -> str:
    return quality_group(
        week=int(row["week"]),
        home_pbp_coverage=row.get("home_pbp_coverage_ratio"),
        away_pbp_coverage=row.get("away_pbp_coverage_ratio"),
    )


def fit_prior_discrete_pool(
    historical_rows: Sequence[Mapping[str, Any]],
    *,
    evaluation_season: int,
) -> tuple[float, float, Mapping[str, float], np.ndarray, np.ndarray, str]:
    if len(historical_rows) < MIN_POOL_ROWS:
        raise ValueError(f"key-number residual pool requires at least {MIN_POOL_ROWS} rows")
    if any(int(row["season"]) >= evaluation_season for row in historical_rows):
        raise ValueError("future outcomes cannot enter an empirical-discrete pool")
    residuals = [float(row["residual"]) for row in historical_rows]
    location, global_scale, scales = grouped_scale(residuals, [_quality_label(row) for row in historical_rows])
    locations = [float(row["prediction"]) + location for row in historical_rows]
    row_scales = [float(scales.get(_quality_label(row), global_scale)) for row in historical_rows]
    actuals = [float(row["actual"]) for row in historical_rows]
    support, ratios = fit_empirical_discrete_ratios(actuals, locations, row_scales)
    pool_id = stable_hash(
        {
            "version": EMPIRICAL_DISCRETE_MARGIN_VERSION,
            "evaluation_season": evaluation_season,
            "horizon": historical_rows[0]["horizon"],
            "game_ids": [row["provider_game_id"] for row in historical_rows],
            "actuals": actuals,
            "locations": locations,
            "scales": row_scales,
            "ratios": ratios.tolist(),
        }
    )
    return location, global_scale, scales, support, ratios, pool_id


def _baseline_discrete(location: float, scale: float, *, pool_id: str) -> EmpiricalDiscreteDistribution:
    support, mass = normal_integer_lattice(location, scale)
    return EmpiricalDiscreteDistribution(support, mass, pool_id, family=HETEROSKEDASTIC_VERSION)


def _settlement_outcome(actual: float, home_line: float) -> str:
    settled = actual + home_line
    if settled > 0:
        return "win"
    if settled < 0:
        return "loss"
    return "push"


def _probability_row(
    row: Mapping[str, Any],
    distribution: EmpiricalDiscreteDistribution,
    *,
    family: str,
    evaluation_season: int,
    pool_rows: int,
) -> dict[str, Any]:
    actual = float(row["actual"])
    intervals: dict[str, float] = {}
    for level in INTERVAL_LEVELS:
        tail = (1.0 - level) / 2
        low, high = distribution.ppf(tail), distribution.ppf(1.0 - tail)
        intervals[f"interval_{int(level * 100)}_covered"] = float(low <= actual <= high)
        intervals[f"interval_{int(level * 100)}_width"] = high - low
    key_mass = {str(number): distribution.pdf(float(number)) for number in KEY_NUMBERS}
    spread_rows: dict[str, Any] = {}
    for line in SPREAD_GRID:
        probabilities = spread_probabilities(distribution, line)
        outcome = _settlement_outcome(actual, line)
        scores = multiclass_scores(probabilities, outcome)
        spread_rows[str(line)] = {
            "win": probabilities.win, "push": probabilities.push, "loss": probabilities.loss,
            "outcome": outcome, "multiclass_brier": scores["brier"],
            "multiclass_log_loss": scores["log_loss"],
        }
    return {
        "canonical_event_id": row["canonical_event_id"], "provider_game_id": row["provider_game_id"],
        "season": row["season"], "week": row["week"], "kickoff": row["kickoff"],
        "horizon": row["horizon"], "actual_margin": actual,
        "point_prediction": float(row["prediction"]), "predicted_location": distribution.location,
        "predicted_scale": distribution.scale, "distribution_family": family,
        "distribution_version": KEY_NUMBER_TOURNAMENT_VERSION, "pool_id": distribution.pool_id,
        "pool_rows": pool_rows, "nll": -math.log(distribution.pdf(actual)),
        "discrete_crps": discrete_crps(distribution, actual),
        "key_number_mass": json.dumps(key_mass, sort_keys=True),
        "spread_probabilities": json.dumps(spread_rows, sort_keys=True),
        "quality_group": _quality_label(row), "fold_id": row["fold_id"],
        "training_cutoff": evaluation_season - 1, "dataset_hash": row["dataset_hash"],
        "feature_set_hash": row["feature_set_hash"], "covid_2020_regime": row["covid_2020_regime"],
        **intervals,
    }


def build_key_number_rows(
    baseline_predictions: pa.Table,
    *,
    end_season: int = 2024,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = _margin_rows(baseline_predictions, end_season=end_season)
    output: list[dict[str, Any]] = []
    pools: list[dict[str, Any]] = []
    for horizon in sorted({str(row["horizon"]) for row in source}):
        horizon_rows = [row for row in source if row["horizon"] == horizon]
        for season in range(FIRST_EVALUATION_SEASON, end_season + 1):
            history = [row for row in horizon_rows if int(row["season"]) < season]
            evaluation = [row for row in horizon_rows if int(row["season"]) == season]
            location, global_scale, scales, support, ratios, pool_id = fit_prior_discrete_pool(
                history, evaluation_season=season
            )
            pools.append(
                {
                    "pool_id": pool_id, "horizon": horizon, "evaluation_season": season,
                    "training_cutoff": season - 1, "rows": len(history), "residual_location": location,
                    "global_scale": global_scale, "group_scales": dict(scales),
                    "support_min": int(support[0]), "support_max": int(support[-1]),
                    "ratios": ratios.tolist(), "ratio_min": float(np.min(ratios)),
                    "ratio_max": float(np.max(ratios)),
                }
            )
            for row in evaluation:
                scale = float(scales.get(_quality_label(row), global_scale))
                predicted_location = float(row["prediction"]) + location
                normal = _baseline_discrete(predicted_location, scale, pool_id=f"normal:{pool_id}")
                empirical = empirical_discrete_distribution(
                    predicted_location, scale, support, ratios, pool_id=pool_id
                )
                output.append(
                    _probability_row(
                        row, normal, family=HETEROSKEDASTIC_VERSION,
                        evaluation_season=season, pool_rows=len(history),
                    )
                )
                output.append(
                    _probability_row(
                        row, empirical, family=EMPIRICAL_DISCRETE_MARGIN_VERSION,
                        evaluation_season=season, pool_rows=len(history),
                    )
                )
    return output, pools


def _paired_bootstrap(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    score: str,
    *,
    iterations: int = 2_000,
) -> dict[str, Any]:
    left = {(row["provider_game_id"], row["season"]): float(row[score]) for row in rows_a}
    right = {(row["provider_game_id"], row["season"]): float(row[score]) for row in rows_b}
    keys = sorted(left.keys() & right.keys(), key=lambda item: (item[1], item[0]))
    seasons = sorted({int(season) for _, season in keys})
    differences = {
        season: np.asarray([left[key] - right[key] for key in keys if int(key[1]) == season])
        for season in seasons
    }
    rng = np.random.default_rng(SEED)
    samples = np.asarray(
        [
            np.mean(np.concatenate([differences[int(s)] for s in rng.choice(seasons, len(seasons), replace=True)]))
            for _ in range(iterations)
        ]
    )
    return {
        "paired_rows": len(keys), "difference_empirical_minus_normal": float(np.mean(np.concatenate(list(differences.values())))),
        "ci_2_5": float(np.quantile(samples, 0.025)), "ci_97_5": float(np.quantile(samples, 0.975)),
    }


def summarize_key_number_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for horizon in sorted({str(row["horizon"]) for row in rows}):
        summary[horizon] = {}
        for family in (HETEROSKEDASTIC_VERSION, EMPIRICAL_DISCRETE_MARGIN_VERSION):
            selected = [row for row in rows if row["horizon"] == horizon and row["distribution_family"] == family]
            summary[horizon][family] = {
                "rows": len(selected), "mean_nll": float(np.mean([row["nll"] for row in selected])),
                "mean_discrete_crps": float(np.mean([row["discrete_crps"] for row in selected])),
                "interval_90_coverage": float(np.mean([row["interval_90_covered"] for row in selected])),
                "interval_90_width": float(np.mean([row["interval_90_width"] for row in selected])),
                "keys": {
                    str(number): {
                        "mean_predicted_mass": float(np.mean([json.loads(row["key_number_mass"])[str(number)] for row in selected])),
                        "observed_frequency": float(np.mean([math.isclose(float(row["actual_margin"]), number) for row in selected])),
                        "calibration_gap": float(
                            np.mean([json.loads(row["key_number_mass"])[str(number)] for row in selected])
                            - np.mean([math.isclose(float(row["actual_margin"]), number) for row in selected])
                        ),
                        "rows": len(selected),
                    } for number in KEY_NUMBERS
                },
                "spreads": {
                    str(line): {
                        "mean_predicted_push": float(np.mean([json.loads(row["spread_probabilities"])[str(line)]["push"] for row in selected])),
                        "observed_push": float(np.mean([json.loads(row["spread_probabilities"])[str(line)]["outcome"] == "push" for row in selected])),
                        "multiclass_brier": float(np.mean([json.loads(row["spread_probabilities"])[str(line)]["multiclass_brier"] for row in selected])),
                        "multiclass_log_loss": float(np.mean([json.loads(row["spread_probabilities"])[str(line)]["multiclass_log_loss"] for row in selected])),
                    } for line in SPREAD_GRID
                },
            }
        empirical = [row for row in rows if row["horizon"] == horizon and row["distribution_family"] == EMPIRICAL_DISCRETE_MARGIN_VERSION]
        normal = [row for row in rows if row["horizon"] == horizon and row["distribution_family"] == HETEROSKEDASTIC_VERSION]
        summary[horizon]["paired"] = {
            "nll": _paired_bootstrap(empirical, normal, "nll"),
            "discrete_crps": _paired_bootstrap(empirical, normal, "discrete_crps"),
        }
    return summary


def run_key_number_tournament(
    baseline_root: Path,
    output_root: Path,
    *,
    end_season: int = 2024,
) -> dict[str, Any]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter key-number tournament")
    started = time.perf_counter()
    baseline_manifest = json.loads((baseline_root / "run_manifest.json").read_text(encoding="utf-8"))
    predictions = pq.read_table(baseline_root / "oof_predictions.parquet")
    rows, pools = build_key_number_rows(predictions, end_season=end_season)
    table = pa.Table.from_pylist(rows).sort_by(
        [(name, "ascending") for name in ("horizon", "distribution_family", "kickoff", "provider_game_id")]
    )
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "oof_key_number_probabilities.parquet"
    pq.write_table(table, path, compression="zstd")
    pools_path = output_root / "empirical_discrete_pools.json"
    pools_path.write_text(json.dumps(pools, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest: dict[str, Any] = {
        "tournament_version": KEY_NUMBER_TOURNAMENT_VERSION,
        "experiment_plan": "docs/NCAAF_STRONG_MODEL_EXPERIMENT_PLAN.md",
        "baseline_run_hash": baseline_manifest["run_hash"], "dataset_hash": baseline_manifest["dataset_hash"],
        "feature_set_hash": baseline_manifest["feature_set_hash"], "evaluation_seasons": [2020, end_season],
        "horizons": sorted({str(row["horizon"]) for row in rows}), "minimum_pool_rows": MIN_POOL_ROWS,
        "key_numbers": list(KEY_NUMBERS), "spread_grid": list(SPREAD_GRID),
        "probability_rows": table.num_rows, "pool_count": len(pools),
        "probability_schema_hash": schema_hash(table.schema), "probability_content_hash": table_content_hash(table),
        "probability_file_sha256": _sha256(path), "pools_file_sha256": _sha256(pools_path),
        "summary": summarize_key_number_rows(rows), "provider_calls": 0, "holdout_accessed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    deterministic = {key: value for key, value in manifest.items() if key != "elapsed_seconds"}
    manifest["run_hash"] = stable_hash(deterministic)
    (output_root / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_key_number_run(output_root: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    table = pq.read_table(output_root / "oof_key_number_probabilities.parquet")
    if table.num_rows != manifest["probability_rows"]:
        errors.append("key-number row count mismatch")
    if max(table["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked holdout accessed")
    if table_content_hash(table) != manifest["probability_content_hash"]:
        errors.append("key-number content mismatch")
    for payload in table["spread_probabilities"].to_pylist():
        for line, probabilities in json.loads(payload).items():
            total = probabilities["win"] + probabilities["push"] + probabilities["loss"]
            if not math.isclose(total, 1.0, abs_tol=1e-10):
                errors.append(f"spread probabilities do not sum to one: {line}")
                return errors
            if not float(line).is_integer() and probabilities["push"] != 0:
                errors.append(f"half-point push is nonzero: {line}")
                return errors
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
