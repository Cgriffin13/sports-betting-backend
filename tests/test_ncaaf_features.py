from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from app.research.ncaaf.artifacts import ResearchArtifactStore, artifact_dict, dataset_hash, manifest_has_secret
from app.research.ncaaf.contracts import (
    MorningPolicy,
    PredictionHorizon,
    feature_set_hash,
    prediction_as_of,
    reconstructed_available_at,
    validate_feature_seasons,
)
from app.research.ncaaf.feature_registry import feature_definition, feature_definitions
from app.research.ncaaf.features import TeamGameMetric, aggregate_team_games, build_feature_rows, feature_table
from app.research.ncaaf.reconciliation import reconcile_pbp


def test_reconstructed_availability_and_horizons_are_explicit() -> None:
    kickoff = datetime(2024, 9, 7, 16, tzinfo=UTC)
    assert reconstructed_available_at(kickoff) == kickoff + timedelta(hours=24)
    assert prediction_as_of(kickoff, PredictionHorizon.HOURS_24) == kickoff - timedelta(hours=24)
    assert prediction_as_of(kickoff, PredictionHorizon.MINUTES_60) == kickoff - timedelta(minutes=60)
    assert prediction_as_of(
        kickoff,
        PredictionHorizon.GAME_DAY_MORNING,
        first_kickoff_of_day=kickoff,
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    ) == kickoff - timedelta(hours=3)


def test_feature_build_rejects_locked_2025_by_default() -> None:
    validate_feature_seasons(2014, 2024)
    with pytest.raises(ValueError, match="sealed|holdout"):
        validate_feature_seasons(2014, 2025)
    validate_feature_seasons(2025, 2025, allow_holdout=True)


def test_team_game_aggregation_definitions_and_missingness() -> None:
    kickoff = datetime(2024, 8, 31, 19, tzinfo=UTC)
    games = [_game(1, kickoff, "A", "B")]
    plays = [
        _play(1, "A", "B", "Pass Reception", 0.4, 20, down=1, distance=10),
        _play(1, "A", "B", "Rush", -0.2, 4, down=2, distance=10),
        _play(1, "B", "A", "Sack", -1.0, -7, down=3, distance=6),
    ]
    drives = [
        {
            "provider_game_id": 1,
            "offense_program_id": "A",
            "defense_program_id": "B",
            "identity_resolved": True,
            "yards": 50,
            "points": 7,
        },
        {
            "provider_game_id": 1,
            "offense_program_id": "B",
            "defense_program_id": "A",
            "identity_resolved": True,
            "yards": 10,
            "points": 0,
        },
    ]
    stats = [{"provider_game_id": 1, "program_id": "A"}]
    result = {item.program_id: item for item in aggregate_team_games(games, plays, drives, stats)}
    assert result["A"].metrics["off_ppa"] == pytest.approx(0.1)
    assert result["A"].metrics["def_ppa_allowed"] == pytest.approx(-1.0)
    assert result["A"].metrics["pass_ppa"] == pytest.approx(0.4)
    assert result["A"].metrics["rush_ppa"] == pytest.approx(-0.2)
    assert result["A"].metrics["success_rate"] == pytest.approx(0.5)
    assert result["A"].metrics["explosive_rate"] == pytest.approx(0.5)
    assert result["A"].metrics["points_per_drive"] == pytest.approx(7.0)
    assert result["A"].metrics["havoc_rate"] == pytest.approx(1.0)
    assert result["A"].team_stats_present is True
    assert result["B"].team_stats_present is False


