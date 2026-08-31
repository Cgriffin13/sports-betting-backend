from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.research.ncaaf.contracts import stable_hash
from app.research.ncaaf.artifacts import ResearchArtifactStore

FREEZE_VERSION = "ncaaf-finalist-freeze-v1"
HOLDOUT_PROTOCOL_VERSION = "ncaaf-2025-one-time-holdout-v1"

MARKET_AWARE_MANIFEST_ID = "838540d121117e0e9564f19256b9f23e30d618e6374b0235ff115b535c8443ae"
MARKET_AWARE_DATASET_HASH = "6305a430fd43d74feaf2dad8d326c809d0c2758521db60e5aaa8cc5502e72fad"
MARKET_AWARE_POINT_HASH = "71c33513361d1065eb9e45fe62fd97759f4350ce0e0a630bf9d0c9b7e22aff03"
MARKET_AWARE_PROBABILITY_HASH = "707d836dffd7c689a341efc4720268a4ddcc202f8daccabfa704d76160e9d9f9"
MARKET_AWARE_SUMMARY_HASH = "8cf4d84e08795eaf5367ce8b36fc9f27ed29f9bce2f9773fcb4daea9d81edf6a"
MARKET_COMPARISON_HASH = "cf8669b7f4dd371d12ae03e6e0de180ffb63c196a848a6d7ac791bba8f023bcc"
HISTORICAL_MARKET_HASH = "96c3236ea6770e669b351398900b92289a9263cbfe625f3cf986dad235c5274b"
FEATURE_DATASET_HASH = "b2f7444e2a7451d90c9078fb3b694d1586b1d30dd7f9c3a60b869381532b8bfe"
FEATURE_SET_HASH = "0d4d5b3e9996c5682bc6e5366f70c4a82fd80fce8a3ebaa8db7a6ee22bc446ad"
BASELINE_RUN_HASH = "036989b3c5b65226f93f72164e73ec4070b14ca7105d9b55c9e86af9c9778cfb"
POWER_PREDICTIONS_HASH = "acf300df3e7578039ef26a3da3e9939257095f8100e38cff3776c5a8a10e7e55"
TOTAL_RIDGE_ARTIFACT_HASH = "d41797ed69ea699038f4ba530962611c24799db9ba930daf22c95decff32c167"
TOTAL_RIDGE_BLEND_WEIGHT = 0.17854145992095644

ALLOWED_CANDIDATES = frozenset(
    {
        "margin_market_consensus",
        "margin_football_power_diagnostic",
        "total_market_consensus",
        "total_market_ridge_blend",
    }
)
REJECTED_CANDIDATES = frozenset(
    {
        "margin_market_residual_ridge",
        "margin_market_feature_ridge",
        "total_market_residual_ridge",
        "total_market_feature_ridge",
        "total_market_residual_catboost",
        "total_market_feature_catboost",
        "total_preseason_catboost_blend",
    }
)


