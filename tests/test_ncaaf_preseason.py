from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pyarrow as pa
import pytest

from app.cli.ingest_ncaaf_preseason import build_plan
from app.research.ncaaf.preseason import (
    PRESEASON_AVAILABILITY_POLICY_VERSION,
    SourcePart,
    augment_feature_tables,
    build_team_name_map,
    normalize_preseason_facts,
)
from app.research.ncaaf.modeling import elo_predictions, frozen_folds
from app.research.ncaaf.preseason_modeling import _fit_power_prior, preseason_feature_columns
from app.research.ncaaf.preseason_supplement import _family_only_columns


KICKOFF = datetime(2024, 8, 31, 16, tzinfo=UTC)


def test_source_plan_is_bounded_and_keeps_2025_out() -> None:
    plan = build_plan(2014, 2024)
    assert len(plan) == 69
    assert plan[0] == ("info", {})
    assert plan[-1] == ("info", {})
    assert all(parameters.get("year", 2024) <= 2024 for _, parameters in plan)


def test_team_mapping_uses_canonical_identity_and_drops_name_conflicts() -> None:
    games = _games(
        [
            _game(1, 2024, "A", "B", "Alpha", "Beta"),
            _game(2, 2024, "C", "B", "Alpha", "Beta", kickoff=KICKOFF + timedelta(days=1)),
        ]
    )
    mapping = build_team_name_map(games)
    assert "alpha" not in mapping
    assert mapping["beta"] == "B"


def test_normalization_builds_preseason_families_without_zero_imputation() -> None:
    parts = [
        _part("player/returning", {"year": 2024}, [{"season": 2024, "team": "Alpha", "percentPPA": 0.61}]),
        _part("recruiting/teams", {"year": 2024}, [{"year": 2024, "team": "Alpha", "rank": 8, "points": 284.2}]),
        _part("talent", {"year": 2024}, [{"year": 2024, "team": "Alpha", "talent": 910.5}]),
        _part("roster", {"year": 2023}, [{"id": "qb1", "team": "Alpha", "position": "QB"}]),
        _part("roster", {"year": 2024}, [{"id": "qb1", "team": "Alpha", "position": "QB"}]),
        _part(
            "stats/player/season",
            {"year": 2023, "category": "passing"},
            [
                {"season": 2023, "team": "Alpha", "playerId": "qb1", "statType": "ATT", "stat": "300"},
                {"season": 2023, "team": "Alpha", "playerId": "qb1", "statType": "YDS", "stat": "3100"},
            ],
        ),
        _part(
            "coaches",
            {"minYear": 2014, "maxYear": 2024},
            [{"id": 77, "seasons": [{"year": 2023, "teamId": 1}, {"year": 2024, "teamId": 1}]}],
        ),
    ]
    table, report = normalize_preseason_facts(parts, normalized_games=_games([_game(1, 2024, "A", "B", "Alpha", "Beta")]))
    alpha = next(row for row in table.to_pylist() if row["program_id"] == "A" and row["season"] == 2024)
    assert alpha["returning_percent_ppa"] == pytest.approx(0.61)
    assert alpha["recruiting_rank"] == pytest.approx(8)
    assert alpha["talent_composite"] == pytest.approx(910.5)
    assert alpha["roster_continuity_ratio"] == pytest.approx(1.0)
    assert alpha["prior_leading_qb_returns"] is True
    assert alpha["head_coach_change"] is False
    assert alpha["transfer_in_count"] is None
    assert alpha["portal_available"] is False
    assert alpha["returning_passing_usage"] is None
    assert alpha["availability_policy_version"] == PRESEASON_AVAILABILITY_POLICY_VERSION
    assert report["strict_live_fidelity"] is False


def test_portal_uses_transfer_date_and_excludes_future_moves() -> None:
    games = _games([_game(1, 2024, "A", "B", "Alpha", "Beta")])
    before = (KICKOFF - timedelta(days=10)).isoformat()
    after = (KICKOFF + timedelta(days=1)).isoformat()
    records = [
        {"origin": "Beta", "destination": "Alpha", "position": "QB", "rating": 0.91, "transferDate": before},
        {"origin": "Beta", "destination": "Alpha", "position": "WR", "rating": 0.88, "transferDate": after},
    ]
    table, _ = normalize_preseason_facts([_part("player/portal", {"year": 2024}, records)], normalized_games=games)
    rows = {(row["program_id"], row["season"]): row for row in table.to_pylist()}
    assert rows[("A", 2024)]["transfer_in_count"] == 1
    assert rows[("A", 2024)]["transfer_in_qb_count"] == 1
    assert rows[("B", 2024)]["transfer_out_count"] == 1


