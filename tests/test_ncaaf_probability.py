from __future__ import annotations

import math
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from app.research.ncaaf.calibration import (
    HETEROSKEDASTIC_VERSION,
    NORMAL_VERSION,
    fit_chronological_distribution,
    paired_season_bootstrap,
    run_probability_tournament,
    shifted_distribution,
)
from app.research.ncaaf.probability import (
    EmpiricalGridDistribution,
    NormalDistribution,
    StudentTDistribution,
    binary_scores,
    fit_empirical_grid,
    fit_student_t,
    integer_mass,
    moneyline_probabilities,
    spread_probabilities,
    total_probabilities,
)


def test_normal_cdf_and_quantiles_are_coherent() -> None:
    distribution = NormalDistribution(0, 1)
    assert distribution.cdf(0) == pytest.approx(0.5)
    assert distribution.ppf(0.5) == pytest.approx(0)
    assert distribution.cdf(distribution.ppf(0.9)) == pytest.approx(0.9)


def test_student_t_has_heavier_tails_than_normal() -> None:
    student = StudentTDistribution(0, 1, 3)
    normal = NormalDistribution(0, 1)
    assert student.ppf(0.99) > normal.ppf(0.99)
    location, scale, degrees = fit_student_t([-3, -2, -1, 0, 1, 2, 8])
    assert math.isfinite(location)
    assert scale > 0
    assert degrees in {3.0, 5.0, 8.0, 15.0, 30.0}


def test_empirical_residual_distribution_is_deterministic_and_monotonic() -> None:
    first = fit_empirical_grid([-3, -2, -1, 0, 1, 2, 7], pool_id="pool")
    second = fit_empirical_grid([-3, -2, -1, 0, 1, 2, 7], pool_id="pool")
    assert np.array_equal(first.residual_cdf, second.residual_cdf)
    assert np.all(np.diff(first.residual_cdf) >= 0)
    assert first.cdf(-100) == 0
    assert first.cdf(100) == 1


def test_integer_discretization_preserves_positive_mass() -> None:
    distribution = NormalDistribution(3, 10)
    masses = [integer_mass(distribution, integer) for integer in range(-100, 101)]
    assert all(value >= 0 for value in masses)
    assert sum(masses) == pytest.approx(1, abs=1e-10)


def test_moneyline_conditions_out_impossible_completed_game_tie() -> None:
    probabilities = moneyline_probabilities(NormalDistribution(0, 10))
    assert probabilities.win == pytest.approx(0.5)
    assert probabilities.loss == pytest.approx(0.5)
    assert probabilities.push == 0
    assert probabilities.audit is not None
    assert probabilities.audit["conditioned_tie_mass"] > 0


@pytest.mark.parametrize("line", [-7.5, -3.5, 0.5, 3.5, 7.5])
def test_half_point_spread_has_no_push(line: float) -> None:
    probabilities = spread_probabilities(NormalDistribution(0, 14), line)
    assert probabilities.push == 0
    assert probabilities.win + probabilities.loss == pytest.approx(1)


def test_integer_spread_has_nonzero_push_and_exact_settlement_mass() -> None:
    distribution = NormalDistribution(3, 10)
    probabilities = spread_probabilities(distribution, -3)
    assert probabilities.push == pytest.approx(integer_mass(distribution, 3))
    assert probabilities.push > 0
    assert probabilities.win + probabilities.push + probabilities.loss == pytest.approx(1)


@pytest.mark.parametrize("line", [41.5, 45.5, 52.5])
def test_half_point_total_has_no_push(line: float) -> None:
    probabilities = total_probabilities(NormalDistribution(48, 14), line)
    assert probabilities.push == 0
    assert probabilities.win + probabilities.loss == pytest.approx(1)


def test_integer_total_has_nonzero_push() -> None:
    distribution = NormalDistribution(48, 14)
    probabilities = total_probabilities(distribution, 48)
    assert probabilities.push == pytest.approx(integer_mass(distribution, 48))
    assert probabilities.win + probabilities.push + probabilities.loss == pytest.approx(1)


def test_total_under_reverses_win_and_loss_without_changing_push() -> None:
    distribution = NormalDistribution(48, 14)
    over = total_probabilities(distribution, 45, over=True)
    under = total_probabilities(distribution, 45, over=False)
    assert under.win == pytest.approx(over.loss)
    assert under.loss == pytest.approx(over.win)
    assert under.push == pytest.approx(over.push)


