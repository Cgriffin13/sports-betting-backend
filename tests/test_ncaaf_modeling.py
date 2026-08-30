from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pyarrow as pa
import pytest

from app.research.ncaaf.modeling import (
    EloConfig,
    FrozenFold,
    audit_input,
    elo_predictions,
    feature_columns,
    fit_predict_fold,
    frozen_folds,
    horizon_features_identical,
    paired_season_bootstrap,
    prediction_table,
)


def test_chronological_folds_are_expanding_disjoint_and_sealed() -> None:
    folds = frozen_folds()
    assert [fold.evaluation_season for fold in folds] == list(range(2019, 2025))
    assert folds[0].train_start == 2014 and folds[0].train_end == 2018
    assert folds[-1].role == "validation" and folds[-1].evaluation_season == 2024
    assert all(fold.train_end < fold.evaluation_season < 2025 for fold in folds)


def test_input_audit_rejects_locked_holdout() -> None:
    table = _table([_row(2025, 1)])
    with pytest.raises(ValueError, match="locked 2025"):
        audit_input(table, _manifest(), "24_hours_before_kickoff")


def test_fold_local_preprocessing_ignores_future_mutation() -> None:
    table = _table([_row(year, year, feature=None if year == 2016 else float(year)) for year in range(2014, 2020)])
    fold = FrozenFold("f", "development", 2014, 2018, 2019)
    columns = feature_columns(table)
    first, artifact_first = fit_predict_fold(table, fold, "target_margin", "ridge", {"alpha": 1.0}, columns)
    rows = table.to_pylist()
    rows[-1]["feature"] = 999999.0
    rows[-1]["target_margin"] = -999999.0
    second, artifact_second = fit_predict_fold(pa.Table.from_pylist(rows, schema=table.schema), fold, "target_margin", "ridge", {"alpha": 1.0}, columns)
    assert artifact_first["pipeline"] == artifact_second["pipeline"]
    # Validation feature mutation may alter its prediction, but never fitted preprocessing/model state.
    assert first[0] != second[0]


def test_future_fold_mutation_cannot_change_earlier_prediction() -> None:
    rows = [_row(year, year) for year in range(2014, 2021)]
    table = _table(rows)
    fold = FrozenFold("f", "development", 2014, 2018, 2019)
    columns = feature_columns(table)
    first, _ = fit_predict_fold(table, fold, "target_total", "ridge", {"alpha": 10.0}, columns)
    rows[-1]["target_total"] = 10000.0
    rows[-1]["feature"] = -10000.0
    second, _ = fit_predict_fold(_table(rows), fold, "target_total", "ridge", {"alpha": 10.0}, columns)
    assert first.tolist() == second.tolist()


def test_elo_predicts_before_target_game_update_and_handles_neutral() -> None:
    rows = [_row(2019, 1), _row(2019, 2)]
    rows[0].update(target_margin=20.0, neutral_site=False)
    rows[1].update(target_margin=0.0, neutral_site=True)
    predictions = elo_predictions(rows, EloConfig(home_field_points=3.0, update_rate=0.2))
    assert predictions[0] == 3.0
    assert predictions[1] == pytest.approx(3.4)  # first game's 17-point error creates a 3.4-point rating gap


def test_elo_offseason_regression_is_applied() -> None:
    rows = [_row(2019, 1), _row(2020, 2)]
    rows[0].update(target_margin=20.0, neutral_site=True)
    rows[1].update(target_margin=0.0, neutral_site=True)
    prediction = elo_predictions(rows, EloConfig(offseason_carry=0.5, update_rate=0.2))[1]
    assert prediction == pytest.approx(2.0)


def test_training_and_prediction_artifacts_are_deterministic() -> None:
    table = _table([_row(year, year) for year in range(2014, 2020)])
    fold = FrozenFold("f", "development", 2014, 2018, 2019)
    columns = feature_columns(table)
    first = fit_predict_fold(table, fold, "target_margin", "elastic_net", {"alpha": 0.01, "l1_ratio": 0.5}, columns)
    second = fit_predict_fold(table, fold, "target_margin", "elastic_net", {"alpha": 0.01, "l1_ratio": 0.5}, columns)
    assert np.array_equal(first[0], second[0])
    assert first[1] == second[1]


def test_prediction_artifact_schema_and_oof_order() -> None:
    rows = [
        {"horizon": "h", "target": "margin", "model_family": "ridge", "variant": "full", "kickoff": datetime(2020, 1, 2, tzinfo=UTC), "provider_game_id": 2},
        {"horizon": "h", "target": "margin", "model_family": "ridge", "variant": "full", "kickoff": datetime(2020, 1, 1, tzinfo=UTC), "provider_game_id": 1},
    ]
    table = prediction_table(rows)
    assert table["provider_game_id"].to_pylist() == [1, 2]


def test_identical_horizon_features_are_detected() -> None:
    first = _table([_row(2019, 1)])
    changed = _table([_row(2019, 1, feature=100.0)])
    assert horizon_features_identical({"a": first, "b": first}, feature_columns(first))
    assert not horizon_features_identical({"a": first, "b": changed}, feature_columns(first))


def test_paired_season_bootstrap_is_deterministic_and_paired() -> None:
    first = [
        {"provider_game_id": game, "season": 2020 + game % 2, "residual": float(game)} for game in range(1, 7)
    ]
    second = [
        {"provider_game_id": game, "season": 2020 + game % 2, "residual": float(game + 1)} for game in range(1, 7)
    ]
    result = paired_season_bootstrap(first, second, iterations=100)
    assert result == paired_season_bootstrap(first, second, iterations=100)
    assert result["paired_games"] == 6
    assert result["mae_difference"] == -1.0


def _manifest() -> dict[str, str]:
    return {"dataset_hash": "d", "feature_set_hash": "f", "availability_policy_version": "a"}


def _row(season: int, game_id: int, *, feature: float | None = None) -> dict[str, object]:
    kickoff = datetime(season, 9, 1, tzinfo=UTC) + timedelta(days=game_id)
    return {
        "canonical_event_id": f"e-{game_id}", "provider_game_id": game_id, "season": season, "week": 1,
        "kickoff": kickoff, "prediction_as_of": kickoff - timedelta(hours=24),
        "prediction_horizon": "24_hours_before_kickoff", "home_program_id": "A", "away_program_id": "B",
        "neutral_site": False, "conference_game": True, "postseason": False, "covid_2020_regime": season == 2020,
        "target_margin": float(game_id), "target_total": float(40 + game_id), "feature": float(game_id) if feature is None else feature,
    }


def _table(rows: list[dict[str, object]]) -> pa.Table:
    return pa.Table.from_pylist(sorted(rows, key=lambda row: (row["kickoff"], row["provider_game_id"])))
