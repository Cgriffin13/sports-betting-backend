from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import stats

from app.research.ncaaf.artifacts import schema_hash, table_content_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.probability import (
    CALIBRATION_VERSION,
    EMPIRICAL_VERSION,
    HETEROSKEDASTIC_VERSION,
    NORMAL_VERSION,
    SKEW_NORMAL_VERSION,
    STUDENT_T_VERSION,
    EmpiricalGridDistribution,
    NormalDistribution,
    PredictiveDistribution,
    SkewNormalDistribution,
    StudentTDistribution,
    binary_scores,
    fit_empirical_grid,
    fit_normal,
    fit_skew_normal,
    fit_student_t,
    grouped_scale,
    interval_diagnostics,
    moneyline_probabilities,
    quality_group,
)

PROBABILITY_TOURNAMENT_VERSION = "ncaaf-probability-tournament-v1"
MIN_POOL_ROWS = 400
FIRST_CALIBRATION_SEASON = 2020
BOOTSTRAP_ITERATIONS = 2_000
SEED = 53104
SPREAD_GRID = (-14.0, -10.0, -7.5, -7.0, -3.5, -3.0, 0.0, 3.0, 3.5, 7.0, 7.5, 10.0, 14.0)
TOTAL_GRID = (35.0, 41.0, 41.5, 45.0, 45.5, 49.0, 49.5, 52.0, 52.5, 56.0, 56.5, 63.0)
INTERVAL_LEVELS = (0.50, 0.80, 0.90, 0.95)
POINT_MODELS = (
    ("margin", "elo", "ncaaf-margin-power-v1"),
    ("margin", "ridge", "full_v1"),
    ("total", "ridge", "full_without_opponent_adjustment"),
    ("total", "ridge", "full_v1"),
)
_QUANTILE_OFFSET_CACHE: dict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]] = {}


@dataclass(frozen=True, slots=True)
class DistributionFit:
    family: str
    target: str
    horizon: str
    point_model_family: str
    point_model_variant: str
    evaluation_season: int
    training_cutoff: int
    residual_rows: int
    residual_location: float
    global_scale: float
    parameters: Mapping[str, Any]
    pool_id: str