def freeze_body() -> dict[str, Any]:
    """Return the immutable pre-holdout specification; it contains no 2025 observations."""
    candidates = {
        "margin_spread_moneyline": {
            "primary": "margin_market_consensus",
            "diagnostic_only": ["margin_football_power_diagnostic"],
            "probability_source": "market_consensus",
        },
        "total": {
            "benchmark": "total_market_consensus",
            "challenger": "total_market_ridge_blend",
            "blend_formula": "market + football_weight * (football_ridge_no_opp - market)",
            "football_weight": TOTAL_RIDGE_BLEND_WEIGHT,
            "market_weight": 1.0 - TOTAL_RIDGE_BLEND_WEIGHT,
            "weight_training_cutoff": 2023,
            "weight_policy": "constrained-oof-least-squares-v1",
        },
    }
    gates = {
        "integrity": {
            "all_frozen_hashes_match": True,
            "same_common_cohort": True,
            "minimum_total_holdout_games": 500,
            "provider_calls": 0,
            "later_horizons_allowed": False,
        },
        "total_blend_practical_effect": {
            "all_required": True,
            "minimum_mae_improvement_points": 0.10,
            "maximum_rmse_degradation_points": 0.10,
            "minimum_multiclass_brier_improvement": 0.001,
            "minimum_multiclass_log_loss_improvement": 0.001,
            "paired_week_block_90pct_mae_upper_bound": 0.05,
            "complexity_must_remain_single_fixed_linear_blend": True,
        },
        "calibration": {
            "moneyline_market_max_brier_degradation_vs_2024": 0.02,
            "moneyline_market_max_log_loss_degradation_vs_2024": 0.04,
            "spread_market_max_multiclass_brier_degradation_vs_2024": 0.02,
            "spread_market_max_multiclass_log_loss_degradation_vs_2024": 0.04,
            "total_market_max_multiclass_brier_degradation_vs_2024": 0.02,
            "total_market_max_multiclass_log_loss_degradation_vs_2024": 0.04,
            "blend_max_brier_degradation_vs_market": 0.0,
            "blend_max_log_loss_degradation_vs_market": 0.0,
            "maximum_weighted_calibration_error": 0.05,
            "push_probability_required": True,
        },
        "segments": {
            "minimum_rows": 75,
            "definitions": {
                "season_timing": ["weeks_0_3", "weeks_4_plus"],
                "market_dispersion": ["below_0.02", "at_or_above_0.02"],
                "model_market_disagreement_points": ["0_to_3", "3_to_7", "7_plus"],
                "total_line": ["below_45", "45_to_60", "above_60"],
                "feature_quality": ["high", "low"],
            },
            "maximum_segments_with_mae_degradation_over_0.25": 1,
            "maximum_any_segment_mae_degradation": 0.50,
            "maximum_any_segment_brier_degradation": 0.01,
        },
    }
    return {
        "freeze_version": FREEZE_VERSION,
        "status": "frozen_pre_holdout",
        "holdout_accessed": False,
        "provider_calls": 0,
        "allowed_candidates": sorted(ALLOWED_CANDIDATES),
        "rejected_candidates": sorted(REJECTED_CANDIDATES),
        "candidates": candidates,
        "versions": {
            "horizon": "morning_first_kickoff_minus_3h",
            "consensus": "unweighted-median-v1",
            "vig_removal": "proportional-v1",
            "market_tournament": "ncaaf-market-aware-tournament-v1",
            "probability": "chronological-empirical-market-aware-v1",
            "push_handling": "integer-lattice-settlement-v1",
            "common_cohort": "canonical-event-exact-morning-min-two-books-v1",
            "uncertainty": "paired-week-block-90pct-and-predeclared-segments-v1",
            "holdout_protocol": HOLDOUT_PROTOCOL_VERSION,
        },
        "frozen_hashes": {
            "market_aware_manifest_id": MARKET_AWARE_MANIFEST_ID,
            "market_aware_dataset": MARKET_AWARE_DATASET_HASH,
            "market_aware_points": MARKET_AWARE_POINT_HASH,
            "market_aware_probabilities": MARKET_AWARE_PROBABILITY_HASH,
            "market_aware_summary": MARKET_AWARE_SUMMARY_HASH,
            "market_comparison_dataset": MARKET_COMPARISON_HASH,
            "historical_market_dataset": HISTORICAL_MARKET_HASH,
            "feature_dataset": FEATURE_DATASET_HASH,
            "feature_set": FEATURE_SET_HASH,
            "baseline_run": BASELINE_RUN_HASH,
            "football_power_predictions": POWER_PREDICTIONS_HASH,
            "total_ridge_2024_fold_artifact": TOTAL_RIDGE_ARTIFACT_HASH,
        },
        "total_ridge_artifact": {
            "family": "ridge",
            "variant": "full_without_opponent_adjustment",
            "model_version": "ncaaf-baseline-tournament-v1",
            "preprocessing_version": "median-indicator-variance-standardize-v1",
            "fold_id": "develop_through_2023_evaluate_2024",
            "training_cutoff": 2023,
            "training_rows": 7479,
            "alpha": 100.0,
            "artifact_hash": TOTAL_RIDGE_ARTIFACT_HASH,
        },
        "calibration_reference_2024": {
            "moneyline_market_brier": 0.185773,
            "moneyline_market_log_loss": 0.548005,
            "spread_market_multiclass_brier": 0.516309,
            "spread_market_multiclass_log_loss": 0.748862,
            "total_market_multiclass_brier": 0.4999865787510407,
            "total_market_multiclass_log_loss": 0.6937262489476305,
        },
        "gates": gates,
        "fallbacks": {
            "integrity_failure": "stop_without_interpreting_holdout",
            "margin_or_probability_gate_failure": "retain_market_consensus_and_record_warning",
            "total_blend_any_gate_failure": "retain_total_market_consensus",
            "total_blend_all_gates_pass": "advance_blend_to_shadow_candidate_only",
            "football_power": "diagnostic_only_regardless_of_relative_accuracy_if_integrity_passes",
        },
        "holdout_protocol": [
            "verify freeze manifest and every available source/artifact hash",
            "require an explicit one-time 2025 unlock and immutable access record",
            "build 2025 football and market inputs under existing point-in-time rules",
            "reject refitting, recalibration, retuning, candidate additions, and later-horizon substitution",
            "generate predictions from the exact frozen specifications and artifacts",
            "evaluate only the predeclared aggregate, calibration, uncertainty, and segment gates",
            "record pass, fail, unevaluable, and fallback decisions before any interpretation",
            "treat data/code integrity defects as stop-and-remediate events, never as permission to tune",
        ],
    }


def build_freeze_manifest() -> dict[str, Any]:
    body = freeze_body()
    return {**body, "freeze_hash": stable_hash(body)}


