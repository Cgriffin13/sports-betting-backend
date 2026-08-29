from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

PBP_RECONCILIATION_VERSION = "cfbd-cfbfastr-pbp-reconciliation-v1"


def reconcile_pbp(
    cfbd_plays: Sequence[Mapping[str, Any]],
    cfbd_games: Sequence[Mapping[str, Any]],
    qa_report: Mapping[str, Any],
) -> dict[str, Any]:
    cfbd_counts = Counter(int(row["provider_game_id"]) for row in cfbd_plays)
    games = {int(row["provider_game_id"]): row for row in cfbd_games}
    qa_counts: dict[int, int] = {}
    qa_meta: dict[int, Mapping[str, Any]] = {}
    qa_season_rows: dict[int, int] = {}
    for season in qa_report["seasons"]:
        year = int(season["season"])
        qa_season_rows[year] = int(season["row_count"])
        for game in season["games"]:
            game_id = int(game["game_id"])
            qa_counts[game_id] = int(game["play_count"])
            qa_meta[game_id] = {**game, "season": year}
    years = range(int(qa_report["start_season"]), int(qa_report["end_season"]) + 1)
    by_season: list[dict[str, Any]] = []
    game_differences: list[dict[str, Any]] = []
    for year in years:
        cfbd_year_ids = {
            game_id for game_id, game in games.items() if int(game["season"]) == year and game_id in cfbd_counts
        }
        qa_year_ids = {game_id for game_id, game in qa_meta.items() if int(game["season"]) == year}
        matched = cfbd_year_ids & qa_year_ids
        only_cfbd = cfbd_year_ids - qa_year_ids
        only_qa = qa_year_ids - cfbd_year_ids
        cfbd_rows = sum(cfbd_counts[game_id] for game_id in cfbd_year_ids)
        within_delta = sum(cfbd_counts[game_id] - qa_counts[game_id] for game_id in matched)
        classifications: Counter[str] = Counter()
        postseason: Counter[str] = Counter()
        for game_id in cfbd_year_ids | qa_year_ids:
            game = games.get(game_id, {})
            qa_game = qa_meta.get(game_id, {})
            if game:
                home = game.get("home_classification")
                away = game.get("away_classification")
                cohort = "fbs_vs_fbs" if home == away == "fbs" else "fbs_vs_fcs_or_other"
                bucket = "postseason" if bool(game.get("postseason")) else "regular"
            else:
                cohort = "fbs_vs_fbs" if bool(qa_game.get("fbs_game")) else "fbs_vs_fcs_or_other"
                bucket = "postseason" if str(qa_game.get("season_type", "")).lower() != "regular" else "regular"
            classifications[cohort] += cfbd_counts.get(game_id, 0) - qa_counts.get(game_id, 0)
            postseason[bucket] += cfbd_counts.get(game_id, 0) - qa_counts.get(game_id, 0)
            if game_id in matched and cfbd_counts[game_id] != qa_counts[game_id]:
                game_differences.append(
                    {
                        "season": year,
                        "game_id": game_id,
                        "cohort": cohort,
                        "season_segment": bucket,
                        "cfbd_plays": cfbd_counts[game_id],
                        "cfbfastR_plays": qa_counts[game_id],
                        "difference": cfbd_counts[game_id] - qa_counts[game_id],
                    }
                )
        by_season.append(
            {
                "season": year,
                "cfbd_rows": cfbd_rows,
                "cfbfastR_rows": qa_season_rows.get(year, 0),
                "difference": cfbd_rows - qa_season_rows.get(year, 0),
                "matched_games": len(matched),
                "cfbd_only_games": len(only_cfbd),
                "cfbfastR_only_games": len(only_qa),
                "within_matched_game_difference": within_delta,
                "difference_by_cohort": dict(sorted(classifications.items())),
                "difference_by_season_segment": dict(sorted(postseason.items())),
            }
        )
    game_differences.sort(key=lambda row: (-abs(int(row["difference"])), int(row["season"]), int(row["game_id"])))
    common_cfbd = sum(row["cfbd_rows"] for row in by_season)
    common_qa = sum(row["cfbfastR_rows"] for row in by_season)
    return {
        "report_version": PBP_RECONCILIATION_VERSION,
        "common_season_range": [min(years), max(years)],
        "cited_aggregate_difference": -123444,
        "cited_difference_problem": "The prior comparison used CFBD 2014-2024 against cfbfastR 2014-2025 and therefore mixed universes.",
        "common_season_cfbd_rows": common_cfbd,
        "common_season_cfbfastR_rows": common_qa,
        "common_season_difference": common_cfbd - common_qa,
        "by_season": by_season,
        "largest_matched_game_differences": game_differences[:100],
        "matched_games_with_different_counts": len(game_differences),
        "assessment": "feature-specific concern, not blocking for the baseline dataset",
        "bias_conclusion": "Use CFBD as authoritative input, retain per-season/game PBP coverage flags, and segment 2021-2022. Row equality is not expected because source play taxonomy and FBS filters differ.",
    }