def test_duplicate_source_manifest_does_not_duplicate_transfer_facts() -> None:
    games = _games([_game(1, 2024, "A", "B", "Alpha", "Beta")])
    part = _part("player/portal", {"year": 2024}, [{
        "origin": "Beta", "destination": "Alpha", "position": "QB", "rating": 0.91,
        "transferDate": (KICKOFF - timedelta(days=10)).isoformat(),
    }])
    table, _ = normalize_preseason_facts([part, part], normalized_games=games)
    alpha = next(row for row in table.to_pylist() if row["program_id"] == "A")
    assert alpha["transfer_in_count"] == 1


def test_prediction_as_of_controls_preseason_availability() -> None:
    games = _games([_game(1, 2024, "A", "B", "Alpha", "Beta")])
    facts, _ = normalize_preseason_facts(
        [_part("player/returning", {"year": 2024}, [{"season": 2024, "team": "Alpha", "percentPPA": 0.61}])],
        normalized_games=games,
    )
    base = _base_table(KICKOFF - timedelta(hours=24))
    augmented, coverage = augment_feature_tables({"24_hours_before_kickoff": base}, facts)
    row = augmented["24_hours_before_kickoff"].to_pylist()[0]
    assert row["home_preseason_available"] is False
    assert row["home_preseason_returning_percent_ppa"] is None
    assert coverage["24_hours_before_kickoff"]["available_team_sides"] == 0

    later = _base_table(KICKOFF + timedelta(minutes=1))
    augmented_later, _ = augment_feature_tables({"post_start_test": later}, facts)
    later_row = augmented_later["post_start_test"].to_pylist()[0]
    assert later_row["home_preseason_available"] is True
    assert later_row["home_preseason_returning_percent_ppa"] == pytest.approx(0.61)


def test_future_source_changes_do_not_alter_prior_feature_row() -> None:
    games = _games([_game(1, 2024, "A", "B", "Alpha", "Beta")])
    current = _part("player/portal", {"year": 2024}, [{
        "origin": "Beta", "destination": "Alpha", "position": "QB", "rating": 0.9,
        "transferDate": (KICKOFF - timedelta(days=2)).isoformat(),
    }])
    future = _part("player/portal", {"year": 2024}, [{
        "origin": "Beta", "destination": "Alpha", "position": "QB", "rating": 1.0,
        "transferDate": (KICKOFF + timedelta(days=2)).isoformat(),
    }], suffix="future")
    first, _ = normalize_preseason_facts([current], normalized_games=games)
    changed, _ = normalize_preseason_facts([current, future], normalized_games=games)
    first_row = next(row for row in first.to_pylist() if row["program_id"] == "A")
    changed_row = next(row for row in changed.to_pylist() if row["program_id"] == "A")
    for key in ("source_manifest_ids", "source_content_hashes", "ingested_at", "source_count"):
        first_row.pop(key)
        changed_row.pop(key)
    assert first_row == changed_row


def test_locked_holdout_is_rejected() -> None:
    with pytest.raises(ValueError, match="holdout"):
        normalize_preseason_facts([], normalized_games=_games([_game(1, 2024, "A", "B", "Alpha", "Beta")]), end_season=2025)


def test_model_feature_contract_excludes_identifiers_and_keeps_quality() -> None:
    facts, _ = normalize_preseason_facts(
        [_part("player/returning", {"year": 2024}, [{"season": 2024, "team": "Alpha", "percentPPA": 0.61}])],
        normalized_games=_games([_game(1, 2024, "A", "B", "Alpha", "Beta")]),
    )
    augmented, _ = augment_feature_tables({"test": _base_table(KICKOFF + timedelta(minutes=1))}, facts)
    columns = preseason_feature_columns(augmented["test"])
    assert "home_preseason_head_coach_id" not in columns
    assert "home_preseason_returning_percent_ppa" in columns
    assert "home_preseason_missing_family_count" in columns


