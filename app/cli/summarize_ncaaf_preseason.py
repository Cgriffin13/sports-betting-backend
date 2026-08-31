from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize bounded NCAAF preseason/personnel results")
    parser.add_argument("--primary-dir", type=Path, default=Path(".ncaaf-data/models/preseason-v1"))
    parser.add_argument("--supplement-dir", type=Path, default=Path(".ncaaf-data/models/preseason-supplement-v1"))
    args = parser.parse_args()
    primary = json.loads((args.primary_dir / "run_manifest.json").read_text(encoding="utf-8"))
    supplement = json.loads((args.supplement_dir / "run_manifest.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "primary_run_hash": primary["run_hash"],
                "supplement_run_hash": supplement["run_hash"],
                "input_dataset_hash": primary["input_dataset_hash"],
                "preseason_feature_set_hash": primary["preseason_feature_set_hash"],
                "candidates": primary["report"]["candidates"],
                "comparisons": primary["report"]["comparisons"],
                "family_only": supplement["family_only_summary"],
                "probability": supplement["probability_summary"],
                "uncertainty": supplement["uncertainty_segments"],
                "provider_calls": 0,
                "holdout_accessed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
