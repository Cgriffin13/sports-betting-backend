from __future__ import annotations

import argparse
import json

from sqlalchemy import desc, select

from app.cli.ncaaf_common import research_index_runtime
from app.db.ncaaf_models import SourceManifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect credential-free CFBD source manifests")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    factory, _ = research_index_runtime()
    with factory() as session:
        manifests = session.scalars(select(SourceManifest).order_by(desc(SourceManifest.retrieved_at)).limit(args.limit)).all()
    print(
        json.dumps(
            [
                {
                    "id": str(item.id),
                    "endpoint": item.endpoint,
                    "parameters": item.request_parameters,
                    "request_hash": item.request_hash,
                    "retrieved_at": item.retrieved_at.isoformat(),
                    "content_hash": item.content_hash,
                    "row_count": item.row_count,
                    "response_bytes": item.response_bytes,
                    "availability_mode": item.availability_mode,
                    "supersedes_manifest_id": str(item.supersedes_manifest_id) if item.supersedes_manifest_id else None,
                    "artifact_uri": item.artifact_uri,
                }
                for item in manifests
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
