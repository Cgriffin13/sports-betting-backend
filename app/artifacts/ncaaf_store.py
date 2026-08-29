from __future__ import annotations

import gzip
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.domain.ncaaf import ARTIFACT_FORMAT


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    uri: str
    stored_bytes: int
    format: str = ARTIFACT_FORMAT


class ImmutableArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path_for(self, *, endpoint: str, season: int | None, week: int | None, digest: str) -> Path:
        path = self.root / "provider=cfbd" / "league=NCAAF"
        if season is not None:
            path /= f"season={season}"
        if week is not None:
            path /= f"week={week:02d}"
        return path / f"endpoint={endpoint.replace('/', '_')}" / f"{digest}.json.gz"

    def put(
        self,
        payload: bytes,
        *,
        endpoint: str,
        season: int | None,
        week: int | None,
        digest: str,
    ) -> StoredArtifact:
        destination = self.path_for(endpoint=endpoint, season=season, week=week, digest=digest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            temporary = destination.parent / f".{uuid4().hex}.tmp"
            temporary.write_bytes(gzip.compress(payload, mtime=0))
            os.replace(temporary, destination)
        relative = destination.relative_to(self.root).as_posix()
        return StoredArtifact(uri=relative, stored_bytes=destination.stat().st_size)

    def exists(self, uri: str) -> bool:
        candidate = (self.root / uri).resolve()
        return candidate.is_relative_to(self.root) and candidate.is_file()

    def get(self, uri: str) -> bytes:
        candidate = (self.root / uri).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            raise FileNotFoundError("artifact is unavailable")
        return gzip.decompress(candidate.read_bytes())
