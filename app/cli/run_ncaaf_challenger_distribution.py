from __future__ import annotations

import argparse
import json
from pathlib import Path

import psutil

from app.research.ncaaf.challenger_distribution import run_challenger_distribution


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the limited surviving NCAAF challenger distribution comparison")
    parser.add_argument("--strong-dir", type=Path, default=Path(".ncaaf-data/models/strong-v1"))
    parser.add_argument("--probability-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/strong-distribution-v1"))
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("challenger distribution research is offline")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible")
    process = psutil.Process()
    result = run_challenger_distribution(
        args.strong_dir, args.probability_dir, args.output_dir, end_season=args.end_season
    )
    runtime = {
        "elapsed_seconds": result["elapsed_seconds"],
        "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
        "provider_calls": 0,
    }
    (args.output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"run_hash": result["run_hash"], "rows": result["probability_rows"], "provider_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
