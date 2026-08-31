from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Sequence

from app.research.ncaaf.holdout import create_unlock_record, load_unlock_record


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Operate the one-time Phase 5B-9 NCAAF holdout boundary")
    result.add_argument("command", choices=("unlock", "verify-unlock"))
    result.add_argument("--artifact-root", type=Path, default=Path(".ncaaf-data"))
    result.add_argument("--freeze", type=Path, default=Path("docs/reports/NCAAF_FINALIST_FREEZE_V1.json"))
    result.add_argument("--command-id", default="phase-5b-9-locked-holdout")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if arguments.command == "unlock":
        freeze = json.loads(arguments.freeze.read_text(encoding="utf-8"))
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        record = create_unlock_record(
            arguments.artifact_root,
            freeze,
            code_commit=commit,
            command_id=arguments.command_id,
        )
    else:
        record = load_unlock_record(arguments.artifact_root)
    print(
        json.dumps(
            {
                "unlock_id": record["unlock_id"],
                "unlocked_at": record["unlocked_at"],
                "holdout_season": record["holdout_season"],
                "code_commit": record["code_commit"],
                "freeze_hash": record["freeze_hash"],
                "freeze_verified_before_unlock": record["freeze_verified_before_unlock"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
