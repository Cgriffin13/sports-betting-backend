from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psutil

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import PredictionHorizon
from app.research.ncaaf.strong_models import CONFIGURATIONS, FAMILIES, run_strong_model_tournament


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline chronological NCAAF strong-model tournament")
    parser.add_argument("--feature-manifest")
    parser.add_argument("--baseline-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/strong-v1"))
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--family", action="append", choices=FAMILIES)
    parser.add_argument("--target", action="append", choices=["target_margin", "target_total"])
    parser.add_argument("--horizon", action="append", choices=[item.value for item in PredictionHorizon])
    parser.add_argument("--configuration-limit", type=int, choices=range(1, len(CONFIGURATIONS) + 1))
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("strong-model research is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible to this command")
    configurations = CONFIGURATIONS[: args.configuration_limit] if args.configuration_limit else CONFIGURATIONS
    if args.plan:
        print(
            json.dumps(
                {
                    "end_season": args.end_season, "families": args.family or list(FAMILIES),
                    "targets": args.target or "all", "horizons": args.horizon or "all",
                    "configurations_per_family": len(configurations), "network_calls": 0, "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("features", args.feature_manifest)
    process = psutil.Process()
    result = run_strong_model_tournament(
        store, manifest, baseline_root=args.baseline_dir, output_root=args.output_dir,
        end_season=args.end_season, selected_families=tuple(args.family or ()),
        selected_targets=tuple(args.target or ()), selected_horizons=tuple(args.horizon or ()),
        configurations=configurations,
    )
    runtime = {
        "elapsed_seconds": result["elapsed_seconds"], "rss_after_bytes": process.memory_info().rss,
        "peak_rss_bytes": getattr(process.memory_info(), "peak_wset", process.memory_info().rss),
        "provider_calls": 0,
    }
    (args.output_dir / "runtime.json").write_text(
        json.dumps(runtime, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # Runtime/peak memory is operational metadata and is deliberately excluded
    # from the deterministic run hash, but belongs in the run manifest.
    result["runtime_measurement"] = runtime
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"run_hash": result["run_hash"], "prediction_rows": result["prediction_rows"],
             "fit_budget": result["fit_budget"], "provider_calls": 0, "output": str(args.output_dir)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
