from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.research.ncaaf.market_comparison import (
    CONSENSUS_VERSION,
    PRIMARY_MARKET_HORIZON,
    VIG_REMOVAL_VERSION,
    build_consensus_rows,
    build_market_feature_rows,
    build_residual_rows,
    join_football_and_market,
    market_expected_margin,
    proportional_no_vig,
    select_oof_predictions,
    settlement_labels,
)

NOW = datetime(2024, 9, 7, 12, tzinfo=UTC)


def observation(book: str, market: str, side: str, point: float | None, odds: int, *, snapshot: datetime = NOW - timedelta(minutes=5), event: str = "event-1", horizon: str = PRIMARY_MARKET_HORIZON) -> dict[str, object]:
    return {
        "canonical_event_id": event, "cfbd_game_id": 1, "season": 2024, "week": 2,
        "scheduled_kickoff": NOW + timedelta(hours=3), "horizon": horizon,
        "requested_at": NOW, "snapshot_at": snapshot, "sportsbook": book,
        "supported_sportsbook": True, "market_type": market, "side": side,
        "point": point, "american_odds": odds, "source_content_hash": f"hash-{book}",
        "source_market_dataset_hash": "market-hash",
    }


def paired(book: str, market: str, point: float | None, odds_a: int = -110, odds_b: int = -110) -> list[dict[str, object]]:
    if market == "h2h":
        return [observation(book, market, "home", None, odds_a), observation(book, market, "away", None, odds_b)]
    if market == "spreads":
        return [observation(book, market, "home", point, odds_a), observation(book, market, "away", -float(point or 0), odds_b)]
    return [observation(book, market, "over", point, odds_a), observation(book, market, "under", point, odds_b)]


def prediction(*, season: int = 2024, event: str = "event-1", horizon: str = "game_day_morning", target: str = "margin", family: str = "elo", variant: str = "ncaaf-margin-power-v1", cutoff: int = 2023) -> dict[str, object]:
    return {
        "canonical_event_id": event, "season": season, "week": 2, "horizon": horizon,
        "target": target, "actual": 7.0, "prediction": 4.0, "model_family": family,
        "model_version": "ncaaf-baseline-tournament-v1", "variant": variant,
        "fold_id": "fold", "training_cutoff": cutoff, "feature_set_hash": "feature",
        "dataset_hash": "football", "football_run_hash": "run",
    }


def test_proportional_vig_removal_is_exact_and_versioned() -> None:
    values = proportional_no_vig((Decimal("0.55"), Decimal("0.50")))
    assert sum(values) == Decimal(1)
    assert values[0] == Decimal("0.523809523810")
    assert (VIG_REMOVAL_VERSION, CONSENSUS_VERSION) == ("proportional-v1", "unweighted-median-v1")


def test_consensus_uses_complete_supported_exact_line_pairs() -> None:
    rows = paired("draftkings", "spreads", -3.5) + paired("fanduel", "spreads", -3.5)
    rows += paired("betmgm", "spreads", -4.5)
    consensus, excluded = build_consensus_rows(rows)
    assert not excluded
    assert len(consensus) == 1
    assert consensus[0]["consensus_point"] == -3.5
    assert consensus[0]["complete_book_count"] == 2
    assert consensus[0]["all_complete_book_count"] == 3


def test_mismatched_spread_and_total_points_are_not_paired() -> None:
    rows = paired("draftkings", "spreads", -3.5)
    rows[1]["point"] = 4.0
    rows += paired("fanduel", "spreads", -3.5)
    consensus, excluded = build_consensus_rows(rows)
    assert consensus == []
    assert excluded[0]["reason"] == "fewer_than_two_complete_books_at_exact_line"


def test_sign_conventions_and_push_labels() -> None:
    assert market_expected_margin(-7.0) == 7.0
    assert market_expected_margin(3.0) == -3.0
    labels = settlement_labels(7.0, 52.0, -7.0, 52.0)
    assert labels == {"moneyline_result": "home_win", "spread_result": "push", "total_result": "push"}


