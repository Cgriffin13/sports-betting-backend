from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pyarrow as pa
import pytest

from app.research.ncaaf.key_numbers import fit_prior_discrete_pool, run_key_number_tournament
from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.challenger_distribution import run_challenger_distribution
from app.research.ncaaf.modeling import feature_columns, frozen_folds
from app.research.ncaaf.probability import (
    EmpiricalDiscreteDistribution,
    empirical_discrete_distribution,
    fit_empirical_discrete_ratios,
    normal_integer_lattice,
    spread_probabilities,
)
from app.research.ncaaf.strong_models import (
    CONFIGURATIONS,
    fit_predict_tree_fold,
    paired_block_comparison,
    run_strong_model_tournament,
    tree_configuration,
)


def _model_table(*, future_delta: float = 0.0, include_holdout: bool = False) -> pa.Table:
    rows = []
    last_season = 2025 if include_holdout else 2024
    for season in range(2014, last_season + 1):
        for game in range(2):
            target_margin = float((season - 2014) + game)
            if season == 2024:
                target_margin += future_delta
            rows.append(
                {
                    "canonical_event_id": f"event-{season}-{game}", "provider_game_id": season * 10 + game,
                    "season": season, "week": game + 1,
                    "kickoff": datetime(season, 9, game + 1, tzinfo=UTC),
                    "prediction_as_of": datetime(season, 8, game + 1, tzinfo=UTC),
                    "prediction_horizon": "24_hours_before_kickoff",
                    "home_program_id": f"home-{game}", "away_program_id": f"away-{game}",
                    "target_margin": target_margin, "target_total": 45.0 + game,
                    "neutral_site": bool(game), "feature_a": float(season - 2014),
                    "home_pbp_coverage_ratio": 1.0, "away_pbp_coverage_ratio": 1.0,
                    "home_current_season_games": game, "away_current_season_games": game,
                    "covid_2020_regime": season == 2020,
                }
            )
    return pa.Table.from_pylist(rows)


def _tiny_config(name: str = "tiny") -> dict[str, object]:
    return {
        "name": name, "max_depth": 2, "num_leaves": 7, "learning_rate": 0.1,
        "n_estimators": 4, "row_subsample": 1.0, "feature_subsample": 1.0,
        "min_child_samples": 2, "l2": 1.0,
    }


@pytest.mark.parametrize("family", ["xgboost", "lightgbm", "catboost"])
def test_tree_configuration_is_seeded_single_threaded_and_deterministic(family: str) -> None:
    first = tree_configuration(family, CONFIGURATIONS[0])
    second = tree_configuration(family, CONFIGURATIONS[0])
    assert first == second
    assert _seed_value(first) == 53105
    assert _thread_value(first) == 1


def _seed_value(parameters: dict[str, object]) -> int:
    value = parameters.get("random_state", parameters.get("random_seed", -1))
    assert isinstance(value, int)
    return value


def _thread_value(parameters: dict[str, object]) -> int:
    value = parameters.get("n_jobs", parameters.get("thread_count", -1))
    assert isinstance(value, int)
    return value


def test_tree_fold_rejects_2025_before_model_fit() -> None:
    table = _model_table(include_holdout=True)
    with pytest.raises(ValueError, match="locked 2025"):
        fit_predict_tree_fold(
            table, frozen_folds()[0], "target_margin", "xgboost", _tiny_config(), feature_columns(table)
        )


def test_future_outcome_mutation_cannot_change_earlier_tree_prediction() -> None:
    original = _model_table()
    mutated = _model_table(future_delta=1_000)
    fold = frozen_folds()[0]
    columns = feature_columns(original)
    first, first_artifact = fit_predict_tree_fold(
        original, fold, "target_margin", "xgboost", _tiny_config(), columns
    )
    second, second_artifact = fit_predict_tree_fold(
        mutated, fold, "target_margin", "xgboost", _tiny_config(), columns
    )
    np.testing.assert_array_equal(first, second)
    assert first_artifact["artifact_hash"] == second_artifact["artifact_hash"]


def test_paired_block_comparison_is_deterministic() -> None:
    challenger = [
        {"provider_game_id": season, "season": season, "residual": 1.0} for season in range(2019, 2025)
    ]
    baseline = [
        {"provider_game_id": season, "season": season, "residual": 2.0} for season in range(2019, 2025)
    ]
    assert paired_block_comparison(challenger, baseline, iterations=50) == paired_block_comparison(
        challenger, baseline, iterations=50
    )


def test_empirical_discrete_pmf_is_valid_and_key_mass_is_data_driven() -> None:
    actuals = [3.0 if index % 5 == 0 else float((index % 21) - 10) for index in range(400)]
    locations = [0.0] * 400
    scales = [14.0] * 400
    support, ratios = fit_empirical_discrete_ratios(actuals, locations, scales)
    distribution = empirical_discrete_distribution(0.0, 14.0, support, ratios, pool_id="test")
    assert isinstance(distribution, EmpiricalDiscreteDistribution)
    assert np.all(distribution.mass >= 0)
    assert math.isclose(float(np.sum(distribution.mass)), 1.0, abs_tol=1e-12)
    _, normal_mass = normal_integer_lattice(0.0, 14.0)
    assert distribution.pdf(3.0) > normal_mass[3 - int(support[0])]


def test_integer_push_and_half_point_zero_push_for_discrete_distribution() -> None:
    support, mass = normal_integer_lattice(7.0, 14.0)
    distribution = EmpiricalDiscreteDistribution(support, mass, "test")
    integer = spread_probabilities(distribution, -7.0)
    half = spread_probabilities(distribution, -7.5)
    assert integer.push > 0
    assert half.push == 0
    assert math.isclose(integer.win + integer.push + integer.loss, 1.0, abs_tol=1e-12)


def test_future_residual_cannot_enter_prior_discrete_pool() -> None:
    rows = [
        {
            "provider_game_id": index, "season": 2019, "horizon": "24_hours_before_kickoff",
            "week": 4, "prediction": 0.0, "actual": float(index % 11), "residual": float(index % 11),
            "home_pbp_coverage_ratio": 1.0, "away_pbp_coverage_ratio": 1.0,
        }
        for index in range(400)
    ]
    first = fit_prior_discrete_pool(rows, evaluation_season=2020)
    future = {**rows[0], "season": 2020, "actual": 1_000.0, "residual": 1_000.0}
    with pytest.raises(ValueError, match="future outcomes"):
        fit_prior_discrete_pool([*rows, future], evaluation_season=2020)
    second = fit_prior_discrete_pool(rows, evaluation_season=2020)
    np.testing.assert_array_equal(first[3], second[3])
    np.testing.assert_allclose(first[4], second[4])
    assert first[5] == second[5]


def test_tournament_guards_holdout_before_reading_artifacts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="locked 2025"):
        run_strong_model_tournament(
            cast(ResearchArtifactStore, None), {},
            baseline_root=tmp_path, output_root=tmp_path, end_season=2025,
        )
    with pytest.raises(ValueError, match="locked 2025"):
        run_key_number_tournament(tmp_path, tmp_path, end_season=2025)
    with pytest.raises(ValueError, match="locked 2025"):
        run_challenger_distribution(tmp_path, tmp_path, tmp_path, end_season=2025)
