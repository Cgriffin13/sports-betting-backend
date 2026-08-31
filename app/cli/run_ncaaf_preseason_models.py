from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psutil

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import PredictionHorizon
from app.research.ncaaf.preseason_modeling import run_preseason_experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the targeted offline NCAAF preseason/personnel experiment")
    parser.add_argument("--manifest")
    parser.add_argument("--baseline-predictions", type=Path, default=Path(".ncaaf-data/models/baseline-v1/oof_predictions.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/preseason-v1"))
    parser.add_argument("--horizon", action="append", choices=[item.value for item in PredictionHorizon])
    parser.add_argument("--skip-catboost", action="store_true")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--end-season", type=int, default=2024)
    args = parser.parse_args()
    if args.network:
        parser.error("preseason modeling is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible")
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("preseason-features", args.manifest)
    if args.plan:
        print(
            json.dumps(
                {
                    "manifest_id": manifest["manifest_id"],
                    "horizons": args.horizon or sorted(manifest["feature_coverage"]),
                    "models": ["power_preseason_prior", "ridge_preseason", *([] if args.skip_catboost else ["catboost_total_preseason"])],
                    "network_calls": 0,
                    "holdout_access": False,
                    "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    process = psutil.Process()
    result = run_preseason_experiment(
        store,
        manifest,
        baseline_predictions_path=args.baseline_predictions,
        output_root=args.output_dir,
        selected_horizons=tuple(args.horizon or ()),
        include_catboost=not args.skip_catboost,
    )
    runtime = {
        "elapsed_seconds": result["elapsed_seconds"],
        "rss_bytes": process.memory_info().rss,
        "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
        "provider_calls": 0,
    }
    (args.output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_hash": result["run_hash"],
                "prediction_rows": result["prediction_rows"],
                "elapsed_seconds": result["elapsed_seconds"],
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
