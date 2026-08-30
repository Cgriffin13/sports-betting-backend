from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize the offline NCAAF probability tournament")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    args = parser.parse_args()
    manifest = json.loads((args.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    candidates = manifest["summary"]["candidates"]
    selected = {}
    for name in (
        "24_hours_before_kickoff|margin|elo|ncaaf-margin-power-v1|quality-grouped-scale-v1",
        "24_hours_before_kickoff|total|ridge|full_without_opponent_adjustment|empirical-kernel-v1",
    ):
        selected[name] = candidates[name]["overall"]
    print(
        json.dumps(
            {
                "run_hash": manifest["run_hash"],
                "provider_calls": manifest["provider_calls"],
                "holdout_accessed": manifest["holdout_accessed"],
                "selected_24h": selected,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
