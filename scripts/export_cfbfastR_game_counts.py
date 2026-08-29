"""Explicitly download public cfbfastR QA Parquet and export only per-game play counts.

This is a bounded QA utility, not a durable facts source. It never uses CFBD, never
prints scores, deletes downloaded Parquet files, and refuses network access without
``--execute``. The compact derived count file can be reused offline by Phase 5B-2.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from audit_cfbfastR_game_coverage import _assets_by_name, _download_table


def export_counts(start_year: int, end_year: int) -> dict[str, Any]:
    schedule_assets = _assets_by_name("cfb_schedules")
    pbp_assets = _assets_by_name("espn_cfb_pbp")
    seasons: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        schedule = _download_table(
            schedule_assets[f"cfb_schedules_{year}.parquet"]["browser_download_url"],
            ["game_id", "season_type", "fbs_game", "fbs_participant", "status", "home_points", "away_points"],
        )
        pbp = _download_table(pbp_assets[f"play_by_play_{year}.parquet"]["browser_download_url"], ["game_id"])
        schedule_lookup = {
            int(game_id): {
                "season_type": schedule["season_type"][index],
                "fbs_game": bool(schedule["fbs_game"][index]),
                "fbs_participant": bool(schedule["fbs_participant"][index]),
                "played": schedule["home_points"][index] is not None and schedule["away_points"][index] is not None,
                "status": schedule["status"][index],
            }
            for index, game_id in enumerate(schedule["game_id"])
            if game_id is not None
        }
        counts = Counter(int(game_id) for game_id in pbp["game_id"] if game_id is not None)
        seasons.append(
            {
                "season": year,
                "asset_sha256": pbp_assets[f"play_by_play_{year}.parquet"].get("digest"),
                "asset_updated_at": pbp_assets[f"play_by_play_{year}.parquet"].get("updated_at"),
                "row_count": sum(counts.values()),
                "games": [
                    {
                        "game_id": game_id,
                        "play_count": count,
                        **schedule_lookup.get(game_id, {"schedule_missing": True}),
                    }
                    for game_id, count in sorted(counts.items())
                ],
            }
        )
    return {
        "source": "SportsDataverse/cfbfastR QA",
        "start_season": start_year,
        "end_season": end_year,
        "seasons": seasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2014)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Authorize the bounded public QA downloads.")
    args = parser.parse_args()
    if not args.execute:
        print("plan: 2 public QA Parquet downloads per season; zero CFBD calls; rerun with --execute")
        return 0
    payload = export_counts(args.start_year, args.end_year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "seasons": len(payload["seasons"]), "cfbd_calls": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    raise SystemExit(main())
