from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from app.research.ncaaf.finalist_freeze import (
    TOTAL_RIDGE_ARTIFACT_HASH,
    TOTAL_RIDGE_BLEND_WEIGHT,
    decide_total_blend,
)
from app.research.ncaaf.holdout_evaluation import (
    apply_frozen_ridge,
    blend_total,
    weighted_calibration_error,
)
from app.research.ncaaf.market_comparison import build_consensus_rows


def _ridge_artifact() -> dict[str, Any]:
    return {
        "artifact_hash": TOTAL_RIDGE_ARTIFACT_HASH,
        "pipeline": {
            "feature_columns": ["a"],
            "imputer_statistics": [2.0],
            "variance_support": [True, True],
            "scaler_mean": [0.0, 0.0],
            "scaler_scale": [1.0, 1.0],
            "coefficients": [1.0, 10.0],
            "intercept": 0.0,
        },
    }


def test_frozen_ridge_is_applied_without_refitting_and_future_rows_do_not_change_prior() -> None:
    training: list[dict[str, Any]] = [{"a": 1.0}, {"a": None}, {"a": 3.0}]
    earlier = apply_frozen_ridge(training, [{"a": None}], _ridge_artifact())
    later = apply_frozen_ridge(training, [{"a": None}, {"a": 999.0}], _ridge_artifact())
    assert earlier.tolist() == [12.0]
    assert later[0] == earlier[0]


def test_frozen_blend_weight_is_exact() -> None:
    assert TOTAL_RIDGE_BLEND_WEIGHT == 0.17854145992095644
    assert blend_total(50.0, 60.0) == 50.0 + TOTAL_RIDGE_BLEND_WEIGHT * 10.0


def test_weighted_calibration_error_is_deterministic() -> None:
    rows = [
        {"win_probability": 0.2, "outcome": "loss"},
        {"win_probability": 0.2, "outcome": "win"},
        {"win_probability": 0.8, "outcome": "win"},
        {"win_probability": 0.8, "outcome": "win"},
    ]
    assert weighted_calibration_error(rows) == pytest.approx(0.25)
    assert weighted_calibration_error(rows) == weighted_calibration_error(list(reversed(rows)))


def test_gate_failure_forces_market_fallback() -> None:
    metrics = {
        "integrity_pass": True,
        "rows": 758,
        "market_mae": 12.5,
        "blend_mae": 12.51,
        "market_rmse": 15.5,
        "blend_rmse": 15.53,
        "market_brier": 0.50,
        "blend_brier": 0.499,
        "market_log_loss": 0.69,
        "blend_log_loss": 0.689,
        "mae_difference_ci90_upper": 0.04,
        "weighted_calibration_error": 0.02,
        "segments_over_0_25_mae_degradation": 0,
        "maximum_segment_mae_degradation": 0.1,
        "maximum_segment_brier_degradation": 0.001,
        "push_probabilities_preserved": True,
    }
    assert decide_total_blend(metrics) == "fallback_to_market_consensus"


def _observation(book: str, side: str, odds: int) -> dict[str, Any]:
    cutoff = datetime(2025, 9, 1, 12, tzinfo=UTC)
    return {
        "canonical_event_id": "event-1",
        "cfbd_game_id": 1,
        "season": 2025,
        "week": 1,
        "scheduled_kickoff": cutoff + timedelta(hours=3),
        "horizon": "morning_first_kickoff_minus_3h",
        "requested_at": cutoff,
        "snapshot_at": cutoff - timedelta(minutes=5),
        "sportsbook": book,
        "supported_sportsbook": True,
        "market_type": "h2h",
        "side": side,
        "point": None,
        "american_odds": odds,
        "source_content_hash": f"{book}-{side}",
    }


def test_holdout_consensus_requires_explicit_access_path() -> None:
    observations = [
        _observation("draftkings", "home", -110),
        _observation("draftkings", "away", -110),
        _observation("fanduel", "home", -105),
        _observation("fanduel", "away", -115),
    ]
    with pytest.raises(ValueError, match="locked 2025"):
        build_consensus_rows(observations)
    rows, exclusions = build_consensus_rows(observations, allow_holdout_access=True)
    assert len(rows) == 1
    assert not exclusions
    assert rows[0]["complete_book_count"] == 2


def test_probability_math_remains_finite() -> None:
    values = np.asarray([blend_total(45.5, 49.0), blend_total(60.0, 55.0)])
    assert np.isfinite(values).all()
