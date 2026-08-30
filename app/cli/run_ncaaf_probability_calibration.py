from __future__ import annotations

import argparse
import json
from pathlib import Path

import psutil

from app.research.ncaaf.calibration import run_probability_tournament


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline NCAAF probability-distribution tournament")
    parser.add_argument("--input-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--family", action="append")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("probability calibration is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible to this command")
    if args.plan:
        print(
            json.dumps(
                {
                    "end_season": args.end_season,
                    "families": args.family or "all predeclared",
                    "network_calls": 0,
                    "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    process = psutil.Process()
    before = process.memory_info().rss
    result = run_probability_tournament(
        args.input_dir,
        args.output_dir,
        end_season=args.end_season,
        selected_families=tuple(args.family or ()),
    )
    runtime = {
        "elapsed_seconds": result["elapsed_seconds"],
        "rss_before_bytes": before,
        "rss_after_bytes": process.memory_info().rss,
        "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
        "provider_calls": 0,
    }
    (args.output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_hash": result["run_hash"],
                "probability_rows": result["probability_rows"],
                "provider_calls": 0,
                "output": str(args.output_dir),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
