from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

import pyarrow.compute as pc
import pyarrow as pa

from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.feature_registry import feature_definition


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a registered feature or one point-in-time game row")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--feature")
    group.add_argument("--game-id", type=int)
    parser.add_argument("--horizon")
    parser.add_argument("--manifest")
    args = parser.parse_args()
    if args.feature:
        print(json.dumps(asdict(feature_definition(args.feature)), indent=2, sort_keys=True, default=str))
        return
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    manifest = store.load_manifest("features", args.manifest)
    artifacts = [item for item in manifest["artifacts"] if item["dataset"] == "model_ready_games"]
    table = pa.concat_tables([store.read_table(item["uri"]) for item in artifacts])
    filtered = table.filter(pc.equal(table["provider_game_id"], args.game_id))
    if args.horizon:
        filtered = filtered.filter(pc.equal(filtered["prediction_horizon"], args.horizon))
    print(json.dumps(filtered.to_pylist(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
