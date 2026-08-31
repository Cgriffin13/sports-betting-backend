from __future__ import annotations

import argparse
import json
import os
from datetime import UTC
from pathlib import Path
from typing import Any, Sequence

import pyarrow as pa
from sqlalchemy import select

from app.cli.ncaaf_common import research_index_runtime
from app.db.ncaaf_models import SourceManifest
from app.research.ncaaf.artifacts import ResearchArtifactStore
from app.research.ncaaf.modeling import load_feature_tables
from app.research.ncaaf.preseason import SOURCE_ENDPOINTS, SourcePart, build_preseason_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic NCAAF preseason/personnel facts and features")
    parser.add_argument("--start-season", type=int, default=2014)
    parser.add_argument("--end-season", type=int, default=2024)
    parser.add_argument("--feature-manifest")
    parser.add_argument("--normalized-manifest")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("preseason feature construction is offline and never accepts network access")
    if args.end_season >= 2025:
        parser.error("the locked 2025 holdout is not accessible to this command")
    factory, raw_store = research_index_runtime()
    store = ResearchArtifactStore(Path(os.getenv("NCAAF_RESEARCH_ARTIFACT_DIR", ".ncaaf-data")))
    feature_manifest = store.load_manifest("features", args.feature_manifest)
    normalized_manifest = store.load_manifest("normalized", args.normalized_manifest)
    with factory() as session:
        manifests = _latest_source_manifests(session.scalars(select(SourceManifest)).all())
        parts = [
            SourcePart(
                manifest_id=str(item.id),
                endpoint=item.endpoint,
                parameters=dict(item.request_parameters),
                content_hash=item.content_hash,
                retrieved_at=(
                    item.retrieved_at.replace(tzinfo=UTC)
                    if item.retrieved_at.tzinfo is None
                    else item.retrieved_at.astimezone(UTC)
                ),
                response_bytes=item.response_bytes,
                records=_records(raw_store.get(item.artifact_uri)),
            )
            for item in manifests
        ]
    if args.plan:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "source_manifests": len(parts),
                    "source_rows": sum(len(part.records) for part in parts),
                    "start_season": args.start_season,
                    "end_season": args.end_season,
                    "base_dataset_hash": feature_manifest["dataset_hash"],
                    "network_calls": 0,
                    "writes": False,
                },
                sort_keys=True,
            )
        )
        return
    games = _normalized_games(store, normalized_manifest, args.start_season, args.end_season)
    result = build_preseason_artifacts(
        store,
        parts=parts,
        normalized_games=games,
        base_tables=load_feature_tables(store, feature_manifest),
        base_manifest=feature_manifest,
        start_season=args.start_season,
        end_season=args.end_season,
    )
    print(
        json.dumps(
            {
                "manifest_id": result["manifest_id"],
                "dataset_hash": result["dataset_hash"],
                "preseason_feature_set_hash": result["preseason_feature_set_hash"],
                "team_season_rows": result["source_report"]["team_season_rows"],
                "provider_calls": 0,
            },
            sort_keys=True,
        )
    )


def _latest_source_manifests(manifests: Sequence[SourceManifest]) -> list[SourceManifest]:
    latest: dict[str, SourceManifest] = {}
    for item in manifests:
        if item.endpoint not in SOURCE_ENDPOINTS:
            continue
        prior = latest.get(item.request_hash)
        if prior is None or (item.retrieved_at, str(item.id)) > (prior.retrieved_at, str(prior.id)):
            latest[item.request_hash] = item
    return sorted(latest.values(), key=lambda item: (item.endpoint, item.request_hash))


def _records(payload: bytes) -> list[dict[str, Any]]:
    value = json.loads(payload)
    if not isinstance(value, list):
        raise ValueError("preseason source payload must be a list")
    return [dict(item) for item in value]


def _normalized_games(
    store: ResearchArtifactStore,
    manifest: dict[str, Any],
    start_season: int,
    end_season: int,
) -> pa.Table:
    tables = [
        store.read_table(item["uri"])
        for item in manifest["artifacts"]
        if item["dataset"] == "games" and start_season <= int(item["season"]) <= end_season
    ]
    if not tables:
        raise ValueError("normalized game artifacts are unavailable")
    return pa.concat_tables(tables)


if __name__ == "__main__":
    main()
