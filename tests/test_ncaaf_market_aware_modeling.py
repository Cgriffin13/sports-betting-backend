from __future__ import annotations

from copy import deepcopy

import pytest

from app.research.ncaaf.market_aware_modeling import (
    PRIMARY_HORIZON,
    _blend_rows,
    _probability_rows,
    canonical_market_rows,
    constrained_blend_weight,
)


def market_row(*, event_id: str = "event-1", season: int = 2023, target: str = "margin") -> dict[str, object]:
    return {
        "canonical_event_id": event_id,
        "season": season,
        "week": 4,
        "scheduled_kickoff": "2023-09-23T19:30:00Z",
        "horizon": PRIMARY_HORIZON,
        "research_role": "primary",
        "target": target,
        "actual": 10.0 if target == "margin" else 57.0,
        "feature_set_hash": "features",
        "football_dataset_hash": "football",
        "source_market_dataset_hash": "market",
        "market_home_no_vig_probability": 0.62 if target == "margin" else None,
        "market_home_spread": -6.5 if target == "margin" else None,
        "market_expected_margin": 6.5 if target == "margin" else None,
        "market_consensus_total": 54.5 if target == "total" else None,
        "market_moneyline_books": 3 if target == "margin" else None,
        "market_spread_books": 3 if target == "margin" else None,
        "market_total_books": 3 if target == "total" else None,
        "market_moneyline_dispersion": 0.02 if target == "margin" else None,
        "market_spread_dispersion": 0.03 if target == "margin" else None,
        "market_total_dispersion": 0.03 if target == "total" else None,
        "model_family": "elo",
        "model_variant": "ncaaf-margin-power-v1",
    }


def point_row(
    *, event_id: str, season: int, candidate: str, prediction: float, actual: float, target: str = "margin"
) -> dict[str, object]:
    return {
        **market_row(event_id=event_id, season=season, target=target),
        "candidate": candidate,
        "architecture": "market_only" if candidate == "market_consensus" else "football_only",
        "prediction": prediction,
        "actual": actual,
    }


def test_canonical_market_rows_collapses_candidate_duplicates() -> None:
    first = market_row()
    second = {**first, "model_family": "ridge", "model_variant": "full_v1"}
    result = canonical_market_rows([first, second])
    assert len(result) == 1
    assert result[0]["canonical_event_id"] == "event-1"


def test_canonical_market_rows_rejects_inconsistent_state_and_holdout() -> None:
    first = market_row()
    inconsistent = {**first, "market_home_spread": -7.0}
    with pytest.raises(ValueError, match="disagree"):
        canonical_market_rows([first, inconsistent])
    with pytest.raises(ValueError, match="2025"):
        canonical_market_rows([{**first, "season": 2025}])


def test_later_horizons_never_enter_primary_rows() -> None:
    later = {**market_row(), "horizon": "60_minutes_before_kickoff", "research_role": "diagnostic_only"}
    assert canonical_market_rows([later]) == []


def test_constrained_blend_weight_is_oof_and_bounded() -> None:
    rows = [
        {"actual": 10.0, "market_prediction": 6.0, "football_prediction": 8.0},
        {"actual": -3.0, "market_prediction": -1.0, "football_prediction": -4.0},
    ]
    weight = constrained_blend_weight(rows)
    assert 0 <= weight <= 1
    assert weight == pytest.approx(1.0)


def test_future_outcome_cannot_change_earlier_blend() -> None:
    rows = []
    for season, actual in ((2020, 10.0), (2021, 4.0), (2022, -3.0), (2023, 8.0), (2024, 50.0)):
        event = f"event-{season}"
        rows.extend(
            [
                point_row(event_id=event, season=season, candidate="market_consensus", prediction=2.0, actual=actual),
                point_row(event_id=event, season=season, candidate="football_power", prediction=5.0, actual=actual),
            ]
        )
    original = _blend_rows(rows)
    changed = deepcopy(rows)
    for row in changed:
        if row["season"] == 2024:
            row["actual"] = -100.0
    rerun = _blend_rows(changed)
    original_2023 = [row for row in original if row["season"] == 2023]
    rerun_2023 = [row for row in rerun if row["season"] == 2023]
    assert original_2023 == rerun_2023


def test_common_cohort_has_one_market_and_component_row_per_game() -> None:
    rows = []
    for season in (2020, 2021):
        event = f"event-{season}"
        rows.append(point_row(event_id=event, season=season, candidate="market_consensus", prediction=1.0, actual=3.0))
        rows.append(point_row(event_id=event, season=season, candidate="football_power", prediction=2.0, actual=3.0))
    market_ids = {row["canonical_event_id"] for row in rows if row["candidate"] == "market_consensus"}
    football_ids = {row["canonical_event_id"] for row in rows if row["candidate"] == "football_power"}
    assert market_ids == football_ids


def test_probability_evaluation_is_target_specific_and_push_aware() -> None:
    rows = []
    consensus = {}
    for index in range(105):
        season = 2020 if index < 100 else 2021
        event = f"event-{index}"
        row = point_row(
            event_id=event,
            season=season,
            candidate="market_consensus",
            prediction=3.0,
            actual=float(index % 15),
        )
        row.update(
            {
                "market_expectation": 3.0,
                "market_home_spread": -3.0,
                "market_home_no_vig_probability": 0.6,
            }
        )
        rows.append(row)
        consensus[(event, "spreads")] = {"side_1_consensus_probability": "0.5"}
    output = _probability_rows(rows, consensus)
    assert len(output) == 5
    for row in output:
        win = row["line_win_probability"]
        push = row["line_push_probability"]
        loss = row["line_loss_probability"]
        assert isinstance(win, float)
        assert isinstance(push, float)
        assert isinstance(loss, float)
        total = win + push + loss
        assert total == pytest.approx(1.0)
        assert push > 0
        assert row["moneyline_probability_source"] == "market_no_vig_consensus"
