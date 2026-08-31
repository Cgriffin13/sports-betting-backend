from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.research.ncaaf.market_aware_modeling import (
    artifact_integrity,
    build_market_aware_tournament,
    validate_market_aware_tournament,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run or validate the offline NCAAF market-aware tournament")
    result.add_argument("command", choices=("run", "validate", "inspect"))
    result.add_argument("--root", type=Path, default=Path(".ncaaf-data"))
    result.add_argument("--namespace", default="market-aware-v1")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "run":
        manifest = build_market_aware_tournament(arguments.root, output_namespace=arguments.namespace)
    else:
        from app.research.ncaaf.artifacts import ResearchArtifactStore

        manifest = ResearchArtifactStore(arguments.root).load_manifest(arguments.namespace)
    if arguments.command == "validate":
        errors = validate_market_aware_tournament(arguments.root, manifest)
        print(json.dumps({"valid": not errors, "errors": errors}, indent=2, sort_keys=True))
        return int(bool(errors))
    if arguments.command == "inspect":
        print(json.dumps(artifact_integrity(arguments.root, manifest), indent=2, sort_keys=True))
        return 0
    print(
        json.dumps(
            {
                "manifest_id": manifest["manifest_id"],
                "dataset_hash": manifest["dataset_hash"],
                "point_rows": manifest["point_rows"],
                "probability_rows": manifest["probability_rows"],
                "runtime_seconds": json.loads(
                    (arguments.root / arguments.namespace / "runtime.json").read_text(encoding="utf-8")
                )["runtime_seconds"],
                "provider_calls": manifest["provider_calls"],
                "holdout_accessed": manifest["holdout_accessed"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
