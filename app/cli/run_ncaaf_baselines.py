from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psutil

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import PredictionHorizon
from app.research.ncaaf.modeling import run_tournament


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline, chronological NCAAF baseline tournament")
    parser.add_argument("--feature-manifest")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--horizon", action="append", choices=[item.value for item in PredictionHorizon])
    parser.add_argument("--target", action="append", choices=["target_margin", "target_total"])
    parser.add_argument("--family", action="append", choices=["naive", "elo", "ridge"])
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("baseline modeling is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible to this command")
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("features", args.feature_manifest)
    if args.plan:
        print(json.dumps({"dataset_hash": manifest["dataset_hash"], "end_season": args.end_season, "horizons": args.horizon or "all", "targets": args.target or "all", "families": args.family or "all", "network_calls": 0, "writes": False}, sort_keys=True))
        return
    process = psutil.Process()
    before = process.memory_info().rss
    result = run_tournament(
        store,
        manifest,
        output_root=args.output_dir,
        bounded_end_season=args.end_season,
        selected_horizons=tuple(args.horizon or ()),
        selected_targets=tuple(args.target or ()),
        selected_families=tuple(args.family or ()),
    )
    result["rss_before_bytes"] = before
    result["rss_after_bytes"] = process.memory_info().rss
    result["peak_rss_bytes"] = getattr(process.memory_info(), "peak_wset", process.memory_info().rss)
    # Re-write with operational metrics that do not affect deterministic run_hash.
    (args.output_dir / "runtime.json").write_text(
        json.dumps({key: result[key] for key in ("elapsed_seconds", "rss_before_bytes", "rss_after_bytes", "peak_rss_bytes", "provider_calls")}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_hash": result["run_hash"], "prediction_rows": result["predictions_rows"], "provider_calls": 0, "output": str(args.output_dir)}, sort_keys=True))


if __name__ == "__main__":
    main()
