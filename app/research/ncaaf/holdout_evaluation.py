from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from app.research.ncaaf.artifacts import ResearchArtifactStore, table_content_hash
from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.finalist_freeze import (
    ALLOWED_CANDIDATES,
    TOTAL_RIDGE_ARTIFACT_HASH,
    TOTAL_RIDGE_BLEND_WEIGHT,
    decide_total_blend,
    validate_local_artifacts,
)
from app.research.ncaaf.holdout import EXPECTED_FREEZE_HASH, load_unlock_record
from app.research.ncaaf.market_comparison import build_consensus_rows
from app.research.ncaaf.modeling import elo_predictions
from app.research.ncaaf.probability import fit_empirical_grid, multiclass_scores, total_probabilities

HOLDOUT_VERSION = "ncaaf-2025-locked-holdout-v1"
SEED = 53107
BOOTSTRAP_ITERATIONS = 10_000
RIDGE_TOLERANCE = 1e-10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_table(root: Path, manifest: Mapping[str, Any], dataset: str) -> pa.Table:
    matches = [item for item in manifest["artifacts"] if item["dataset"] == dataset]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {dataset} artifact")
    return ResearchArtifactStore(root).read_table(str(matches[0]["uri"]))


def _feature_table(root: Path, manifest_id: str) -> pa.Table:
    manifest = ResearchArtifactStore(root).load_manifest("features", manifest_id)
    matches = [
        item
        for item in manifest["artifacts"]
        if item["dataset"] == "model_ready_games"
        and item.get("prediction_horizon") == "game_day_morning"
    ]
    if len(matches) != 1:
        raise ValueError("holdout morning feature artifact is unavailable")
    table = ResearchArtifactStore(root).read_table(str(matches[0]["uri"]))
    if manifest.get("feature_set_hash") != "0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad":
        raise ValueError("holdout feature set differs from the frozen feature set")
    return table


def _numeric_matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [
            [
                np.nan
                if row.get(column) is None or not math.isfinite(float(row[column]))
                else float(row[column])
                for column in columns
            ]
            for row in rows
        ],
        dtype=float,
    )


def apply_frozen_ridge(
    training_rows: Sequence[Mapping[str, Any]],
    evaluation_rows: Sequence[Mapping[str, Any]],
    artifact: Mapping[str, Any],
) -> np.ndarray:
    """Apply serialized sklearn parameters without invoking any fitting API."""
    if artifact.get("artifact_hash") != TOTAL_RIDGE_ARTIFACT_HASH:
        raise ValueError("wrong frozen Ridge artifact")
    pipeline = artifact["pipeline"]
    columns = list(pipeline["feature_columns"])
    train = _numeric_matrix(training_rows, columns)
    evaluate = _numeric_matrix(evaluation_rows, columns)
    statistics = np.asarray(pipeline["imputer_statistics"], dtype=float)
    if train.shape[1] != statistics.size or evaluate.shape[1] != statistics.size:
        raise ValueError("frozen Ridge feature width mismatch")
    indicator_features = np.flatnonzero(np.isnan(train).any(axis=0))
    if np.isnan(statistics).any():
        raise ValueError("frozen Ridge contains an unsupported all-missing training feature")
    imputed = np.where(np.isnan(evaluate), statistics, evaluate)
    indicators = np.isnan(evaluate[:, indicator_features]).astype(float)
    transformed = np.concatenate((imputed, indicators), axis=1)
    support = np.asarray(pipeline["variance_support"], dtype=bool)
    if transformed.shape[1] != support.size:
        raise ValueError("frozen missing-indicator layout cannot be reconstructed exactly")
    transformed = transformed[:, support]
    mean = np.asarray(pipeline["scaler_mean"], dtype=float)
    scale = np.asarray(pipeline["scaler_scale"], dtype=float)
    coefficients = np.asarray(pipeline["coefficients"], dtype=float)
    if transformed.shape[1] != mean.size or mean.size != scale.size or scale.size != coefficients.size:
        raise ValueError("frozen Ridge parameter dimensions disagree")
    standardized = (transformed - mean) / scale
    return standardized @ coefficients + float(pipeline["intercept"])


