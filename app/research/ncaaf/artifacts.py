from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from app.research.ncaaf.contracts import stable_hash, stable_json


@dataclass(frozen=True, slots=True)
class ParquetArtifact:
    dataset: str
    season: int | None
    uri: str
    content_hash: str
    file_hash: str
    row_count: int
    stored_bytes: int
    schema_hash: str
    source_manifest_ids: tuple[str, ...]
    source_content_hashes: tuple[str, ...]
    transformation_version: str
    schema_version: str


def schema_hash(schema: pa.Schema) -> str:
    return hashlib.sha256(schema.remove_metadata().serialize().to_pybytes()).hexdigest()


def table_content_hash(table: pa.Table) -> str:
    """Hash canonical Arrow IPC data, independent of Parquet file metadata."""
    table = table.combine_chunks().replace_schema_metadata(None)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResearchArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def write_parquet(
        self,
        table: pa.Table,
        *,
        namespace: str,
        dataset: str,
        season: int | None,
        schema_version: str,
        transformation_version: str,
        source_manifests: Sequence[Mapping[str, Any]],
        sort_by: Sequence[tuple[str, str]] = (),
    ) -> ParquetArtifact:
        if sort_by and table.num_rows:
            table = table.sort_by(list(sort_by))
        destination_dir = self.root / namespace / f"schema={schema_version}" / f"dataset={dataset}"
        if season is not None:
            destination_dir /= f"season={season}"
        destination_dir.mkdir(parents=True, exist_ok=True)
        temporary = destination_dir / f".{uuid4().hex}.tmp"
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            compression_level=9,
            use_dictionary=True,
            write_statistics=True,
            data_page_version="2.0",
        )
        content_digest = _file_hash(temporary)
        destination = destination_dir / f"{content_digest}.parquet"
        if destination.exists():
            temporary.unlink()
        else:
            os.replace(temporary, destination)
        ids = tuple(sorted(str(item["id"]) for item in source_manifests))
        hashes = tuple(sorted(str(item["content_hash"]) for item in source_manifests))
        return ParquetArtifact(
            dataset=dataset,
            season=season,
            uri=destination.relative_to(self.root).as_posix(),
            content_hash=content_digest,
            file_hash=content_digest,
            row_count=table.num_rows,
            stored_bytes=destination.stat().st_size,
            schema_hash=schema_hash(table.schema),
            source_manifest_ids=ids,
            source_content_hashes=hashes,
            transformation_version=transformation_version,
            schema_version=schema_version,
        )

    def read_table(self, uri: str, *, columns: Sequence[str] | None = None) -> pa.Table:
        path = (self.root / uri).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise FileNotFoundError("research artifact is unavailable")
        return pq.ParquetFile(path).read(columns=columns)

    def write_manifest(self, namespace: str, manifest: Mapping[str, Any]) -> tuple[str, Path]:
        deterministic = {key: value for key, value in manifest.items() if key != "built_at"}
        manifest_id = stable_hash(deterministic)
        path = self.root / namespace / "manifests" / f"{manifest_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            payload = dict(manifest)
            payload["manifest_id"] = manifest_id
            payload.setdefault("built_at", datetime.now(UTC).isoformat())
            _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        current = self.root / namespace / "current.json"
        _atomic_write(
            current,
            json.dumps({"manifest_id": manifest_id, "uri": path.relative_to(self.root).as_posix()}, sort_keys=True)
            + "\n",
        )
        return manifest_id, path

    def load_manifest(self, namespace: str, manifest_id: str | None = None) -> dict[str, Any]:
        if manifest_id is None:
            pointer = json.loads((self.root / namespace / "current.json").read_text(encoding="utf-8"))
            path = self.root / pointer["uri"]
        else:
            path = self.root / namespace / "manifests" / f"{manifest_id}.json"
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def validate_artifact(self, artifact: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        path = (self.root / str(artifact["uri"])).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            return [f"missing artifact: {artifact['uri']}"]
        if _file_hash(path) != artifact["file_hash"]:
            errors.append(f"file hash mismatch: {artifact['uri']}")
        table = pq.ParquetFile(path).read()
        if table.num_rows != artifact["row_count"]:
            errors.append(f"row count mismatch: {artifact['uri']}")
        if schema_hash(table.schema) != artifact["schema_hash"]:
            errors.append(f"schema hash mismatch: {artifact['uri']}")
        return errors


def artifact_dict(artifact: ParquetArtifact) -> dict[str, Any]:
    return asdict(artifact)


def dataset_hash(artifacts: Sequence[Mapping[str, Any]], configuration: Mapping[str, Any]) -> str:
    payload = {
        "artifacts": [
            {"dataset": item["dataset"], "season": item.get("season"), "content_hash": item["content_hash"]}
            for item in sorted(artifacts, key=lambda item: (str(item["dataset"]), int(item.get("season") or 0)))
        ],
        "configuration": configuration,
    }
    return stable_hash(payload)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{uuid4().hex}.tmp"
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def manifest_has_secret(manifest: Mapping[str, Any]) -> bool:
    lowered = stable_json(manifest).lower()
    return any(token in lowered for token in (b"authorization", b"api_key", b"apikey", b"bearer "))