def test_future_mutation_cannot_change_earlier_preseason_power_prediction() -> None:
    original = _model_table()
    mutated = _model_table(future_delta=1_000.0)
    fold = frozen_folds()[0]
    columns = ("home_preseason_returning_percent_ppa", "away_preseason_returning_percent_ppa")
    original_elo = np.asarray(elo_predictions(original.to_pylist()), dtype=float)
    mutated_elo = np.asarray(elo_predictions(mutated.to_pylist()), dtype=float)
    first, first_artifact = _fit_power_prior(original, fold, columns, original_elo)
    second, second_artifact = _fit_power_prior(mutated, fold, columns, mutated_elo)
    np.testing.assert_array_equal(first, second)
    assert first_artifact["artifact_hash"] == second_artifact["artifact_hash"]


def test_family_only_contract_does_not_smuggle_other_preseason_families() -> None:
    facts, _ = normalize_preseason_facts(
        [
            _part("player/returning", {"year": 2024}, [{"season": 2024, "team": "Alpha", "percentPPA": 0.61}]),
            _part("talent", {"year": 2024}, [{"year": 2024, "team": "Alpha", "talent": 910.5}]),
        ],
        normalized_games=_games([_game(1, 2024, "A", "B", "Alpha", "Beta")]),
    )
    augmented, _ = augment_feature_tables({"test": _base_table(KICKOFF + timedelta(minutes=1))}, facts)
    columns = _family_only_columns(augmented["test"], "target_margin", "returning")
    assert any("preseason_returning_" in name for name in columns)
    assert not any("preseason_talent_" in name for name in columns)


def _game(
    game_id: int,
    season: int,
    home_id: str,
    away_id: str,
    home: str,
    away: str,
    *,
    kickoff: datetime = KICKOFF,
) -> dict[str, object]:
    return {
        "provider_game_id": game_id,
        "season": season,
        "kickoff": kickoff,
        "home_program_id": home_id,
        "away_program_id": away_id,
        "home_provider_team_id": 1 if home_id == "A" else 3,
        "away_provider_team_id": 2,
        "home_team": home,
        "away_team": away,
    }


def _games(rows: list[dict[str, object]]) -> pa.Table:
    return pa.Table.from_pylist(rows)


def _base_table(as_of: datetime) -> pa.Table:
    return pa.Table.from_pylist(
        [{
            "provider_game_id": 1,
            "canonical_event_id": "event-1",
            "season": 2024,
            "week": 1,
            "kickoff": KICKOFF,
            "prediction_as_of": as_of,
            "prediction_horizon": "24_hours_before_kickoff",
            "home_program_id": "A",
            "away_program_id": "B",
            "target_margin": 7,
            "target_total": 51,
        }]
    )


def _part(
    endpoint: str,
    parameters: dict[str, object],
    records: list[dict[str, object]],
    *,
    suffix: str = "base",
) -> SourcePart:
    return SourcePart(
        manifest_id=f"{endpoint}-{parameters.get('year', 'all')}-{suffix}",
        endpoint=endpoint,
        parameters=parameters,
        content_hash=f"hash-{endpoint}-{parameters.get('year', 'all')}-{suffix}",
        retrieved_at=datetime(2026, 8, 30, tzinfo=UTC),
        response_bytes=100,
        records=records,
    )


def _model_table(*, future_delta: float = 0.0) -> pa.Table:
    rows: list[dict[str, object]] = []
    for season in range(2014, 2025):
        for game in range(2):
            margin = float((season - 2014) + game)
            feature = float(season - 2014) / 10
            if season == 2024:
                margin += future_delta
                feature += future_delta
            rows.append(
                {
                    "provider_game_id": season * 10 + game,
                    "canonical_event_id": f"event-{season}-{game}",
                    "season": season,
                    "week": game + 1,
                    "kickoff": datetime(season, 9, game + 1, tzinfo=UTC),
                    "prediction_horizon": "24_hours_before_kickoff",
                    "home_program_id": f"home-{game}",
                    "away_program_id": f"away-{game}",
                    "neutral_site": False,
                    "target_margin": margin,
                    "target_total": 50.0,
                    "home_preseason_returning_percent_ppa": feature,
                    "away_preseason_returning_percent_ppa": -feature,
                }
            )
    return pa.Table.from_pylist(rows)
