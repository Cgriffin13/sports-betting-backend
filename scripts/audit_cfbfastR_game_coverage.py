"""Compare public cfbfastR play-by-play game IDs with the unified schedule universe.

This research-only script temporarily downloads one schedule and PBP Parquet file per
season, emits aggregate coverage JSON, and deletes each file. It never prints scores.
See ``audit_sportsdataverse_parquet.py`` for temporary PyArrow installation guidance.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from collections import Counter
from typing import Any

from audit_sportsdataverse_parquet import USER_AGENT, _release_assets


def _download_table(url: str, columns: list[str]) -> dict[str, list[Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - research environment guard
        raise SystemExit("PyArrow is required only for this research script; see its module docstring.") from exc

    path: str | None = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            tempfile.NamedTemporaryFile(prefix="ncaaf-game-coverage-", suffix=".parquet", delete=False) as destination,
        ):
            path = destination.name
            shutil.copyfileobj(response, destination)
        return pq.read_table(path, columns=columns).to_pydict()
    finally:
        if path is not None:
            os.unlink(path)


def _assets_by_name(tag: str) -> dict[str, dict[str, Any]]:
    return {asset["name"]: asset for asset in _release_assets(tag)}


def audit(start_year: int, end_year: int) -> dict[str, Any]:
    schedule_assets = _assets_by_name("cfb_schedules")
    pbp_assets = _assets_by_name("espn_cfb_pbp")
    seasons: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        schedule_asset = schedule_assets[f"cfb_schedules_{year}.parquet"]
        pbp_asset = pbp_assets[f"play_by_play_{year}.parquet"]
        schedule = _download_table(
            schedule_asset["browser_download_url"],
            [
                "game_id",
                "season_type",
                "status",
                "home_points",
                "away_points",
                "fbs_game",
                "fbs_participant",
                "home_id",
                "away_id",
                "home_team",
                "away_team",
            ],
        )
        pbp = _download_table(pbp_asset["browser_download_url"], ["game_id"])
        eligible: dict[int, int] = {}
        team_names: dict[int, str] = {}
        for index, game_id in enumerate(schedule["game_id"]):
            season_type = schedule["season_type"][index]
            status = schedule["status"][index]
            has_score = schedule["home_points"][index] is not None and schedule["away_points"][index] is not None
            is_played_scope = season_type in {"regular", "postseason", "spring_regular", "spring_postseason"}
            is_not_unplayed = status not in {"STATUS_CANCELED", "STATUS_POSTPONED"}
            if schedule["fbs_participant"][index] and has_score and is_played_scope and is_not_unplayed:
                eligible[int(game_id)] = index
                team_names[int(schedule["home_id"][index])] = str(schedule["home_team"][index])
                team_names[int(schedule["away_id"][index])] = str(schedule["away_team"][index])

        pbp_games = {int(game_id) for game_id in pbp["game_id"] if game_id is not None}
        missing = set(eligible) - pbp_games
        missing_by_team: Counter[int] = Counter()
        for game_id in missing:
            index = eligible[game_id]
            missing_by_team[int(schedule["home_id"][index])] += 1
            missing_by_team[int(schedule["away_id"][index])] += 1
        fbs_game_ids = {game_id for game_id, index in eligible.items() if schedule["fbs_game"][index]}
        seasons.append(
            {
                "season": year,
                "eligible_fbs_participant_games": len(eligible),
                "eligible_fbs_vs_fbs_games": len(fbs_game_ids),
                "pbp_games": len(pbp_games),
                "eligible_with_pbp": len(set(eligible) & pbp_games),
                "eligible_missing_pbp": len(missing),
                "eligible_coverage_fraction": round(len(set(eligible) & pbp_games) / len(eligible), 6),
                "fbs_vs_fbs_missing_pbp": len(fbs_game_ids - pbp_games),
                "teams_with_missing_games": [
                    {"team_id": team_id, "team": team_names.get(team_id), "missing_games": count}
                    for team_id, count in missing_by_team.most_common()
                ],
            }
        )
    eligible = sum(season["eligible_fbs_participant_games"] for season in seasons)
    with_pbp = sum(season["eligible_with_pbp"] for season in seasons)
    fbs_games = sum(season["eligible_fbs_vs_fbs_games"] for season in seasons)
    fbs_missing = sum(season["fbs_vs_fbs_missing_pbp"] for season in seasons)
    return {
        "summary": {
            "eligible_fbs_participant_games": eligible,
            "eligible_with_pbp": with_pbp,
            "eligible_missing_pbp": eligible - with_pbp,
            "eligible_coverage_fraction": round(with_pbp / eligible, 6),
            "eligible_fbs_vs_fbs_games": fbs_games,
            "fbs_vs_fbs_with_pbp": fbs_games - fbs_missing,
            "fbs_vs_fbs_missing_pbp": fbs_missing,
            "fbs_vs_fbs_coverage_fraction": round((fbs_games - fbs_missing) / fbs_games, 6),
        },
        "seasons": seasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    args = parser.parse_args()
    if args.start_year > args.end_year:
        parser.error("--start-year must be at or before --end-year")
    json.dump(audit(args.start_year, args.end_year), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
