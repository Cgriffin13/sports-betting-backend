from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.reporting import feature_dataset_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a non-predictive NCAAF feature-corpus QA report")
    parser.add_argument("--normalized-manifest")
    parser.add_argument("--feature-manifest")
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    normalized = store.load_manifest("normalized", args.normalized_manifest)
    features = store.load_manifest("features", args.feature_manifest)
    run_report = json.loads(args.run_report.read_text(encoding="utf-8")) if args.run_report else None
    report = feature_dataset_report(store, normalized, features, run_report=run_report)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": report["target_rows"],
                "dataset_hash": report["dataset_hash"],
                "feature_set_hash": report["feature_set_hash"],
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
