from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from app.research.ncaaf.finalist_freeze import (
    build_freeze_manifest,
    validate_freeze_manifest,
    validate_local_artifacts,
    write_freeze_manifest,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build or validate the pre-2025 NCAAF finalist freeze")
    result.add_argument("command", choices=("build", "validate"))
    result.add_argument("--output", type=Path, default=Path("docs/reports/NCAAF_FINALIST_FREEZE_V1.json"))
    result.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    result.add_argument("--require-local-artifacts", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    manifest = write_freeze_manifest(arguments.output) if arguments.command == "build" else build_freeze_manifest()
    errors = validate_freeze_manifest(manifest)
    if arguments.require_local_artifacts:
        errors = validate_local_artifacts(arguments.artifact_root, manifest)
    print(
        json.dumps(
            {
                "valid": not errors,
                "errors": errors,
                "freeze_hash": manifest["freeze_hash"],
                "holdout_accessed": manifest["holdout_accessed"],
                "provider_calls": manifest["provider_calls"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
