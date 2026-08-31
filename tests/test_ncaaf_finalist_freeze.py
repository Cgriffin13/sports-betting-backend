from __future__ import annotations

import copy
import json

from app.research.ncaaf.finalist_freeze import (
    ALLOWED_CANDIDATES,
    REJECTED_CANDIDATES,
    TOTAL_RIDGE_BLEND_WEIGHT,
    build_freeze_manifest,
    decide_total_blend,
    validate_freeze_manifest,
    write_freeze_manifest,
)


def passing_metrics() -> dict[str, object]:
    return {
        "integrity_pass": True,
        "rows": 650,
        "market_mae": 12.5,
        "blend_mae": 12.35,
        "market_rmse": 16.0,
        "blend_rmse": 15.95,
        "market_brier": 0.50,
        "blend_brier": 0.498,
        "market_log_loss": 0.70,
        "blend_log_loss": 0.698,
        "mae_difference_ci90_upper": -0.01,
        "weighted_calibration_error": 0.03,
        "segments_over_0_25_mae_degradation": 1,
        "maximum_segment_mae_degradation": 0.40,
        "maximum_segment_brier_degradation": 0.005,
        "push_probabilities_preserved": True,
    }


def test_freeze_manifest_is_deterministic_and_seals_holdout(tmp_path) -> None:
    first = build_freeze_manifest()
    second = build_freeze_manifest()
    assert first == second
    assert first["holdout_accessed"] is False
    assert first["provider_calls"] == 0
    assert validate_freeze_manifest(first) == []
    output = tmp_path / "freeze.json"
    write_freeze_manifest(output)
    assert json.loads(output.read_text(encoding="utf-8")) == first


def test_only_locked_finalists_are_allowed_and_rejections_are_disjoint() -> None:
    manifest = build_freeze_manifest()
    assert set(manifest["allowed_candidates"]) == ALLOWED_CANDIDATES
    assert set(manifest["rejected_candidates"]) == REJECTED_CANDIDATES
    assert not ALLOWED_CANDIDATES & REJECTED_CANDIDATES
    assert manifest["candidates"]["margin_spread_moneyline"]["primary"] == "margin_market_consensus"
    assert manifest["candidates"]["total"]["challenger"] == "total_market_ridge_blend"


def test_frozen_hash_and_blend_weight_tampering_fail_validation() -> None:
    manifest = build_freeze_manifest()
    tampered = copy.deepcopy(manifest)
    tampered["candidates"]["total"]["football_weight"] = TOTAL_RIDGE_BLEND_WEIGHT + 0.01
    assert "freeze hash mismatch" in validate_freeze_manifest(tampered)
    assert "total blend weight mismatch" in validate_freeze_manifest(tampered)


def test_holdout_access_and_push_removal_fail_closed() -> None:
    manifest = build_freeze_manifest()
    manifest["holdout_accessed"] = True
    manifest["gates"]["calibration"]["push_probability_required"] = False
    errors = validate_freeze_manifest(manifest)
    assert "2025 holdout must remain sealed" in errors
    assert "push probabilities must be preserved" in errors


def test_total_blend_promotion_rule_is_deterministic_and_all_or_fallback() -> None:
    metrics = passing_metrics()
    assert decide_total_blend(metrics) == "advance_blend_to_shadow_candidate_only"
    assert decide_total_blend(metrics) == "advance_blend_to_shadow_candidate_only"
    for key, failing_value in (
        ("blend_mae", 12.45),
        ("blend_brier", 0.4995),
        ("push_probabilities_preserved", False),
        ("maximum_segment_mae_degradation", 0.51),
    ):
        failed = {**metrics, key: failing_value}
        assert decide_total_blend(failed) == "fallback_to_market_consensus"
