from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.ncaaf.calibration import validate_probability_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate offline NCAAF probability artifacts")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    args = parser.parse_args()
    errors = validate_probability_run(args.output_dir)
    print(json.dumps({"errors": errors, "valid": not errors}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
