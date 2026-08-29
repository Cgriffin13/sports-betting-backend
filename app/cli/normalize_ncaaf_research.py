from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.cli.ncaaf_common import research_index_runtime
from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.contracts import validate_feature_seasons
from app.research.ncaaf.normalize import NormalizedCorpusBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize cached Phase 5B-1 NCAAF artifacts into immutable Parquet")
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--allow-holdout-access", action="store_true")
    parser.add_argument("--network", action="store_true", help="Rejected: this command is deliberately offline.")
    parser.add_argument("--plan", action="store_true", help="Print the bounded offline plan without writing artifacts.")
    args = parser.parse_args()
    if args.network:
        parser.error("normalization never uses network access; ingest source artifacts separately")
    validate_feature_seasons(args.start_season, args.end_season, allow_holdout=args.allow_holdout_access)
    if args.plan:
        seasons = args.end_season - args.start_season + 1
        print(
            json.dumps(
                {
                    "season_range": [args.start_season, args.end_season],
                    "expected_partitions": seasons * 5 + 1,
                    "network_calls": 0,
                    "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    factory, source_store = research_index_runtime()
    output_root = Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data"))
    with factory() as session:
        manifest = NormalizedCorpusBuilder(session, source_store, ResearchArtifactStore(output_root)).build(
            args.start_season, args.end_season
        )
    print(
        json.dumps(
            {
                "manifest_id": manifest["manifest_id"],
                "dataset_hash": manifest["dataset_hash"],
                "artifacts": len(manifest["artifacts"]),
                "network_calls": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