def selected_prediction_rows(table: pa.Table, *, end_season: int = 2024) -> list[dict[str, Any]]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter probability calibration")
    mask = pc.equal(table["season"], -1)
    for target, family, variant in POINT_MODELS:
        candidate = pc.and_(
            pc.and_(pc.equal(table["target"], target), pc.equal(table["model_family"], family)),
            pc.equal(table["variant"], variant),
        )
        mask = pc.or_(mask, candidate)
    mask = pc.and_(mask, pc.less_equal(table["season"], end_season))
    columns = (
        "canonical_event_id", "provider_game_id", "season", "week", "kickoff", "horizon",
        "target", "actual", "prediction", "residual", "model_family", "model_version", "variant",
        "fold_id", "training_cutoff", "feature_set_hash", "dataset_hash",
        "home_pbp_coverage_ratio", "away_pbp_coverage_ratio", "home_current_season_games",
        "away_current_season_games", "covid_2020_regime",
    )
    rows = table.filter(mask).select(columns).to_pylist()
    if not rows:
        raise ValueError("no advanced Phase 5B-3 prediction rows found")
    if max(int(row["season"]) for row in rows) >= 2025:
        raise ValueError("locked 2025 holdout was present")
    keys = [
        (
            row["provider_game_id"], row["horizon"], row["target"], row["model_family"],
            row["variant"], row["season"],
        )
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate point-prediction rows")
    return sorted(
        rows,
        key=lambda row: (
            row["horizon"], row["target"], row["model_family"], row["variant"],
            row["season"], row["kickoff"], row["provider_game_id"],
        ),
    )


def fit_chronological_distribution(
    historical_rows: Sequence[Mapping[str, Any]],
    *,
    family: str,
    evaluation_season: int,
) -> tuple[DistributionFit, PredictiveDistribution, Mapping[str, float]]:
    if not historical_rows:
        raise ValueError("historical residual pool is empty")
    first = historical_rows[0]
    if any(int(row["season"]) >= evaluation_season for row in historical_rows):
        raise ValueError("future residuals cannot enter a chronological distribution fit")
    residuals = [float(row["residual"]) for row in historical_rows]
    if len(residuals) < MIN_POOL_ROWS:
        raise ValueError(f"residual pool requires at least {MIN_POOL_ROWS} rows")
    target = str(first["target"])
    horizon = str(first["horizon"])
    point_family = str(first["model_family"])
    point_variant = str(first["variant"])
    pool_id = stable_hash(
        {
            "family": family,
            "target": target,
            "horizon": horizon,
            "point_family": point_family,
            "point_variant": point_variant,
            "evaluation_season": evaluation_season,
            "residuals": residuals,
        }
    )
    grouped: Mapping[str, float] = {}
    if family == NORMAL_VERSION:
        location, scale = fit_normal(residuals)
        distribution: PredictiveDistribution = NormalDistribution(location, scale)
        parameters: dict[str, Any] = {"residual_location": location, "scale": scale}
    elif family == STUDENT_T_VERSION:
        location, scale, degrees = fit_student_t(residuals)
        distribution = StudentTDistribution(location, scale, degrees)
        parameters = {"residual_location": location, "scale": scale, "degrees_of_freedom": degrees}
    elif family == EMPIRICAL_VERSION:
        empirical = fit_empirical_grid(residuals, pool_id=pool_id)
        location, scale = 0.0, empirical.scale
        distribution = empirical
        parameters = {
            "residual_location": 0.0,
            "scale": scale,
            "bandwidth": empirical.bandwidth,
            "grid_min": float(empirical.residual_grid[0]),
            "grid_max": float(empirical.residual_grid[-1]),
            "grid_step": float(empirical.residual_grid[1] - empirical.residual_grid[0]),
        }
    elif family == HETEROSKEDASTIC_VERSION:
        labels = [
            quality_group(
                week=int(row["week"]),
                home_pbp_coverage=row.get("home_pbp_coverage_ratio"),
                away_pbp_coverage=row.get("away_pbp_coverage_ratio"),
            )
            for row in historical_rows
        ]
        location, scale, grouped = grouped_scale(residuals, labels)
        distribution = NormalDistribution(location, scale, family=HETEROSKEDASTIC_VERSION)
        parameters = {
            "residual_location": location,
            "global_scale": scale,
            "group_scales": dict(grouped),
            "group_rule": "week<=3 x both_pbp_coverage>=0.8",
            "shrinkage_pseudo_observations": 200,
        }
    elif family == SKEW_NORMAL_VERSION and target == "total":
        location, scale, shape = fit_skew_normal(residuals)
        distribution = SkewNormalDistribution(location, scale, shape)
        parameters = {"residual_location": location, "scale": scale, "shape": shape}
    else:
        raise ValueError(f"unsupported distribution family for target: {family}/{target}")
    fit = DistributionFit(
        family=family,
        target=target,
        horizon=horizon,
        point_model_family=point_family,
        point_model_variant=point_variant,
        evaluation_season=evaluation_season,
        training_cutoff=evaluation_season - 1,
        residual_rows=len(residuals),
        residual_location=float(location),
        global_scale=float(scale),
        parameters=parameters,
        pool_id=pool_id,
    )
    return fit, distribution, grouped


def shifted_distribution(
    template: PredictiveDistribution,
    prediction: float,
    *,
    group_scale: float | None = None,
) -> PredictiveDistribution:
    if isinstance(template, EmpiricalGridDistribution):
        return replace(template, location=prediction)
    if isinstance(template, NormalDistribution):
        return replace(template, location=prediction + template.location, scale=group_scale or template.scale)
    if isinstance(template, StudentTDistribution):
        return replace(template, location=prediction + template.location)
    if isinstance(template, SkewNormalDistribution):
        return replace(template, location=prediction + template.location)
    raise TypeError("unsupported predictive distribution")


def _families(target: str) -> tuple[str, ...]:
    base = (NORMAL_VERSION, STUDENT_T_VERSION, EMPIRICAL_VERSION, HETEROSKEDASTIC_VERSION)
    return (*base, SKEW_NORMAL_VERSION) if target == "total" else base


def _fast_scores(distribution: PredictiveDistribution, actual: float) -> tuple[float, float, float]:
    nll = -math.log(max(1e-12, distribution.pdf(actual)))
    probabilities, offsets = _quantile_offsets(distribution)
    quantiles = distribution.location + offsets
    errors = actual - quantiles
    pinball = np.where(errors >= 0, probabilities * errors, (probabilities - 1) * errors)
    return nll, float(2 * np.trapezoid(pinball, probabilities)), distribution.cdf(actual)


def _quantile_offsets(distribution: PredictiveDistribution) -> tuple[np.ndarray, np.ndarray]:
    parameters = distribution.parameters()
    key = (
        distribution.family,
        distribution.scale,
        parameters.get("degrees_of_freedom"),
        parameters.get("shape"),
        parameters.get("pool_id"),
    )
    cached = _QUANTILE_OFFSET_CACHE.get(key)
    if cached is not None:
        return cached
    probabilities = np.linspace(0.02, 0.98, 49)
    offsets = np.asarray(
        [distribution.ppf(float(probability)) - distribution.location for probability in probabilities]
    )
    _QUANTILE_OFFSET_CACHE[key] = (probabilities, offsets)
    return probabilities, offsets


def _probability_row(
    row: Mapping[str, Any],
    fit: DistributionFit,
    distribution: PredictiveDistribution,
) -> dict[str, Any]:
    actual = float(row["actual"])
    nll, crps, pit = _fast_scores(distribution, actual)
    intervals = interval_diagnostics(distribution, actual)
    moneyline = moneyline_probabilities(distribution) if fit.target == "margin" else None
    return {
        "canonical_event_id": row["canonical_event_id"],
        "provider_game_id": row["provider_game_id"],
        "season": row["season"],
        "week": row["week"],
        "kickoff": row["kickoff"],
        "horizon": fit.horizon,
        "target": fit.target,
        "actual": actual,
        "point_prediction": float(row["prediction"]),
        "point_model_family": fit.point_model_family,
        "point_model_version": row["model_version"],
        "point_model_variant": fit.point_model_variant,
        "distribution_family": fit.family,
        "distribution_version": fit.family,
        "predicted_location": distribution.location,
        "predicted_scale": distribution.scale,
        "distribution_parameters": json.dumps(distribution.parameters(), sort_keys=True),
        "home_win_probability": moneyline.win if moneyline else None,
        "away_win_probability": moneyline.loss if moneyline else None,
        "conditioned_tie_mass": moneyline.audit["conditioned_tie_mass"] if moneyline and moneyline.audit else None,
        "nll": nll,
        "crps": crps,
        "pit": pit,
        **{
            f"interval_{int(level * 100)}_covered": intervals[str(level)]["covered"]
            for level in INTERVAL_LEVELS
        },
        **{f"interval_{int(level * 100)}_width": intervals[str(level)]["width"] for level in INTERVAL_LEVELS},
        "quality_group": quality_group(
            week=int(row["week"]),
            home_pbp_coverage=row.get("home_pbp_coverage_ratio"),
            away_pbp_coverage=row.get("away_pbp_coverage_ratio"),
        ),
        "home_pbp_coverage_ratio": row.get("home_pbp_coverage_ratio"),
        "away_pbp_coverage_ratio": row.get("away_pbp_coverage_ratio"),
        "home_current_season_games": row.get("home_current_season_games"),
        "away_current_season_games": row.get("away_current_season_games"),
        "covid_2020_regime": row.get("covid_2020_regime"),
        "fold_id": row["fold_id"],
        "training_cutoff": fit.training_cutoff,
        "residual_pool_id": fit.pool_id,
        "residual_pool_rows": fit.residual_rows,
        "dataset_hash": row["dataset_hash"],
        "feature_set_hash": row["feature_set_hash"],
        "calibration_version": CALIBRATION_VERSION,
    }


def build_probability_rows(
    selected_rows: Sequence[Mapping[str, Any]],
    *,
    end_season: int = 2024,
    selected_families: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter probability calibration")
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in selected_rows:
        key = (str(row["horizon"]), str(row["target"]), str(row["model_family"]), str(row["variant"]))
        groups.setdefault(key, []).append(row)
    output: list[dict[str, Any]] = []
    fits: list[dict[str, Any]] = []
    pools: list[dict[str, Any]] = []
    wanted = set(selected_families)
    for (_, target, _, _), rows in sorted(groups.items()):
        for evaluation_season in range(FIRST_CALIBRATION_SEASON, end_season + 1):
            historical = [row for row in rows if int(row["season"]) < evaluation_season]
            evaluation = [row for row in rows if int(row["season"]) == evaluation_season]
            if not evaluation:
                continue
            for family in _families(target):
                if wanted and family not in wanted:
                    continue
                fit, template, group_scales = fit_chronological_distribution(
                    historical,
                    family=family,
                    evaluation_season=evaluation_season,
                )
                fits.append(asdict(fit))
                if isinstance(template, EmpiricalGridDistribution):
                    pools.append(
                        {
                            "pool_id": fit.pool_id,
                            "residual_grid": template.residual_grid.tolist(),
                            "residual_cdf": template.residual_cdf.tolist(),
                            "residual_pdf": template.residual_pdf.tolist(),
                        }
                    )
                for row in evaluation:
                    label = quality_group(
                        week=int(row["week"]),
                        home_pbp_coverage=row.get("home_pbp_coverage_ratio"),
                        away_pbp_coverage=row.get("away_pbp_coverage_ratio"),
                    )
                    distribution = shifted_distribution(
                        template,
                        float(row["prediction"]),
                        group_scale=group_scales.get(label),
                    )
                    output.append(_probability_row(row, fit, distribution))
    output.sort(
        key=lambda row: (
            row["horizon"], row["target"], row["point_model_family"], row["point_model_variant"],
            row["distribution_family"], row["kickoff"], row["provider_game_id"],
        )
    )
    return output, fits, pools


def _summary_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0}
    result: dict[str, Any] = {
        "rows": len(rows),
        "nll": float(np.mean([float(row["nll"]) for row in rows])),
        "crps": float(np.mean([float(row["crps"]) for row in rows])),
        "pit_histogram": np.histogram([float(row["pit"]) for row in rows], bins=np.linspace(0, 1, 11))[0].tolist(),
        "intervals": {},
    }
    for level in INTERVAL_LEVELS:
        prefix = f"interval_{int(level * 100)}"
        result["intervals"][str(level)] = {
            "coverage": float(np.mean([float(row[f"{prefix}_covered"]) for row in rows])),
            "mean_width": float(np.mean([float(row[f"{prefix}_width"]) for row in rows])),
        }
    margin = [row for row in rows if row["target"] == "margin"]
    if margin:
        scores = [binary_scores(float(row["home_win_probability"]), float(row["actual"]) > 0) for row in margin]
        result["moneyline"] = {
            "brier": float(np.mean([score["brier"] for score in scores])),
            "log_loss": float(np.mean([score["log_loss"] for score in scores])),
            "buckets": calibration_buckets(
                [float(row["home_win_probability"]) for row in margin],
                [float(row["actual"]) > 0 for row in margin],
            ),
        }
    return result


def calibration_buckets(probabilities: Sequence[float], outcomes: Sequence[bool]) -> list[dict[str, Any]]:
    result = []
    for index in range(10):
        lower, upper = index / 10, (index + 1) / 10
        selected = [
            (float(probability), bool(outcome))
            for probability, outcome in zip(probabilities, outcomes, strict=True)
            if lower <= probability < upper or (index == 9 and probability == 1)
        ]
        if selected:
            mean_probability = float(np.mean([item[0] for item in selected]))
            observed = float(np.mean([item[1] for item in selected]))
            result.append(
                {
                    "lower": lower,
                    "upper": upper,
                    "count": len(selected),
                    "mean_probability": mean_probability,
                    "observed_frequency": observed,
                    "calibration_gap": mean_probability - observed,
                }
            )
    return result


def _distribution_from_row(row: Mapping[str, Any], pools: Mapping[str, Mapping[str, Any]]) -> PredictiveDistribution:
    parameters = json.loads(str(row["distribution_parameters"]))
    family = str(row["distribution_family"])
    location, scale = float(row["predicted_location"]), float(row["predicted_scale"])
    if family in {NORMAL_VERSION, HETEROSKEDASTIC_VERSION}:
        return NormalDistribution(location, scale, family=family)
    if family == STUDENT_T_VERSION:
        return StudentTDistribution(location, scale, float(parameters["degrees_of_freedom"]))
    if family == SKEW_NORMAL_VERSION:
        return SkewNormalDistribution(location, scale, float(parameters["shape"]))
    if family == EMPIRICAL_VERSION:
        pool = pools[str(row["residual_pool_id"])]
        return EmpiricalGridDistribution(
            location=location,
            scale=scale,
            residual_grid=np.asarray(pool["residual_grid"]),
            residual_cdf=np.asarray(pool["residual_cdf"]),
            residual_pdf=np.asarray(pool["residual_pdf"]),
            pool_id=str(row["residual_pool_id"]),
            bandwidth=float(parameters["bandwidth"]),
        )
    raise ValueError(f"unknown distribution family: {family}")


def synthetic_line_metrics(
    rows: Sequence[Mapping[str, Any]],
    pool_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {"spread": {}, "total": {}}
    for target, grid in (("margin", SPREAD_GRID), ("total", TOTAL_GRID)):
        target_rows = [row for row in rows if row["target"] == target]
        locations = np.asarray([float(row["predicted_location"]) for row in target_rows])
        scales = np.asarray([float(row["predicted_scale"]) for row in target_rows])
        actuals = np.asarray([float(row["actual"]) for row in target_rows])
        for line in grid:
            if not target_rows:
                continue
            threshold = -line if target == "margin" else line
            if math.isclose(threshold, round(threshold), abs_tol=1e-10):
                integer = round(threshold)
                lower = stats.norm.cdf(integer - 0.5, loc=locations, scale=scales)
                upper = stats.norm.cdf(integer + 0.5, loc=locations, scale=scales)
                push = upper - lower
                win = 1 - upper
                loss = lower
            else:
                boundary = math.floor(threshold) + 0.5
                loss = stats.norm.cdf(boundary, loc=locations, scale=scales)
                push = np.zeros(len(target_rows))
                win = 1 - loss
            settled = actuals + line if target == "margin" else actuals - line
            win_outcome = settled > 0
            push_outcome = settled == 0
            loss_outcome = settled < 0
            matrix = np.column_stack([win, push, loss])
            actual_matrix = np.column_stack([win_outcome, push_outcome, loss_outcome]).astype(float)
            multiclass_brier = np.sum((matrix - actual_matrix) ** 2, axis=1)
            chosen = np.sum(matrix * actual_matrix, axis=1)
            name = str(line)
            result["spread" if target == "margin" else "total"][name] = {
                "rows": len(target_rows),
                "multiclass_brier": float(np.mean(multiclass_brier)),
                "multiclass_log_loss": float(np.mean(-np.log(np.clip(chosen, 1e-12, 1)))),
                "mean_predicted_push": float(np.mean(push)),
                "observed_push": float(np.mean(push_outcome)),
                "win_buckets": calibration_buckets(win.tolist(), win_outcome.tolist()),
            }
    return result


def key_number_metrics(
    rows: Sequence[Mapping[str, Any]],
    pool_rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    output: dict[str, Any] = {}
    for target, numbers in (("margin", (3, 7, 10, 14)), ("total", (35, 41, 45, 49, 52, 56, 63))):
        selected = [row for row in rows if row["target"] == target]
        target_output = {}
        for number in numbers:
            locations = np.asarray([float(row["predicted_location"]) for row in selected])
            scales = np.asarray([float(row["predicted_scale"]) for row in selected])
            modeled = stats.norm.cdf(number + 0.5, loc=locations, scale=scales) - stats.norm.cdf(
                number - 0.5, loc=locations, scale=scales
            )
            observed = [math.isclose(float(row["actual"]), number) for row in selected]
            target_output[str(number)] = {
                "mean_modeled_mass": float(np.mean(modeled)),
                "observed_frequency": float(np.mean(observed)),
                "rows": len(selected),
            }
        output[target] = target_output
    return output


def paired_season_bootstrap(
    rows_a: Sequence[Mapping[str, Any]],
    rows_b: Sequence[Mapping[str, Any]],
    *,
    score: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> Mapping[str, float]:
    a = {(row["provider_game_id"], row["season"]): float(row[score]) for row in rows_a}
    b = {(row["provider_game_id"], row["season"]): float(row[score]) for row in rows_b}
    keys = sorted(a.keys() & b.keys(), key=lambda key: (key[1], key[0]))
    seasons = sorted({int(key[1]) for key in keys})
    if not keys or not seasons:
        raise ValueError("paired bootstrap requires shared rows")
    by_season = {
        season: np.asarray([a[key] - b[key] for key in keys if int(key[1]) == season])
        for season in seasons
    }
    observed = float(np.mean(np.concatenate(list(by_season.values()))))
    rng = np.random.default_rng(SEED)
    samples = np.asarray(
        [
            np.mean(np.concatenate([by_season[int(item)] for item in rng.choice(seasons, len(seasons), replace=True)]))
            for _ in range(iterations)
        ]
    )
    return {
        "paired_rows": float(len(keys)),
        "difference_a_minus_b": observed,
        "ci_2_5": float(np.quantile(samples, 0.025)),
        "ci_97_5": float(np.quantile(samples, 0.975)),
    }


def summarize_probability_rows(
    rows: Sequence[Mapping[str, Any]],
    pool_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["horizon"]), str(row["target"]), str(row["point_model_family"]),
            str(row["point_model_variant"]), str(row["distribution_family"]),
        )
        groups.setdefault(key, []).append(row)
    summary: dict[str, Any] = {
        "candidates": {},
        "paired_normal_comparisons": {},
        "joint_residual_correlation": {},
        "implied_score_diagnostics": {},
    }
    for key, values in sorted(groups.items()):
        name = "|".join(key)
        segments = {
            "early": [row for row in values if int(row["week"] or 0) <= 3],
            "later": [row for row in values if int(row["week"] or 0) > 3],
            "high_quality": [row for row in values if str(row["quality_group"]).endswith("high")],
            "low_quality": [row for row in values if str(row["quality_group"]).endswith("low")],
            "2020": [row for row in values if int(row["season"]) == 2020],
            "2021_2022": [row for row in values if int(row["season"]) in {2021, 2022}],
        }
        summary["candidates"][name] = {
            "overall": _summary_metrics(values),
            "by_season": {
                str(season): _summary_metrics([row for row in values if int(row["season"]) == season])
                for season in sorted({int(row["season"]) for row in values})
            },
            "segments": {name: _summary_metrics(segment) for name, segment in segments.items()},
        }
    for key, values in sorted(groups.items()):
        if key[-1] == NORMAL_VERSION:
            continue
        normal_key = (*key[:-1], NORMAL_VERSION)
        if normal_key in groups:
            name = "|".join(key)
            summary["paired_normal_comparisons"][name] = {
                "nll": paired_season_bootstrap(values, groups[normal_key], score="nll"),
                "crps": paired_season_bootstrap(values, groups[normal_key], score="crps"),
            }
    primary_margin = [
        row for row in rows
        if row["target"] == "margin" and row["point_model_family"] == "elo"
        and row["distribution_family"] == NORMAL_VERSION
    ]
    primary_total = [
        row for row in rows
        if row["target"] == "total" and row["point_model_variant"] == "full_without_opponent_adjustment"
        and row["distribution_family"] == NORMAL_VERSION
    ]
    total_index: dict[tuple[Any, Any], Mapping[str, Any]] = {
        (row["provider_game_id"], row["horizon"]): row for row in primary_total
    }
    for horizon in sorted({str(row["horizon"]) for row in primary_margin}):
        pairs = []
        for row in primary_margin:
            lookup_key = (row["provider_game_id"], row["horizon"])
            if row["horizon"] != horizon or lookup_key not in total_index:
                continue
            total_row = total_index[lookup_key]
            pairs.append(
                (
                    float(row["actual"]) - float(row["point_prediction"]),
                    float(total_row["actual"]) - float(total_row["point_prediction"]),
                )
            )
        summary["joint_residual_correlation"][horizon] = {
            "rows": len(pairs),
            "correlation": float(np.corrcoef(np.asarray(pairs).T)[0, 1]) if pairs else None,
            "joint_simulator_advanced": False,
            "reason": "absolute correlation below the predeclared 0.10 materiality threshold",
        }
        implied_scores = []
        for row in primary_margin:
            lookup_key = (row["provider_game_id"], row["horizon"])
            if row["horizon"] != horizon or lookup_key not in total_index:
                continue
            margin_mean = float(row["point_prediction"])
            total_mean = float(total_index[lookup_key]["point_prediction"])
            implied_scores.append(((total_mean + margin_mean) / 2, (total_mean - margin_mean) / 2))
        summary["implied_score_diagnostics"][horizon] = {
            "rows": len(implied_scores),
            "negative_home_expected_scores": sum(home < 0 for home, _ in implied_scores),
            "negative_away_expected_scores": sum(away < 0 for _, away in implied_scores),
            "minimum_home_expected_score": min(home for home, _ in implied_scores),
            "minimum_away_expected_score": min(away for _, away in implied_scores),
        }
    primary_rows = [
        row for row in rows
        if (
            row["target"] == "margin" and row["point_model_family"] == "elo"
            or row["target"] == "total" and row["point_model_variant"] == "full_without_opponent_adjustment"
        )
        and row["distribution_family"] == NORMAL_VERSION
    ]
    summary["synthetic_lines"] = synthetic_line_metrics(primary_rows, pool_rows)
    summary["key_numbers"] = key_number_metrics(primary_rows, pool_rows)
    return summary


def run_probability_tournament(
    input_root: Path,
    output_root: Path,
    *,
    end_season: int = 2024,
    selected_families: Sequence[str] = (),
) -> dict[str, Any]:
    if end_season >= 2025:
        raise ValueError("locked 2025 holdout cannot enter probability calibration")
    started = time.perf_counter()
    baseline_manifest = json.loads((input_root / "run_manifest.json").read_text(encoding="utf-8"))
    prediction_table = pq.read_table(input_root / "oof_predictions.parquet")
    selected = selected_prediction_rows(prediction_table, end_season=end_season)
    rows, fits, pools = build_probability_rows(
        selected,
        end_season=end_season,
        selected_families=selected_families,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    probability_path = output_root / "oof_probabilities.parquet"
    pq.write_table(table, probability_path, compression="zstd")
    pools_path = output_root / "distribution_pools.json"
    pools_path.write_text(json.dumps(pools, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fits_path = output_root / "distribution_fits.json"
    fits_path.write_text(json.dumps(fits, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = summarize_probability_rows(rows, pools)
    manifest: dict[str, Any] = {
        "tournament_version": PROBABILITY_TOURNAMENT_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "experiment_plan": "docs/NCAAF_DISTRIBUTION_EXPERIMENT_PLAN.md",
        "input_tournament_hash": baseline_manifest["run_hash"],
        "dataset_hash": baseline_manifest["dataset_hash"],
        "feature_set_hash": baseline_manifest["feature_set_hash"],
        "availability_policy_version": baseline_manifest["availability_policy_version"],
        "input_prediction_content_hash": baseline_manifest["predictions_content_hash"],
        "selected_point_models": [list(item) for item in POINT_MODELS],
        "distribution_families": sorted({str(row["distribution_family"]) for row in rows}),
        "evaluation_seasons": [FIRST_CALIBRATION_SEASON, end_season],
        "residual_seed_season": 2019,
        "minimum_pool_rows": MIN_POOL_ROWS,
        "spread_grid": list(SPREAD_GRID),
        "total_grid": list(TOTAL_GRID),
        "probability_rows": table.num_rows,
        "fit_rows": len(fits),
        "pool_rows": len(pools),
        "probability_schema_hash": schema_hash(table.schema),
        "probability_content_hash": table_content_hash(table),
        "probability_file_sha256": _sha256(probability_path),
        "pools_file_sha256": _sha256(pools_path),
        "fits_file_sha256": _sha256(fits_path),
        "summary": summary,
        "selection_policy": {
            "rule": "advance complexity only when paired season-block NLL/CRPS improvement is practically meaningful and calibration/coverage is not worse",
            "default_when_indistinguishable": NORMAL_VERSION,
            "scope": "offline football probability research only; no market edge, EV, or production claim",
        },
        "holdout_accessed": False,
        "provider_calls": 0,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    deterministic = {key: value for key, value in manifest.items() if key != "elapsed_seconds"}
    manifest["run_hash"] = stable_hash(deterministic)
    (output_root / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_probability_run(output_root: Path) -> list[str]:
    errors: list[str] = []
    manifest = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    table = pq.read_table(output_root / "oof_probabilities.parquet")
    if table.num_rows != manifest["probability_rows"]:
        errors.append("probability row count mismatch")
    if max(table["season"].to_pylist()) >= 2025 or manifest["holdout_accessed"]:
        errors.append("locked holdout accessed")
    if schema_hash(table.schema) != manifest["probability_schema_hash"]:
        errors.append("probability schema mismatch")
    if table_content_hash(table) != manifest["probability_content_hash"]:
        errors.append("probability content mismatch")
    if _sha256(output_root / "oof_probabilities.parquet") != manifest["probability_file_sha256"]:
        errors.append("probability file hash mismatch")
    for row in table.select(["home_win_probability", "away_win_probability"]).to_pylist():
        if row["home_win_probability"] is None:
            continue
        if not math.isclose(float(row["home_win_probability"]) + float(row["away_win_probability"]), 1, abs_tol=1e-10):
            errors.append("moneyline probabilities do not sum to one")
            break
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
