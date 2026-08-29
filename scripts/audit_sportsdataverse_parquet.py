"""Inspect public SportsDataverse Parquet release metadata without downloading data rows.

Research-only usage (PyArrow is intentionally not an application dependency):

    python -m pip install --target <temp-dir> pyarrow==21.0.0
    PYTHONPATH=<temp-dir> python scripts/audit_sportsdataverse_parquet.py \
        --tag espn_cfb_pbp --asset-prefix play_by_play --start-year 2014 --end-year 2025

The script requests only each Parquet footer and emits JSON. It never reads credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

GITHUB_RELEASE_URL = "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/{tag}"
USER_AGENT = "sports-betting-backend-phase5b-source-audit"


def _request(url: str, *, byte_range: str | None = None) -> bytes:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if byte_range is not None:
        headers["Range"] = byte_range
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return response.read()


def _release_assets(tag: str) -> list[dict[str, Any]]:
    payload = json.loads(_request(GITHUB_RELEASE_URL.format(tag=tag)))
    return list(payload["assets"])


def _parquet_metadata(url: str, size: int) -> Any:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - research environment guard
        raise SystemExit("PyArrow is required only for this research script; see its module docstring.") from exc

    trailer = _request(url, byte_range=f"bytes={size - 8}-{size - 1}")
    if len(trailer) != 8 or trailer[4:] != b"PAR1":
        raise ValueError(f"Invalid Parquet trailer from {url}")
    metadata_length = struct.unpack("<I", trailer[:4])[0]
    footer_start = size - 8 - metadata_length
    footer = _request(url, byte_range=f"bytes={footer_start}-{size - 1}")
    synthetic_file = b"PAR1" + footer
    return pq.read_metadata(pa.BufferReader(synthetic_file))


def _column_nulls(metadata: Any, columns: Iterable[str]) -> dict[str, int | None]:
    requested = set(columns)
    totals: dict[str, int] = {column: 0 for column in requested}
    has_statistics: dict[str, bool] = {column: True for column in requested}
    for row_group_index in range(metadata.num_row_groups):
        row_group = metadata.row_group(row_group_index)
        for column_index in range(row_group.num_columns):
            column = row_group.column(column_index)
            name = column.path_in_schema
            if name not in requested:
                continue
            statistics = column.statistics
            if statistics is None or statistics.null_count is None:
                has_statistics[name] = False
            else:
                totals[name] += statistics.null_count
    return {column: totals[column] if has_statistics[column] else None for column in sorted(requested)}


def _scan_parquet(url: str, columns: list[str], value_count_columns: list[str]) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - research environment guard
        raise SystemExit("PyArrow is required only for this research script; see its module docstring.") from exc

    temp_path: str | None = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with (
            urllib.request.urlopen(request, timeout=120) as response,
            tempfile.NamedTemporaryFile(prefix="ncaaf-source-audit-", suffix=".parquet", delete=False) as destination,
        ):
            temp_path = destination.name
            shutil.copyfileobj(response, destination)
        available_columns = set(pq.read_schema(temp_path).names)
        selected = [column for column in columns if column in available_columns]
        data = pq.read_table(temp_path, columns=selected).to_pydict()
        row_count = len(next(iter(data.values()), []))
        null_counts = {column: sum(value is None for value in values) for column, values in data.items()}
        value_counts = {
            column: {
                str(value): count
                for value, count in sorted(Counter(data[column]).items(), key=lambda item: str(item[0]))
            }
            for column in value_count_columns
            if column in data
        }
        games = len(set(data.get("game_id", [])) - {None})
        team_rows: dict[str, int] = Counter(str(value) for value in data.get("pos_team", []) if value is not None)
        team_epa_nulls: dict[str, int] = defaultdict(int)
        for team, epa in zip(data.get("pos_team", []), data.get("EPA", []), strict=False):
            if team is not None and epa is None:
                team_epa_nulls[str(team)] += 1
        return {
            "downloaded_bytes": os.path.getsize(temp_path),
            "rows": row_count,
            "games": games,
            "selected_column_nulls": null_counts,
            "selected_value_counts": value_counts,
            "teams": len(team_rows),
            "teams_with_epa_nulls": {
                team: {"rows": team_rows[team], "epa_nulls": count}
                for team, count in sorted(team_epa_nulls.items(), key=lambda item: (-item[1], item[0]))
            },
        }
    finally:
        if temp_path is not None:
            os.unlink(temp_path)


def audit(
    tag: str,
    asset_prefix: str,
    start_year: int,
    end_year: int,
    columns: list[str],
    *,
    scan_data: bool,
    value_count_columns: list[str],
) -> dict[str, Any]:
    assets = {asset["name"]: asset for asset in _release_assets(tag) if asset["name"].endswith(".parquet")}
    seasons: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        name = f"{asset_prefix}_{year}.parquet"
        asset = assets.get(name)
        if asset is None:
            seasons.append({"season": year, "asset": name, "available": False})
            continue
        metadata = _parquet_metadata(asset["browser_download_url"], int(asset["size"]))
        schema_names = set(metadata.schema.names)
        season_result = {
            "season": year,
            "asset": name,
            "available": True,
            "size_bytes": int(asset["size"]),
            "rows": metadata.num_rows,
            "row_groups": metadata.num_row_groups,
            "columns": metadata.num_columns,
            "requested_column_presence": {column: column in schema_names for column in columns},
            "requested_column_nulls": _column_nulls(metadata, [c for c in columns if c in schema_names]),
            "sha256": asset.get("digest"),
            "updated_at": asset.get("updated_at"),
            "url": asset["browser_download_url"],
        }
        if scan_data:
            season_result["data_scan"] = _scan_parquet(asset["browser_download_url"], columns, value_count_columns)
        seasons.append(season_result)
    return {"tag": tag, "asset_prefix": asset_prefix, "seasons": seasons}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--asset-prefix", required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument("--column", action="append", default=[])
    parser.add_argument("--value-count", action="append", default=[])
    parser.add_argument(
        "--scan-data",
        action="store_true",
        help="Download each selected asset temporarily and calculate exact selected-column/team counts.",
    )
    args = parser.parse_args()
    if args.start_year > args.end_year:
        parser.error("--start-year must be at or before --end-year")
    result = audit(
        args.tag,
        args.asset_prefix,
        args.start_year,
        args.end_year,
        args.column,
        scan_data=args.scan_data,
        value_count_columns=args.value_count,
    )
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
