from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pyarrow.compute as pc

from app.research.ncaaf.artifacts import ResearchArtifactStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one normalized NCAAF preseason team-season row")
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--manifest")
    args = parser.parse_args()
    if args.season >= 2025:
        parser.error("the locked 2025 holdout is not accessible")
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("preseason-features", args.manifest)
    artifact = next(
        item
        for item in manifest["artifacts"]
        if item["dataset"] == "team_season_preseason_facts" and int(item["season"]) == args.season
    )
    table = store.read_table(artifact["uri"])
    selected = table.filter(pc.equal(table["program_id"], args.program_id)).to_pylist()
    print(json.dumps(selected[0] if selected else {"found": False}, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
