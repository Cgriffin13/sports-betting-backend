from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate deterministic NCAAF preseason model artifacts")
    parser.add_argument("--model-dir", type=Path, default=Path(".ncaaf-data/models/preseason-v1"))
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    if args.network:
        parser.error("preseason model validation is offline")
    manifest = json.loads((args.model_dir / "run_manifest.json").read_text(encoding="utf-8"))
    path = args.model_dir / "oof_preseason_predictions.parquet"
    table = pq.ParquetFile(path).read()
    errors: list[str] = []
    if max(int(value) for value in table["season"].to_pylist()) >= 2025:
        errors.append("locked 2025 holdout appears in predictions")
    if table.num_rows != int(manifest["prediction_rows"]):
        errors.append("prediction row count mismatch")
    if _hash(path) != manifest["prediction_file_hash"]:
        errors.append("prediction file hash mismatch")
    if bool(manifest["holdout_accessed"]):
        errors.append("manifest reports holdout access")
    print(json.dumps({"valid": not errors, "errors": errors, "run_hash": manifest["run_hash"]}, sort_keys=True))
    if errors:
        raise SystemExit(1)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
