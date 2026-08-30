from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from app.research.ncaaf.probability import empirical_discrete_distribution, spread_probabilities


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one stored empirical-discrete NCAAF margin pool")
    parser.add_argument("--pool-file", type=Path, default=Path(".ncaaf-data/models/key-number-v1/empirical_discrete_pools.json"))
    parser.add_argument("--pool-id", required=True)
    parser.add_argument("--location", required=True, type=float)
    parser.add_argument("--scale", required=True, type=float)
    parser.add_argument("--spread", type=float, default=-7.0)
    args = parser.parse_args()
    pools = json.loads(args.pool_file.read_text(encoding="utf-8"))
    matches = [row for row in pools if row["pool_id"] == args.pool_id]
    if len(matches) != 1:
        parser.error("pool ID was not found uniquely")
    pool = matches[0]
    support = np.arange(pool["support_min"], pool["support_max"] + 1, dtype=np.int16)
    distribution = empirical_discrete_distribution(
        args.location, args.scale, support, np.asarray(pool["ratios"], dtype=float), pool_id=args.pool_id
    )
    settlement = spread_probabilities(distribution, args.spread)
    print(
        json.dumps(
            {
                "family": distribution.family, "location": distribution.location, "scale": distribution.scale,
                "spread": args.spread, "win": settlement.win, "push": settlement.push,
                "loss": settlement.loss, "key_mass": {str(k): distribution.pdf(float(k)) for k in (3, 7, 10, 14)},
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