def _verify_ridge_replay(
    feature_rows: Sequence[Mapping[str, Any]], artifact: Mapping[str, Any], root: Path
) -> float:
    training = [row for row in feature_rows if int(row["season"]) <= 2023]
    validation = [row for row in feature_rows if int(row["season"]) == 2024]
    predictions = apply_frozen_ridge(training, validation, artifact)
    saved = pq.read_table(root / "models" / "baseline-v1" / "oof_predictions.parquet").to_pylist()
    expected = {
        str(row["canonical_event_id"]): float(row["prediction"])
        for row in saved
        if int(row["season"]) == 2024
        and row["horizon"] == "game_day_morning"
        and row["target"] == "total"
        and row["model_family"] == "ridge"
        and row["variant"] == "full_without_opponent_adjustment"
    }
    paired = [
        abs(float(value) - expected[str(row["canonical_event_id"])])
        for row, value in zip(validation, predictions, strict=True)
        if str(row["canonical_event_id"]) in expected
    ]
    if len(paired) != len(expected) or not paired:
        raise ValueError("frozen Ridge replay cohort does not match saved 2024 predictions")
    maximum = max(paired)
    if maximum > RIDGE_TOLERANCE:
        raise ValueError(f"frozen Ridge replay mismatch: {maximum}")
    return maximum


