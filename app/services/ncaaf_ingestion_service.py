from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.artifacts.ncaaf_store import ImmutableArtifactStore
from app.db.ncaaf_models import SourceManifest
from app.domain.ncaaf import (
    ARTIFACT_FORMAT,
    CFBD_PROVIDER,
    SOURCE_SCHEMA_VERSION,
    canonical_request_hash,
)
from app.persistence.ncaaf_repository import NcaafRepository
from app.providers.cfbd import CfbdDataClient, CfbdResponse


@dataclass(frozen=True, slots=True)
class IngestionResult:
    manifest_id: str
    cache_hit: bool
    provider_calls: int
    row_count: int
    response_bytes: int
    stored_bytes: int
    content_hash: str
    artifact_uri: str


class NcaafIngestionService:
    def __init__(self, client: CfbdDataClient, repository: NcaafRepository, store: ImmutableArtifactStore) -> None:
        self.client = client
        self.repository = repository
        self.store = store

    def ingest(
        self,
        endpoint: str,
        parameters: dict[str, Any],
        *,
        refresh: bool = False,
    ) -> IngestionResult:
        request_hash = canonical_request_hash(CFBD_PROVIDER, endpoint, parameters)
        latest = self.repository.latest_manifest(request_hash)
        if not refresh and latest is not None and self.store.exists(latest.artifact_uri):
            records = json.loads(self.store.get(latest.artifact_uri))
            normalized_records = records if isinstance(records, list) else [records]
            self._normalize(latest, normalized_records, parameters)
            return _result(latest, cache_hit=True, provider_calls=0)
        response = self.client.get(endpoint, parameters)
        same = self.repository.same_manifest(request_hash, response.content_hash)
        if same is not None and self.store.exists(same.artifact_uri):
            same_records = response.records if isinstance(response.records, list) else [response.records]
            self._normalize(same, same_records, parameters)
            return _result(same, cache_hit=True, provider_calls=1)
        season = _integer_or_none(parameters.get("year"))
        week = _integer_or_none(parameters.get("week"))
        stored = self.store.put(
            response.payload_bytes,
            endpoint=endpoint,
            season=season,
            week=week,
            digest=response.content_hash,
        )
        manifest = self.repository.add_manifest(
            SourceManifest(
                provider=CFBD_PROVIDER,
                endpoint=endpoint.strip("/"),
                product=_product(endpoint),
                request_parameters=response.parameters,
                request_hash=request_hash,
                retrieved_at=response.retrieved_at,
                source_timestamps=_source_timestamps(response),
                content_hash=response.content_hash,
                schema_version=SOURCE_SCHEMA_VERSION,
                source_version=response.headers.get("etag") or response.headers.get("last-modified"),
                row_count=response.row_count,
                response_bytes=len(response.payload_bytes),
                stored_bytes=stored.stored_bytes,
                availability_mode="reconstructed" if season is not None and season < response.retrieved_at.year else "contemporaneous",
                response_metadata=response.headers,
                warnings=None,
                errors=None,
                supersedes_manifest_id=latest.id if latest else None,
                artifact_uri=stored.uri,
                artifact_format=ARTIFACT_FORMAT,
            )
        )
        records = response.records if isinstance(response.records, list) else [response.records]
        self._normalize(manifest, records, parameters)
        return _result(manifest, cache_hit=False, provider_calls=1)

    def _normalize(
        self,
        manifest: SourceManifest,
        records: list[dict[str, Any]],
        parameters: dict[str, Any],
    ) -> None:
        endpoint = manifest.endpoint
        season = _integer_or_none(parameters.get("year"))
        week = _integer_or_none(parameters.get("week"))
        self.repository.add_artifact_index(
            manifest,
            season=season,
            week=week,
            artifact_kind=_product(endpoint),
            records=records,
        )
        if endpoint.strip("/") in {"teams", "teams/fbs"} and season is not None:
            self.repository.upsert_programs(records, season=season, manifest_id=manifest.id)
        elif endpoint.strip("/") == "venues":
            self.repository.upsert_venues(records, manifest_id=manifest.id, retrieved_at=manifest.retrieved_at)
        elif endpoint.strip("/") == "games" and season is not None:
            self.repository.ingest_games(records, manifest_id=manifest.id, season=season)


def _source_timestamps(response: CfbdResponse) -> dict[str, Any] | None:
    values = {
        key: response.headers[key]
        for key in ("date", "last-modified")
        if key in response.headers
    }
    return values or None


def _product(endpoint: str) -> str:
    return endpoint.strip("/").replace("/", "_")


def _integer_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _result(manifest: SourceManifest, *, cache_hit: bool, provider_calls: int) -> IngestionResult:
    return IngestionResult(
        manifest_id=str(manifest.id),
        cache_hit=cache_hit,
        provider_calls=provider_calls,
        row_count=manifest.row_count,
        response_bytes=manifest.response_bytes,
        stored_bytes=manifest.stored_bytes,
        content_hash=manifest.content_hash,
        artifact_uri=manifest.artifact_uri,
    )