def test_holdout_and_in_sample_predictions_are_rejected() -> None:
    with pytest.raises(ValueError, match="2025"):
        select_oof_predictions([prediction(season=2025)], "run")
    with pytest.raises(ValueError, match="in-sample"):
        select_oof_predictions([prediction(cutoff=2024)], "run")


def test_same_horizon_join_and_identity_are_required() -> None:
    consensus, _ = build_consensus_rows(paired("draftkings", "h2h", None) + paired("fanduel", "h2h", None))
    selected = select_oof_predictions([prediction()], "run")
    joined, _ = join_football_and_market(consensus, selected)
    assert len(joined) == 1
    mismatch, exclusions = join_football_and_market(consensus, [{**selected[0], "canonical_event_id": "other"}])
    assert mismatch == []
    assert exclusions[0]["reason"] == "market_state_unavailable"


def test_future_snapshot_cannot_enter_morning_join() -> None:
    rows = paired("draftkings", "h2h", None) + paired("fanduel", "h2h", None)
    consensus, _ = build_consensus_rows(rows)
    consensus[0]["snapshot_max"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError, match="future"):
        join_football_and_market(consensus, select_oof_predictions([prediction()], "run"))


def test_future_snapshot_is_rejected_during_consensus() -> None:
    rows = paired("draftkings", "h2h", None) + paired("fanduel", "h2h", None)
    for row in rows:
        row["snapshot_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError, match="future"):
        build_consensus_rows(rows)


def test_time_travel_later_snapshot_does_not_change_morning_row() -> None:
    morning = paired("draftkings", "h2h", None) + paired("fanduel", "h2h", None)
    before, _ = build_consensus_rows(morning)
    later = deepcopy(morning)
    for row in later:
        row["horizon"] = "60_minutes_before_kickoff"
        row["requested_at"] = NOW + timedelta(hours=2)
        row["snapshot_at"] = NOW + timedelta(hours=2) - timedelta(minutes=5)
        row["american_odds"] = -150
    after, _ = build_consensus_rows([*morning, *later])
    assert before[0] == next(row for row in after if row["horizon"] == PRIMARY_MARKET_HORIZON)


def test_diagnostic_horizon_is_never_primary() -> None:
    rows = paired("draftkings", "h2h", None) + paired("fanduel", "h2h", None)
    for row in rows:
        row["horizon"] = "60_minutes_before_kickoff"
    consensus, _ = build_consensus_rows(rows)
    assert consensus[0]["research_role"] == "diagnostic_only"


def test_residual_targets_preserve_pushes() -> None:
    spread = {"market_type": "spreads", "consensus_point": -7.0, "actual": 7.0}
    total = {"market_type": "totals", "consensus_point": 52.0, "actual": 52.0}
    rows = build_residual_rows([spread, total])
    assert rows[0]["market_residual_target"] == 0
    assert rows[0]["spread_result"] == "push"
    assert rows[1]["total_result"] == "push"


def test_common_cohort_requires_both_margin_markets() -> None:
    base = prediction()
    base.update({"horizon": PRIMARY_MARKET_HORIZON, "research_role": "primary", "scheduled_kickoff": NOW,
                 "source_market_dataset_hash": "market", "vig_removal_version": VIG_REMOVAL_VERSION,
                 "consensus_version": CONSENSUS_VERSION, "complete_book_count": 2, "model_variant": base["variant"],
                 "football_prediction": base["prediction"], "football_dataset_hash": base["dataset_hash"],
                 "probability_dispersion": "0.01", "side_1_consensus_probability": "0.55"})
    spread = {**base, "market_type": "spreads", "consensus_point": -3.5}
    assert build_market_feature_rows([spread]) == []
    moneyline = {**base, "market_type": "h2h", "consensus_point": None}
    result = build_market_feature_rows([spread, moneyline])
    assert len(result) == 1
    assert result[0]["market_expected_margin"] == 3.5


def test_consensus_build_is_deterministic() -> None:
    rows = paired("draftkings", "totals", 52.0) + paired("fanduel", "totals", 52.0)
    assert build_consensus_rows(rows) == build_consensus_rows(reversed(rows))
