from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.research.ncaaf.challenger_distribution import validate_challenger_distribution
from app.research.ncaaf.key_numbers import validate_key_number_run
from app.research.ncaaf.strong_models import validate_strong_model_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate offline Phase 5B-5 artifacts")
    parser.add_argument("--strong-dir", type=Path, default=Path(".ncaaf-data/models/strong-v1"))
    parser.add_argument("--key-number-dir", type=Path, default=Path(".ncaaf-data/models/key-number-v1"))
    parser.add_argument(
        "--challenger-distribution-dir",
        type=Path,
        default=Path(".ncaaf-data/models/strong-distribution-v1"),
    )
    args = parser.parse_args()
    errors = {
        "strong_models": validate_strong_model_run(args.strong_dir),
        "key_numbers": validate_key_number_run(args.key_number_dir),
        "challenger_distribution": validate_challenger_distribution(args.challenger_distribution_dir),
    }
    print(json.dumps(errors, sort_keys=True))
    if any(errors.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
