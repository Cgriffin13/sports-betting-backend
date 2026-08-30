from __future__ import annotations

import argparse
import json

from app.research.ncaaf.probability import (
    NormalDistribution,
    moneyline_probabilities,
    spread_probabilities,
    total_probabilities,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate a synthetic line probability from an offline Normal distribution")
    parser.add_argument("--market", choices=["moneyline", "spread", "total"], required=True)
    parser.add_argument("--mean", type=float, required=True)
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--line", type=float)
    parser.add_argument("--under", action="store_true")
    args = parser.parse_args()
    distribution = NormalDistribution(args.mean, args.scale)
    if args.market == "moneyline":
        result = moneyline_probabilities(distribution)
    elif args.market == "spread":
        if args.line is None:
            parser.error("spread requires --line")
        result = spread_probabilities(distribution, args.line)
    else:
        if args.line is None:
            parser.error("total requires --line")
        result = total_probabilities(distribution, args.line, over=not args.under)
    print(json.dumps({"win": result.win, "push": result.push, "loss": result.loss, "audit": result.audit}, sort_keys=True))


if __name__ == "__main__":
    main()
