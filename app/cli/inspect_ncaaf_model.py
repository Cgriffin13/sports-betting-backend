from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a baseline fold, model manifest, or metric summary")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    parser.add_argument("--fold")
    parser.add_argument("--metric-prefix")
    args = parser.parse_args()
    manifest = json.loads((args.output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    result: object = manifest
    if args.fold:
        result = next((fold for fold in manifest["folds"] if fold["fold_id"] == args.fold), None)
    elif args.metric_prefix:
        result = {key: value for key, value in manifest["summary"].items() if key.startswith(args.metric_prefix)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