def _market_consensus(root: Path, market_manifest_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = ResearchArtifactStore(root).load_manifest("holdout-2025-market", market_manifest_id)
    observations = _artifact_table(root, manifest, "observations").to_pylist()
    for row in observations:
        row["source_market_dataset_hash"] = manifest["dataset_hash"]
        row["source_market_dataset_version"] = manifest["dataset_version"]
    return build_consensus_rows(observations, allow_holdout_access=True)


def _quality(row: Mapping[str, Any]) -> str:
    values = (row.get("home_pbp_coverage_ratio"), row.get("away_pbp_coverage_ratio"))
    return "high" if all(value is not None and float(value) >= 0.8 for value in values) else "low"


def _point_metrics(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, float | int]:
    actual = np.asarray([float(row["actual"]) for row in rows])
    prediction = np.asarray([float(row[field]) for row in rows])
    residual = actual - prediction
    return {
        "rows": len(rows),
        "mae": float(np.mean(np.abs(residual))),
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "bias": float(np.mean(residual)),
    }


def blend_total(market_total: float, ridge_total: float) -> float:
    return market_total + TOTAL_RIDGE_BLEND_WEIGHT * (ridge_total - market_total)


def _probability_rows(
    rows: Sequence[Mapping[str, Any]],
    prior_points: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    source_candidates = {
        "market_consensus": "market_consensus",
        "blend_ridge_no_opp": "blend_football_ridge_no_opp",
    }
    by_candidate = {
        candidate: [
            float(item["actual"]) - float(item["prediction"])
            for item in prior_points
            if item["target"] == "total"
            and item["candidate"] == source_candidates[candidate]
            and int(item["season"]) <= 2024
        ]
        for candidate in source_candidates
    }
    bases = {
        candidate: fit_empirical_grid(
            residuals,
            pool_id=stable_hash(
                {"target": "total", "candidate": source_candidates[candidate], "cutoff": 2024}
            ),
        )
        for candidate, residuals in by_candidate.items()
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        for candidate, field in (
            ("market_consensus", "market_prediction"),
            ("blend_ridge_no_opp", "blend_prediction"),
        ):
            residuals = by_candidate[candidate]
            base = bases[candidate]
            pool_id = base.pool_id
            distribution = type(base)(
                float(row[field]),
                base.scale,
                base.residual_grid,
                base.residual_cdf,
                base.residual_pdf,
                base.pool_id,
                base.bandwidth,
            )
            probabilities = total_probabilities(distribution, float(row["market_prediction"]))
            outcome = str(row["outcome"])
            scores = multiclass_scores(probabilities, outcome)
            output.append(
                {
                    "canonical_event_id": row["canonical_event_id"],
                    "week": row["week"],
                    "candidate": candidate,
                    "win_probability": probabilities.win,
                    "push_probability": probabilities.push,
                    "loss_probability": probabilities.loss,
                    "outcome": outcome,
                    "multiclass_brier": scores["brier"],
                    "multiclass_log_loss": scores["log_loss"],
                    "residual_pool_id": pool_id,
                    "residual_pool_rows": len(residuals),
                    "distribution_scale": base.scale,
                }
            )
    return output


def weighted_calibration_error(rows: Sequence[Mapping[str, Any]]) -> float:
    total = len(rows)
    if not total:
        return float("nan")
    error = 0.0
    for lower in np.arange(0.0, 1.0, 0.1):
        upper = lower + 0.1
        selected = [
            row
            for row in rows
            if lower <= float(row["win_probability"]) <= upper
            and (lower == 0.9 or float(row["win_probability"]) < upper)
        ]
        if selected:
            predicted = float(np.mean([float(row["win_probability"]) for row in selected]))
            observed = float(np.mean([row["outcome"] == "win" for row in selected]))
            error += len(selected) / total * abs(predicted - observed)
    return error


def _week_block_interval(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    blocks: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        blocks[int(row["week"])].append(
            abs(float(row["actual"]) - float(row["blend_prediction"]))
            - abs(float(row["actual"]) - float(row["market_prediction"]))
        )
    weeks = sorted(blocks)
    rng = np.random.default_rng(SEED)
    samples = np.empty(BOOTSTRAP_ITERATIONS)
    for index in range(BOOTSTRAP_ITERATIONS):
        selected = rng.choice(weeks, size=len(weeks), replace=True)
        samples[index] = np.mean([value for week in selected for value in blocks[int(week)]])
    values = [value for block in blocks.values() for value in block]
    return {
        "blocks": len(weeks),
        "iterations": BOOTSTRAP_ITERATIONS,
        "seed": SEED,
        "blend_minus_market_mae": float(np.mean(values)),
        "ci90_lower": float(np.quantile(samples, 0.05)),
        "ci90_upper": float(np.quantile(samples, 0.95)),
    }


def _segment_name(row: Mapping[str, Any], family: str) -> str:
    if family == "season_timing":
        return "weeks_0_3" if int(row["week"]) <= 3 else "weeks_4_plus"
    if family == "market_dispersion":
        return "below_0.02" if float(row["dispersion"]) < 0.02 else "at_or_above_0.02"
    if family == "model_market_disagreement_points":
        value = abs(float(row["ridge_prediction"]) - float(row["market_prediction"]))
        return "0_to_3" if value < 3 else "3_to_7" if value < 7 else "7_plus"
    if family == "total_line":
        value = float(row["market_prediction"])
        return "below_45" if value < 45 else "45_to_60" if value <= 60 else "above_60"
    if family == "feature_quality":
        return str(row["quality_level"])
    raise ValueError(f"unknown segment family: {family}")


def _segments(
    rows: Sequence[Mapping[str, Any]], probability_rows: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, float | int]]:
    probabilities = {
        (str(row["canonical_event_id"]), str(row["candidate"])): row for row in probability_rows
    }
    results: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    families = (
        "season_timing",
        "market_dispersion",
        "model_market_disagreement_points",
        "total_line",
        "feature_quality",
    )
    for family in families:
        names = sorted({_segment_name(row, family) for row in rows})
        for name in names:
            selected = [row for row in rows if _segment_name(row, family) == name]
            market = _point_metrics(selected, "market_prediction")
            blend = _point_metrics(selected, "blend_prediction")
            market_brier = float(
                np.mean(
                    [
                        probabilities[(str(row["canonical_event_id"]), "market_consensus")][
                            "multiclass_brier"
                        ]
                        for row in selected
                    ]
                )
            )
            blend_brier = float(
                np.mean(
                    [
                        probabilities[(str(row["canonical_event_id"]), "blend_ridge_no_opp")][
                            "multiclass_brier"
                        ]
                        for row in selected
                    ]
                )
            )
            item = {
                "family": family,
                "segment": name,
                "rows": len(selected),
                "market_mae": market["mae"],
                "blend_mae": blend["mae"],
                "mae_degradation": float(blend["mae"]) - float(market["mae"]),
                "market_brier": market_brier,
                "blend_brier": blend_brier,
                "brier_degradation": blend_brier - market_brier,
                "gate_status": "EVALUATED" if len(selected) >= 75 else "UNEVALUABLE",
            }
            results.append(item)
            if len(selected) >= 75:
                evaluated.append(item)
    return results, {
        "segments_over_0_25_mae_degradation": sum(float(row["mae_degradation"]) > 0.25 for row in evaluated),
        "maximum_segment_mae_degradation": max((float(row["mae_degradation"]) for row in evaluated), default=0.0),
        "maximum_segment_brier_degradation": max((float(row["brier_degradation"]) for row in evaluated), default=0.0),
    }


def _gate(status: bool | None, value: Any, threshold: str) -> dict[str, Any]:
    return {
        "status": "UNEVALUABLE" if status is None else "PASS" if status else "FAIL",
        "value": value,
        "threshold": threshold,
    }


def run_holdout_evaluation(
    root: Path,
    freeze_manifest: Mapping[str, Any],
    *,
    feature_manifest_id: str,
    market_manifest_id: str,
    code_commit: str,
) -> dict[str, Any]:
    unlock = load_unlock_record(root)
    if freeze_manifest.get("freeze_hash") != EXPECTED_FREEZE_HASH:
        raise ValueError("freeze manifest hash mismatch")
    freeze_errors = validate_local_artifacts(root, freeze_manifest)
    if freeze_errors:
        raise ValueError(f"freeze artifact verification failed: {freeze_errors}")
    if set(freeze_manifest["allowed_candidates"]) != ALLOWED_CANDIDATES:
        raise ValueError("frozen candidate allowlist changed")

    feature_manifest = ResearchArtifactStore(root).load_manifest("features", feature_manifest_id)
    features = _feature_table(root, feature_manifest_id).to_pylist()
    holdout_features = [row for row in features if int(row["season"]) == 2025]
    if any(row["fold_role"] != "locked_test" for row in holdout_features):
        raise ValueError("2025 feature rows are not labeled locked_test")
    fold_models = json.loads((root / "models" / "baseline-v1" / "fold_models.json").read_text())
    ridge_matches = [row for row in fold_models if row.get("artifact_hash") == TOTAL_RIDGE_ARTIFACT_HASH]
    if len(ridge_matches) != 1:
        raise ValueError("frozen Ridge artifact is unavailable")
    ridge = ridge_matches[0]
    replay_difference = _verify_ridge_replay(features, ridge, root)
    training = [row for row in features if int(row["season"]) <= 2023]
    ridge_predictions = apply_frozen_ridge(training, holdout_features, ridge)
    ridge_by_id = {
        str(row["canonical_event_id"]): float(value)
        for row, value in zip(holdout_features, ridge_predictions, strict=True)
    }
    features_by_id = {str(row["canonical_event_id"]): row for row in holdout_features}
    ordered_features = sorted(features, key=lambda row: (row["kickoff"], row["provider_game_id"]))
    power_values = elo_predictions(ordered_features)
    power_by_id = {
        str(row["canonical_event_id"]): float(value)
        for row, value in zip(ordered_features, power_values, strict=True)
        if int(row["season"]) == 2025
    }

    consensus, consensus_exclusions = _market_consensus(root, market_manifest_id)
    by_market = {
        (str(row["canonical_event_id"]), str(row["market_type"])): row for row in consensus
    }
    rows: list[dict[str, Any]] = []
    for event_id, feature in sorted(features_by_id.items()):
        total = by_market.get((event_id, "totals"))
        if total is None or event_id not in ridge_by_id:
            continue
        line = float(total["consensus_point"])
        actual = float(feature["target_total"])
        delta = actual - line
        rows.append(
            {
                "canonical_event_id": event_id,
                "season": 2025,
                "week": int(feature["week"]),
                "actual": actual,
                "market_prediction": line,
                "ridge_prediction": ridge_by_id[event_id],
                "blend_prediction": blend_total(line, ridge_by_id[event_id]),
                "outcome": "win" if delta > 0 else "loss" if delta < 0 else "push",
                "book_count": int(total["complete_book_count"]),
                "dispersion": float(total["probability_dispersion"]),
                "quality_level": _quality(feature),
                "requested_cutoff": total["requested_cutoff"],
                "snapshot_max": total["snapshot_max"],
            }
        )
    if any(row["snapshot_max"] > row["requested_cutoff"] for row in rows):
        raise ValueError("later market snapshot leaked into the morning holdout")

    market_aware = ResearchArtifactStore(root).load_manifest(
        "market-aware-v1", str(freeze_manifest["frozen_hashes"]["market_aware_manifest_id"])
    )
    prior_points = _artifact_table(root, market_aware, "point_predictions").to_pylist()
    probability_rows = _probability_rows(rows, prior_points)
    market_probability = [row for row in probability_rows if row["candidate"] == "market_consensus"]
    blend_probability = [row for row in probability_rows if row["candidate"] == "blend_ridge_no_opp"]
    market_metrics = _point_metrics(rows, "market_prediction")
    blend_metrics = _point_metrics(rows, "blend_prediction")
    market_brier = float(np.mean([float(row["multiclass_brier"]) for row in market_probability]))
    blend_brier = float(np.mean([float(row["multiclass_brier"]) for row in blend_probability]))
    market_log = float(np.mean([float(row["multiclass_log_loss"]) for row in market_probability]))
    blend_log = float(np.mean([float(row["multiclass_log_loss"]) for row in blend_probability]))
    calibration = weighted_calibration_error(blend_probability)
    interval = _week_block_interval(rows)
    segment_rows, segment_summary = _segments(rows, probability_rows)
    integer_line_games = sum(float(row["market_prediction"]).is_integer() for row in rows)
    push_preserved = all(
        row.get("push_probability") is not None
        and float(row["push_probability"]) >= 0
        and math.isfinite(float(row["push_probability"]))
        and abs(
            float(row["win_probability"])
            + float(row["push_probability"])
            + float(row["loss_probability"])
            - 1.0
        )
        <= 1e-12
        for row in probability_rows
    )
    metrics_for_decision = {
        "integrity_pass": True,
        "rows": len(rows),
        "market_mae": market_metrics["mae"],
        "blend_mae": blend_metrics["mae"],
        "market_rmse": market_metrics["rmse"],
        "blend_rmse": blend_metrics["rmse"],
        "market_brier": market_brier,
        "blend_brier": blend_brier,
        "market_log_loss": market_log,
        "blend_log_loss": blend_log,
        "mae_difference_ci90_upper": interval["ci90_upper"],
        "weighted_calibration_error": calibration,
        "push_probabilities_preserved": push_preserved,
        **segment_summary,
    }
    gates = {
        "minimum_500_games": _gate(len(rows) >= 500, len(rows), ">= 500"),
        "mae_improvement": _gate(
            float(market_metrics["mae"]) - float(blend_metrics["mae"]) >= 0.10,
            float(market_metrics["mae"]) - float(blend_metrics["mae"]),
            ">= 0.10",
        ),
        "rmse_degradation": _gate(
            float(blend_metrics["rmse"]) - float(market_metrics["rmse"]) <= 0.10,
            float(blend_metrics["rmse"]) - float(market_metrics["rmse"]),
            "<= 0.10",
        ),
        "brier_improvement": _gate(market_brier - blend_brier >= 0.001, market_brier - blend_brier, ">= 0.001"),
        "log_loss_improvement": _gate(market_log - blend_log >= 0.001, market_log - blend_log, ">= 0.001"),
        "week_block_upper": _gate(float(interval["ci90_upper"]) <= 0.05, interval["ci90_upper"], "<= +0.05"),
        "weighted_calibration": _gate(calibration <= 0.05, calibration, "<= 0.05"),
        "push_probabilities": _gate(push_preserved, push_preserved, "preserved and normalized"),
        "maximum_segment_degradation": _gate(
            float(segment_summary["maximum_segment_mae_degradation"]) <= 0.50
            and float(segment_summary["maximum_segment_brier_degradation"]) <= 0.01,
            {
                "mae": segment_summary["maximum_segment_mae_degradation"],
                "brier": segment_summary["maximum_segment_brier_degradation"],
            },
            "MAE <= 0.50 and Brier <= 0.01",
        ),
        "segment_count_over_0_25": _gate(
            int(segment_summary["segments_over_0_25_mae_degradation"]) <= 1,
            segment_summary["segments_over_0_25_mae_degradation"],
            "<= 1",
        ),
    }
    decision = decide_total_blend(metrics_for_decision)
    final_status = (
        "PASS" if decision == "advance_blend_to_shadow_candidate_only" else "FAIL"
    )

    # Frozen benchmark context; it does not reopen the margin decision.
    h2h_rows = [row for row in consensus if row["market_type"] == "h2h" and row["canonical_event_id"] in features_by_id]
    ml_brier = float(
        np.mean(
            [
                (float(row["side_1_consensus_probability"]) - (1.0 if features_by_id[str(row["canonical_event_id"])]["target_margin"] > 0 else 0.0)) ** 2
                for row in h2h_rows
            ]
        )
    )
    clipped = [min(max(float(row["side_1_consensus_probability"]), 1e-15), 1 - 1e-15) for row in h2h_rows]
    outcomes = [1.0 if features_by_id[str(row["canonical_event_id"])]["target_margin"] > 0 else 0.0 for row in h2h_rows]
    ml_log = float(np.mean([-(y * math.log(p) + (1 - y) * math.log(1 - p)) for p, y in zip(clipped, outcomes, strict=True)]))
    spread_rows = [
        {
            "actual": float(features_by_id[str(row["canonical_event_id"])]["target_margin"]),
            "market": -float(row["consensus_point"]),
            "power": power_by_id[str(row["canonical_event_id"])],
        }
        for row in consensus
        if row["market_type"] == "spreads"
        and row["canonical_event_id"] in features_by_id
        and row["canonical_event_id"] in power_by_id
    ]

    result: dict[str, Any] = {
        "holdout_version": HOLDOUT_VERSION,
        "status": final_status,
        "decision": decision,
        "fallback": "market_consensus" if final_status != "PASS" else None,
        "shadow_candidate": "total_market_ridge_blend" if final_status == "PASS" else None,
        "code_commit": code_commit,
        "freeze_hash": freeze_manifest["freeze_hash"],
        "freeze_verification": {"valid": True, "errors": [], "ridge_2024_replay_max_abs_difference": replay_difference},
        "first_access": unlock,
        "provider": {
            "cfbd_calls": 37,
            "odds_api_calls": 79,
            "odds_api_credits": 2370,
            "odds_api_remaining": 17630,
        },
        "source_hashes": {
            "normalized": "5b965841111d47f090553e0779213f8722be3d3ea353f04ec9865fd9f393c386",
            "feature_dataset": feature_manifest["dataset_hash"],
            "market_dataset": ResearchArtifactStore(root)
            .load_manifest("holdout-2025-market", market_manifest_id)["dataset_hash"],
        },
        "coverage": {
            "eligible_fbs_vs_fbs": len(holdout_features),
            "football_features": len(holdout_features),
            "market_consensus_games_by_market": {
                market: len({str(row["canonical_event_id"]) for row in consensus if row["market_type"] == market})
                for market in ("h2h", "spreads", "totals")
            },
            "total_common_cohort": len(rows),
            "consensus_exclusions": len(consensus_exclusions),
        },
        "total_metrics": {
            "market": {**market_metrics, "multiclass_brier": market_brier, "multiclass_log_loss": market_log},
            "blend": {
                **blend_metrics,
                "multiclass_brier": blend_brier,
                "multiclass_log_loss": blend_log,
                "weighted_calibration_error": calibration,
            },
            "differences": {
                "mae_improvement": float(market_metrics["mae"]) - float(blend_metrics["mae"]),
                "rmse_degradation": float(blend_metrics["rmse"]) - float(market_metrics["rmse"]),
                "brier_improvement": market_brier - blend_brier,
                "log_loss_improvement": market_log - blend_log,
            },
            "week_block_interval": interval,
        },
        "margin_benchmark": {
            "moneyline_games": len(h2h_rows),
            "moneyline_brier": ml_brier,
            "moneyline_log_loss": ml_log,
            "spread_common_games": len(spread_rows),
            "market_spread_point_metrics": _point_metrics(spread_rows, "market"),
            "football_power_diagnostic_metrics": _point_metrics(spread_rows, "power"),
            "primary": "market_consensus",
            "football_power": "diagnostic_only",
        },
        "gates": gates,
        "segments": segment_rows,
        "candidate_allowlist": sorted(ALLOWED_CANDIDATES),
        "blend_weight": TOTAL_RIDGE_BLEND_WEIGHT,
        "probability_version": freeze_manifest["versions"]["probability"],
        "push_version": freeze_manifest["versions"]["push_handling"],
        "push_audit": {
            "integer_line_games": integer_line_games,
            "nonzero_push_probability_rows": sum(
                float(row["push_probability"]) > 0 for row in probability_rows
            ),
            "explicit_probability_field": True,
            "probabilities_normalized": push_preserved,
        },
    }

    artifact_dir = root / "holdout-2025" / "evaluation"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    point_table = pa.Table.from_pylist(rows)
    probability_table = pa.Table.from_pylist(probability_rows)
    pq.write_table(point_table, artifact_dir / "total_predictions.parquet", compression="zstd")
    pq.write_table(probability_table, artifact_dir / "total_probabilities.parquet", compression="zstd")
    result["artifact_hashes"] = {
        "total_predictions_content": table_content_hash(point_table),
        "total_predictions_file": _sha256(artifact_dir / "total_predictions.parquet"),
        "total_probabilities_content": table_content_hash(probability_table),
        "total_probabilities_file": _sha256(artifact_dir / "total_probabilities.parquet"),
    }
    body = dict(result)
    result["holdout_run_hash"] = stable_hash(body)
    (artifact_dir / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return result


def validate_holdout_report(root: Path, report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    body = {key: value for key, value in report.items() if key != "holdout_run_hash"}
    if report.get("holdout_run_hash") != stable_hash(body):
        errors.append("holdout run hash mismatch")
    if report.get("freeze_hash") != EXPECTED_FREEZE_HASH:
        errors.append("freeze hash mismatch")
    try:
        unlock = load_unlock_record(root)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if report.get("first_access", {}).get("unlock_id") != unlock.get("unlock_id"):
            errors.append("first-access record mismatch")
    if set(report.get("candidate_allowlist", [])) != ALLOWED_CANDIDATES:
        errors.append("candidate allowlist mismatch")
    if abs(float(report.get("blend_weight", -1)) - TOTAL_RIDGE_BLEND_WEIGHT) > 1e-15:
        errors.append("frozen blend weight mismatch")
    artifact_dir = root / "holdout-2025" / "evaluation"
    paths = {
        "total_predictions_file": artifact_dir / "total_predictions.parquet",
        "total_probabilities_file": artifact_dir / "total_probabilities.parquet",
    }
    for key, path in paths.items():
        if not path.is_file() or _sha256(path) != report.get("artifact_hashes", {}).get(key):
            errors.append(f"artifact hash mismatch: {key}")
    if all(path.is_file() for path in paths.values()):
        points = pq.read_table(paths["total_predictions_file"]).to_pylist()
        probabilities = pq.read_table(paths["total_probabilities_file"]).to_pylist()
        if len(points) != int(report.get("coverage", {}).get("total_common_cohort", -1)):
            errors.append("common cohort row count mismatch")
        if {str(row["canonical_event_id"]) for row in points} != {
            str(row["canonical_event_id"]) for row in probabilities
        }:
            errors.append("market and blend probability cohorts differ")
        for row in points:
            expected = blend_total(float(row["market_prediction"]), float(row["ridge_prediction"]))
            if abs(float(row["blend_prediction"]) - expected) > 1e-12:
                errors.append("frozen blend formula mismatch")
                break
        for row in probabilities:
            total = sum(float(row[key]) for key in ("win_probability", "push_probability", "loss_probability"))
            if abs(total - 1.0) > 1e-12 or float(row["push_probability"]) < 0:
                errors.append("probability normalization mismatch")
                break
    statuses = {value.get("status") for value in report.get("gates", {}).values()}
    if not statuses <= {"PASS", "FAIL", "UNEVALUABLE"}:
        errors.append("unknown gate status")
    if report.get("status") == "FAIL" and report.get("fallback") != "market_consensus":
        errors.append("failed holdout did not select market fallback")
    return errors
