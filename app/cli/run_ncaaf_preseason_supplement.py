from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.preseason_supplement import run_preseason_supplement


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded NCAAF preseason family/probability supplements")
    parser.add_argument("--manifest")
    parser.add_argument("--primary-dir", type=Path, default=Path(".ncaaf-data/models/preseason-v1"))
    parser.add_argument("--key-number-dir", type=Path, default=Path(".ncaaf-data/models/key-number-v1"))
    parser.add_argument("--probability-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/preseason-supplement-v1"))
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--end-season", type=int, default=2024)
    args = parser.parse_args()
    if args.network:
        parser.error("preseason supplemental modeling is offline")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible")
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("preseason-features", args.manifest)
    result = run_preseason_supplement(
        store, manifest, primary_root=args.primary_dir,
        key_number_root=args.key_number_dir, probability_root=args.probability_dir,
        output_root=args.output_dir,
    )
    print(json.dumps({"run_hash": result["run_hash"], "provider_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
