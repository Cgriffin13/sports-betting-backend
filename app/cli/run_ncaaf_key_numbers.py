from __future__ import annotations

import argparse
import json
from pathlib import Path

import psutil

from app.research.ncaaf.key_numbers import run_key_number_tournament


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline empirical-discrete NCAAF margin evaluation")
    parser.add_argument("--baseline-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/key-number-v1"))
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("key-number research is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible to this command")
    if args.plan:
        print(json.dumps({"end_season": args.end_season, "network_calls": 0, "writes": False}, sort_keys=True))
        return
    process = psutil.Process()
    result = run_key_number_tournament(args.baseline_dir, args.output_dir, end_season=args.end_season)
    runtime = {
        "elapsed_seconds": result["elapsed_seconds"], "rss_after_bytes": process.memory_info().rss,
        "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
        "provider_calls": 0,
    }
    (args.output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"run_hash": result["run_hash"], "rows": result["probability_rows"], "provider_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