def test_target_and_future_games_cannot_leak_backward() -> None:
    target_time = datetime(2024, 9, 14, 19, tzinfo=UTC)
    prior = _metric(1, 2024, target_time - timedelta(days=14), "A", "B", 0.2)
    opponent_prior = _metric(2, 2024, target_time - timedelta(days=13), "B", "D", -0.1)
    target_fact = _metric(3, 2024, target_time, "A", "C", 99.0)
    future = _metric(4, 2024, target_time + timedelta(days=7), "B", "D", 100.0)
    game = _game(3, target_time, "A", "C")
    baseline = build_feature_rows(
        [game],
        [prior, opponent_prior, target_fact, future],
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    changed = build_feature_rows(
        [game],
        [
            prior,
            opponent_prior,
            replace(target_fact, metrics=_metrics(-999.0)),
            replace(future, metrics=_metrics(-999.0)),
        ],
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    assert baseline == changed
    assert baseline["home_off_ppa_last3"] == pytest.approx(0.2)
    assert baseline["home_prior_games_available"] == 1


def test_target_score_is_label_only_and_cannot_change_features() -> None:
    target_time = datetime(2024, 9, 14, 19, tzinfo=UTC)
    game = _game(3, target_time, "A", "C")
    changed_game = {**game, "target_margin": -40, "target_total": 100}
    history = [_metric(1, 2024, target_time - timedelta(days=14), "A", "B", 0.2)]
    original = build_feature_rows(
        [game],
        history,
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    changed = build_feature_rows(
        [changed_game],
        history,
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    for key in ("target_margin", "target_total"):
        original.pop(key)
        changed.pop(key)
    assert original == changed


def test_morning_slate_uses_eastern_calendar_day_not_utc_day() -> None:
    early = _game(1, datetime(2024, 9, 7, 16, tzinfo=UTC), "A", "B")
    late = _game(2, datetime(2024, 9, 8, 1, tzinfo=UTC), "C", "D")
    rows = build_feature_rows(
        [early, late],
        [],
        horizons=(PredictionHorizon.GAME_DAY_MORNING,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )
    assert rows[0]["prediction_as_of"] == rows[1]["prediction_as_of"] == datetime(2024, 9, 7, 13, tzinfo=UTC)


def test_late_available_correction_cannot_masquerade_as_prior_fact() -> None:
    target_time = datetime(2024, 9, 14, 19, tzinfo=UTC)
    prior = _metric(1, 2024, target_time - timedelta(days=14), "A", "B", 0.2)
    late = replace(prior, provider_game_id=2, metrics=_metrics(50.0), available_at=target_time + timedelta(hours=1))
    row = build_feature_rows(
        [_game(3, target_time, "A", "C")],
        [prior, late],
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    assert row["home_off_ppa_last3"] == pytest.approx(0.2)
    assert row["home_prior_games_available"] == 1


def test_early_season_prior_weights_shift_with_current_games() -> None:
    target_time = datetime(2024, 9, 21, 19, tzinfo=UTC)
    history = [
        _metric(1, 2023, datetime(2023, 11, 1, 19, tzinfo=UTC), "A", "B", 0.4),
        _metric(2, 2024, target_time - timedelta(days=14), "A", "B", 0.0),
    ]
    row = build_feature_rows(
        [_game(3, target_time, "A", "C")],
        history,
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    assert row["home_current_weight"] == pytest.approx(0.25)
    assert row["home_prior_weight"] == pytest.approx(0.75)
    assert row["home_off_ppa_blended"] == pytest.approx(0.3)


def test_opponent_future_results_do_not_change_adjustment() -> None:
    target_time = datetime(2024, 10, 1, 19, tzinfo=UTC)
    a_prior = _metric(1, 2024, target_time - timedelta(days=14), "A", "B", 0.4)
    b_prior = _metric(2, 2024, target_time - timedelta(days=13), "B", "D", -0.2)
    b_future = _metric(4, 2024, target_time + timedelta(days=2), "B", "D", 80.0)
    game = _game(3, target_time, "A", "C")
    first = build_feature_rows(
        [game],
        [a_prior, b_prior, b_future],
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    second = build_feature_rows(
        [game],
        [a_prior, b_prior, replace(b_future, metrics=_metrics(-80.0))],
        horizons=(PredictionHorizon.MINUTES_60,),
        morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
    )[0]
    assert first["home_off_ppa_opponent_adjusted"] == second["home_off_ppa_opponent_adjusted"]


def test_feature_registry_is_complete_versioned_and_hashed() -> None:
    definitions = feature_definitions()
    assert len(definitions) == len({item.name for item in definitions})
    assert all(item.point_in_time_rule and item.missingness and item.transformation_version for item in definitions)
    assert feature_definition("home_off_ppa_last3").minimum_sample == 1
    assert feature_set_hash(definitions) == feature_set_hash(tuple(reversed(definitions)))


def test_parquet_artifact_and_dataset_hash_are_deterministic(tmp_path: Path) -> None:
    store = ResearchArtifactStore(tmp_path)
    table = pa.table({"id": [2, 1], "value": ["b", "a"]})
    source = [{"id": "source-1", "content_hash": "a" * 64}]
    first = store.write_parquet(
        table,
        namespace="features",
        dataset="sample",
        season=2024,
        schema_version="v1",
        transformation_version="t1",
        source_manifests=source,
        sort_by=(("id", "ascending"),),
    )
    second = store.write_parquet(
        table,
        namespace="features",
        dataset="sample",
        season=2024,
        schema_version="v1",
        transformation_version="t1",
        source_manifests=source,
        sort_by=(("id", "ascending"),),
    )
    assert first == second
    assert store.validate_artifact(artifact_dict(first)) == []
    assert dataset_hash([artifact_dict(first)], {"version": 1}) == dataset_hash([artifact_dict(second)], {"version": 1})
    assert manifest_has_secret({"request": {"year": 2024}}) is False
    assert manifest_has_secret({"Authorization": "Bearer secret"}) is True


def test_feature_row_schema_and_order_are_deterministic() -> None:
    games = [
        _game(2, datetime(2024, 9, 8, 19, tzinfo=UTC), "C", "D"),
        _game(1, datetime(2024, 9, 7, 19, tzinfo=UTC), "A", "B"),
    ]
    rows = build_feature_rows(
        games, [], horizons=(PredictionHorizon.HOURS_24,), morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE
    )
    first = feature_table(rows)
    second = feature_table(list(reversed(rows))).sort_by([("season", "ascending"), ("kickoff", "ascending")])
    assert first.column_names == second.column_names
    assert first.to_pylist() == second.to_pylist()


def test_horizon_feature_tables_share_one_schema() -> None:
    game = _game(1, datetime(2024, 9, 7, 19, tzinfo=UTC), "A", "B")
    morning = feature_table(
        build_feature_rows(
            [game],
            [],
            horizons=(PredictionHorizon.GAME_DAY_MORNING,),
            morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
        )
    )
    hour = feature_table(
        build_feature_rows(
            [game],
            [],
            horizons=(PredictionHorizon.MINUTES_60,),
            morning_policy=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE,
        )
    )
    assert morning.schema == hour.schema
    assert pa.types.is_string(hour.schema.field("morning_policy").type)


def test_pbp_reconciliation_detects_common_season_universe_error() -> None:
    games = [_game(1, datetime(2024, 9, 1, tzinfo=UTC), "A", "B"), _game(2, datetime(2024, 9, 2, tzinfo=UTC), "A", "C")]
    plays = [{"provider_game_id": 1}] * 3 + [{"provider_game_id": 2}] * 2
    qa = {
        "start_season": 2024,
        "end_season": 2024,
        "seasons": [{"season": 2024, "row_count": 4, "games": [{"game_id": 1, "play_count": 4, "fbs_game": True}]}],
    }
    report = reconcile_pbp(plays, games, qa)
    assert report["common_season_difference"] == 1
    assert report["by_season"][0]["cfbd_only_games"] == 1
    assert "mixed universes" in report["cited_difference_problem"]


def test_pbp_reconciliation_attributes_qa_only_games_to_their_actual_season() -> None:
    games = [_game(1, datetime(2023, 9, 1, tzinfo=UTC), "A", "B")]
    plays = [{"provider_game_id": 1}]
    qa = {
        "start_season": 2023,
        "end_season": 2024,
        "seasons": [
            {"season": 2023, "row_count": 1, "games": [{"game_id": 1, "play_count": 1, "fbs_game": True}]},
            {
                "season": 2024,
                "row_count": 2,
                "games": [
                    {
                        "game_id": 99,
                        "play_count": 2,
                        "fbs_game": True,
                        "season_type": "postseason",
                    }
                ],
            },
        ],
    }
    report = reconcile_pbp(plays, games, qa)
    assert report["by_season"][0]["cfbfastR_only_games"] == 0
    assert report["by_season"][1]["cfbfastR_only_games"] == 1
    assert report["by_season"][1]["difference_by_cohort"] == {"fbs_vs_fbs": -2}
    assert report["by_season"][1]["difference_by_season_segment"] == {"postseason": -2}


def _game(game_id: int, kickoff: datetime, home: str, away: str) -> dict[str, Any]:
    return {
        "provider_game_id": game_id,
        "canonical_event_id": f"event-{game_id}",
        "season": kickoff.year,
        "week": 1,
        "kickoff": kickoff,
        "available_at": kickoff + timedelta(hours=24),
        "home_program_id": home,
        "away_program_id": away,
        "home_classification": "fbs",
        "away_classification": "fbs",
        "neutral_site": False,
        "postseason": False,
        "model_eligible": True,
        "target_margin": 7,
        "target_total": 55,
    }


def _play(
    game_id: int, offense: str, defense: str, play_type: str, ppa: float, yards: int, *, down: int, distance: int
) -> dict[str, Any]:
    return {
        "provider_game_id": game_id,
        "offense_program_id": offense,
        "defense_program_id": defense,
        "identity_resolved": True,
        "play_type": play_type,
        "ppa": ppa,
        "yards_gained": yards,
        "down": down,
        "distance": distance,
        "wallclock": "2024-08-31T19:00:00Z",
    }


def _metrics(value: float) -> dict[str, float]:
    return {
        "off_ppa": value,
        "def_ppa_allowed": -value,
        "pass_ppa": value,
        "rush_ppa": value,
        "success_rate": 0.5,
        "explosive_rate": 0.1,
        "yards_per_play": 6.0,
        "yards_per_drive": 30.0,
        "points_per_drive": 2.5,
        "plays_per_game": 70.0,
        "drives_per_game": 12.0,
        "havoc_rate": 0.1,
    }


def _metric(game_id: int, season: int, kickoff: datetime, team: str, opponent: str, value: float) -> TeamGameMetric:
    return TeamGameMetric(
        provider_game_id=game_id,
        season=season,
        week=1,
        kickoff=kickoff,
        available_at=kickoff + timedelta(hours=24),
        program_id=team,
        opponent_program_id=opponent,
        is_home=True,
        metrics=_metrics(value),
        play_rows=70,
        drive_rows=12,
        wallclock_coverage=1.0,
        team_stats_present=True,
    )
