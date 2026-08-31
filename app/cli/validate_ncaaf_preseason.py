from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.preseason import validate_preseason_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NCAAF preseason/personnel artifacts")
    parser.add_argument("--manifest")
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("preseason validation is offline")
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("preseason-features", args.manifest)
    errors = validate_preseason_manifest(store, manifest)
    print(json.dumps({"valid": not errors, "errors": errors, "manifest_id": manifest["manifest_id"]}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