def test_invalid_distribution_and_line_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        NormalDistribution(0, 0)
    with pytest.raises(ValueError):
        NormalDistribution(float("nan"), 1)
    with pytest.raises(ValueError):
        spread_probabilities(NormalDistribution(0, 1), float("inf"))


def _historical_rows(*, future_delta: float = 0) -> list[dict[str, object]]:
    rows = []
    for index in range(600):
        season = 2019 if index < 300 else 2020
        residual = float((index % 31) - 15)
        if season == 2020:
            residual += future_delta
        rows.append(
            {
                "provider_game_id": index,
                "season": season,
                "week": index % 14,
                "horizon": "24_hours_before_kickoff",
                "target": "margin",
                "model_family": "elo",
                "variant": "ncaaf-margin-power-v1",
                "residual": residual,
                "home_pbp_coverage_ratio": 1.0,
                "away_pbp_coverage_ratio": 1.0,
            }
        )
    return rows


def test_chronological_fit_rejects_future_residuals() -> None:
    rows = _historical_rows()
    with pytest.raises(ValueError, match="future residuals"):
        fit_chronological_distribution(rows, family=NORMAL_VERSION, evaluation_season=2020)


def test_future_residual_mutation_cannot_change_prior_fit() -> None:
    first = [row for row in _historical_rows() if cast(int, row["season"]) < 2020]
    changed = [row for row in _historical_rows(future_delta=10_000) if cast(int, row["season"]) < 2020]
    fit_a, distribution_a, _ = fit_chronological_distribution(
        [*first, *first], family=NORMAL_VERSION, evaluation_season=2020
    )
    fit_b, distribution_b, _ = fit_chronological_distribution(
        [*changed, *changed], family=NORMAL_VERSION, evaluation_season=2020
    )
    assert fit_a.pool_id == fit_b.pool_id
    assert distribution_a.parameters() == distribution_b.parameters()


def test_quality_aware_scale_can_widen_low_quality_rows() -> None:
    rows = []
    for index in range(800):
        low = index >= 400
        rows.append(
            {
                "provider_game_id": index,
                "season": 2019,
                "week": 6,
                "horizon": "24_hours_before_kickoff",
                "target": "margin",
                "model_family": "elo",
                "variant": "ncaaf-margin-power-v1",
                "residual": float((index % (41 if low else 11)) - (20 if low else 5)),
                "home_pbp_coverage_ratio": 0.2 if low else 1.0,
                "away_pbp_coverage_ratio": 0.2 if low else 1.0,
            }
        )
    _, template, scales = fit_chronological_distribution(
        rows, family=HETEROSKEDASTIC_VERSION, evaluation_season=2020
    )
    high = shifted_distribution(template, 0, group_scale=scales["later|high"])
    low_distribution = shifted_distribution(template, 0, group_scale=scales["later|low"])
    assert low_distribution.scale > high.scale


def test_empirical_shift_moves_location_without_mutating_pool() -> None:
    template = fit_empirical_grid([-2, -1, 0, 1, 2], pool_id="pool")
    shifted = shifted_distribution(template, 10)
    assert isinstance(shifted, EmpiricalGridDistribution)
    assert shifted.location == 10
    assert template.location == 0


def test_binary_scores_are_numerically_safe_at_boundaries() -> None:
    assert math.isfinite(binary_scores(0, False)["log_loss"])
    assert math.isfinite(binary_scores(1, True)["log_loss"])


def test_paired_bootstrap_is_deterministic() -> None:
    rows_a = [{"provider_game_id": i, "season": 2020 + i % 2, "nll": float(i % 5)} for i in range(20)]
    rows_b = [{"provider_game_id": i, "season": 2020 + i % 2, "nll": float(i % 3)} for i in range(20)]
    first = paired_season_bootstrap(rows_a, rows_b, score="nll", iterations=50)
    second = paired_season_bootstrap(rows_a, rows_b, score="nll", iterations=50)
    assert first == second


def test_probability_tournament_rejects_holdout_before_reading_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="locked 2025 holdout"):
        run_probability_tournament(tmp_path / "missing", tmp_path / "out", end_season=2025)
