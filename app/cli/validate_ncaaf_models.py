from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.ncaaf.modeling import validate_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate NCAAF baseline model artifacts without network access")
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/baseline-v1"))
    args = parser.parse_args()
    errors = validate_run(args.output_dir)
    print(json.dumps({"errors": errors, "valid": not errors}, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