def validate_freeze_manifest(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    body = {key: value for key, value in manifest.items() if key != "freeze_hash"}
    if manifest.get("freeze_hash") != stable_hash(body):
        errors.append("freeze hash mismatch")
    if manifest.get("holdout_accessed") is not False:
        errors.append("2025 holdout must remain sealed")
    if int(manifest.get("provider_calls", -1)) != 0:
        errors.append("provider calls must be zero")
    allowed = set(manifest.get("allowed_candidates", []))
    rejected = set(manifest.get("rejected_candidates", []))
    if allowed != ALLOWED_CANDIDATES:
        errors.append("finalist allowlist mismatch")
    if rejected != REJECTED_CANDIDATES or allowed & rejected:
        errors.append("rejected-candidate policy mismatch")
    total = manifest.get("candidates", {}).get("total", {})
    if abs(float(total.get("football_weight", -1)) - TOTAL_RIDGE_BLEND_WEIGHT) > 1e-15:
        errors.append("total blend weight mismatch")
    if abs(float(total.get("football_weight", 0)) + float(total.get("market_weight", 0)) - 1.0) > 1e-15:
        errors.append("blend weights do not sum to one")
    if not manifest.get("gates", {}).get("calibration", {}).get("push_probability_required"):
        errors.append("push probabilities must be preserved")
    return errors


def validate_local_artifacts(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    """Validate local ignored artifacts when present; absence is reported without reading holdout data."""
    errors = validate_freeze_manifest(manifest)
    current = root / "market-aware-v1" / "current.json"
    if not current.exists():
        return [*errors, "local Phase 5B-7 market-aware artifact is unavailable"]
    pointer = json.loads(current.read_text(encoding="utf-8"))
    if pointer.get("manifest_id") != MARKET_AWARE_MANIFEST_ID:
        errors.append("market-aware manifest id mismatch")
    source = json.loads((root / str(pointer["uri"])).read_text(encoding="utf-8"))
    if source.get("holdout_accessed") is not False:
        errors.append("source artifact accessed holdout")
    expected = manifest["frozen_hashes"]
    scalar_checks = {
        "dataset_hash": "market_aware_dataset",
        "summary_hash": "market_aware_summary",
        "source_market_comparison_hash": "market_comparison_dataset",
        "source_market_dataset_hash": "historical_market_dataset",
        "source_feature_dataset_hash": "feature_dataset",
        "feature_set_hash": "feature_set",
    }
    for source_key, frozen_key in scalar_checks.items():
        if source.get(source_key) != expected[frozen_key]:
            errors.append(f"source {source_key} mismatch")
    artifact_hashes = {item["dataset"]: item["content_hash"] for item in source["artifacts"]}
    if artifact_hashes.get("point_predictions") != expected["market_aware_points"]:
        errors.append("point artifact mismatch")
    if artifact_hashes.get("probability_predictions") != expected["market_aware_probabilities"]:
        errors.append("probability artifact mismatch")
    store = ResearchArtifactStore(root)
    for artifact in source["artifacts"]:
        errors.extend(store.validate_artifact(artifact))
    fold_models = root / "models" / "baseline-v1" / "fold_models.json"
    if fold_models.exists():
        models = json.loads(fold_models.read_text(encoding="utf-8"))
        matches = [item for item in models if item.get("artifact_hash") == TOTAL_RIDGE_ARTIFACT_HASH]
        if len(matches) != 1:
            errors.append("frozen total Ridge artifact not found exactly once")
    return errors


def write_freeze_manifest(path: Path) -> dict[str, Any]:
    manifest = build_freeze_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def decide_total_blend(metrics: Mapping[str, Any]) -> str:
    """Apply the frozen all-or-fallback gate without tuning or discretionary scoring."""
    required = {
        "integrity_pass": bool(metrics.get("integrity_pass")),
        "minimum_rows": int(metrics.get("rows", 0)) >= 500,
        "mae": float(metrics.get("market_mae", 0)) - float(metrics.get("blend_mae", 0)) >= 0.10,
        "rmse": float(metrics.get("blend_rmse", 0)) - float(metrics.get("market_rmse", 0)) <= 0.10,
        "brier": float(metrics.get("market_brier", 0)) - float(metrics.get("blend_brier", 0)) >= 0.001,
        "log_loss": float(metrics.get("market_log_loss", 0)) - float(metrics.get("blend_log_loss", 0)) >= 0.001,
        "mae_interval": float(metrics.get("mae_difference_ci90_upper", 1)) <= 0.05,
        "calibration": float(metrics.get("weighted_calibration_error", 1)) <= 0.05,
        "segments": int(metrics.get("segments_over_0_25_mae_degradation", 99)) <= 1
        and float(metrics.get("maximum_segment_mae_degradation", 99)) <= 0.50
        and float(metrics.get("maximum_segment_brier_degradation", 99)) <= 0.01,
        "push": bool(metrics.get("push_probabilities_preserved")),
    }
    return "advance_blend_to_shadow_candidate_only" if all(required.values()) else "fallback_to_market_consensus"
