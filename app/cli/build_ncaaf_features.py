from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import psutil

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import MorningPolicy, PredictionHorizon, validate_feature_seasons
from app.research.ncaaf.features import PointInTimeFeatureBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Build leakage-safe NCAAF point-in-time feature rows offline")
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--normalized-manifest")
    parser.add_argument("--horizon", action="append", choices=[item.value for item in PredictionHorizon])
    parser.add_argument(
        "--morning-policy",
        choices=[item.value for item in MorningPolicy],
        default=MorningPolicy.FIRST_KICKOFF_MINUS_3H_CANDIDATE.value,
    )
    parser.add_argument("--allow-holdout-access", action="store_true")
    parser.add_argument("--network", action="store_true", help="Rejected: feature builds are offline.")
    parser.add_argument("--run-report", type=Path, help="Optional non-secret runtime/memory report path.")
    parser.add_argument("--plan", action="store_true", help="Print configuration without building artifacts.")
    args = parser.parse_args()
    if args.network:
        parser.error("feature builds never use network access")
    validate_feature_seasons(args.start_season, args.end_season, allow_holdout=args.allow_holdout_access)
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    normalized = store.load_manifest("normalized", args.normalized_manifest)
    horizons = tuple(PredictionHorizon(value) for value in (args.horizon or [item.value for item in PredictionHorizon]))
    if args.plan:
        print(
            json.dumps(
                {
                    "season_range": [args.start_season, args.end_season],
                    "normalized_manifest_id": normalized["manifest_id"],
                    "horizons": sorted(str(item) for item in horizons),
                    "morning_policy": args.morning_policy,
                    "network_calls": 0,
                    "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    process = psutil.Process()
    before = process.memory_info().rss
    started = time.perf_counter()
    manifest = PointInTimeFeatureBuilder(store, normalized).build(
        args.start_season, args.end_season, horizons=horizons, morning_policy=MorningPolicy(args.morning_policy)
    )
    elapsed = time.perf_counter() - started
    memory = process.memory_info()
    result = {
        "manifest_id": manifest["manifest_id"],
        "dataset_hash": manifest["dataset_hash"],
        "feature_set_hash": manifest["feature_set_hash"],
        "rows": manifest["row_count"],
        "eligible_games": manifest["eligible_game_count"],
        "elapsed_seconds": round(elapsed, 3),
        "rss_before_bytes": before,
        "rss_after_bytes": memory.rss,
        "peak_rss_bytes": getattr(memory, "peak_wset", memory.rss),
        "network_calls": 0,
    }
    if args.run_report:
        args.run_report.parent.mkdir(parents=True, exist_ok=True)
        args.run_report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
