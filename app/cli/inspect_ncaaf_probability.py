from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one offline NCAAF OOF probability row")
    parser.add_argument("game_id", type=int)
    parser.add_argument("--output-dir", type=Path, default=Path(".ncaaf-data/models/probability-v1"))
    parser.add_argument("--target", choices=["margin", "total"], default="margin")
    args = parser.parse_args()
    table = pq.read_table(args.output_dir / "oof_probabilities.parquet")
    table = table.filter(pc.and_(pc.equal(table["provider_game_id"], args.game_id), pc.equal(table["target"], args.target)))
    if table.num_rows == 0:
        raise SystemExit("probability row not found")
    print(json.dumps(table.slice(0, 1).to_pylist()[0], default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
