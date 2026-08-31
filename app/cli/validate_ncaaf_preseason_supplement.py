from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.ncaaf.preseason_supplement import validate_preseason_supplement


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NCAAF preseason supplemental artifacts")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/preseason-supplement-v1"))
    args = parser.parse_args()
    errors = validate_preseason_supplement(args.output_dir)
    print(json.dumps({"valid": not errors, "errors": errors}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
