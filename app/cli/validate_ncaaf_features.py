from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import LOCKED_HOLDOUT_SEASON


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate immutable NCAAF normalized/feature artifacts and holdout boundaries"
    )
    parser.add_argument("--namespace", choices=("normalized", "features"), default="features")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest(args.namespace, args.manifest)
    errors = [error for artifact in manifest["artifacts"] for error in store.validate_artifact(artifact)]
    if int(manifest.get("end_season", 0)) >= LOCKED_HOLDOUT_SEASON:
        errors.append("ordinary development manifest reaches the locked 2025 holdout")
    row_counts = Counter(item["dataset"] for item in manifest["artifacts"] for _ in range(int(item["row_count"])))
    result = {
        "manifest_id": manifest["manifest_id"],
        "errors": errors,
        "valid": not errors,
        "rows_by_dataset": dict(row_counts),
        "network_calls": 0,
    }
    print(json.dumps(result, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
