from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Mapping
from typing import Any, cast

import pytest
from sqlalchemy import Table, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import Session

from app.artifacts.ncaaf_store import ImmutableArtifactStore
from app.db.market_models import CanonicalEvent, ProviderEventMapping
from app.db.ncaaf_models import (
    CanonicalVenue,
    FootballGameFact,
    ProgramAlias,
    ProgramSeasonMembership,
    ProviderProgramMapping,
    ProviderVenueMapping,
    SourceArtifactIndex,
    SourceManifest,
)
from app.domain.ncaaf import (
    CFBD_PROVIDER,
    build_game_eligibility,
    canonical_request_hash,
    canonical_request_parameters,
    validate_development_seasons,
)
from app.persistence.ncaaf_repository import NcaafRepository
from app.providers.cfbd import CfbdResponse
from app.providers.cfbd import CfbdClient, CfbdProviderError
from app.services.ncaaf_ingestion_service import NcaafIngestionService


class FakeCfbdClient:
    def __init__(self, payloads: list[list[dict[str, Any]] | dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls = 0

    def get(self, endpoint: str, parameters: Mapping[str, Any] | None = None) -> CfbdResponse:
        parameters = parameters or {}
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return CfbdResponse(
            endpoint=endpoint,
            parameters=canonical_request_parameters(parameters),
            retrieved_at=datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
            payload_bytes=body,
            records=payload,
            headers={"etag": f'"version-{self.calls}"'},
            status_code=200,
        )


def _service(session: Session, tmp_path: Path, client: FakeCfbdClient) -> NcaafIngestionService:
    return NcaafIngestionService(client, NcaafRepository(session), ImmutableArtifactStore(tmp_path))


def test_request_canonicalization_excludes_credentials() -> None:
    parameters = {"year": 2024, "week": 1, "Authorization": "secret", "api_key": "secret", "token": "secret"}
    assert canonical_request_parameters(parameters) == {"week": 1, "year": 2024}
    digest = canonical_request_hash(CFBD_PROVIDER, "games", parameters)
    assert len(digest) == 64
    assert "secret" not in digest
    assert digest == canonical_request_hash(CFBD_PROVIDER, "/games", {"week": 1, "year": 2024})


def test_holdout_guard_defaults_to_2024() -> None:
    validate_development_seasons(2014, 2024)
    with pytest.raises(ValueError, match="sealed"):
        validate_development_seasons(2014, 2025)
    validate_development_seasons(2025, 2025, allow_holdout=True)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"completed": False}, "not_final"),
        ({"completed": False, "status": "cancelled"}, "cancelled"),
        ({"completed": False, "status": "postponed"}, "postponed"),
        ({"awayClassification": "fcs"}, "not_fbs_vs_fbs"),
        ({"awayId": None}, "unresolved_program_identity"),
        ({"homePoints": None}, "missing_final_score"),
        ({"forfeit": True}, "manual_result_review"),
    ],
)
def test_game_exclusion_reasons(changes: dict[str, Any], reason: str) -> None:
    game = _game()
    game.update(changes)
    result = build_game_eligibility(game)
    assert result.eligible is False
    assert result.exclusion_reason == reason
    assert result.margin is None
    assert result.total is None


def test_game_targets_include_overtime_final_and_neutral_site() -> None:
    game = _game()
    game.update({"homePoints": 31, "awayPoints": 28, "overtimePeriods": 1, "neutralSite": True})
    result = build_game_eligibility(game)
    assert result.eligible is True
    assert result.margin == 3
    assert result.total == 59


def test_immutable_cache_idempotency_and_secret_free_manifest(session_factory: Any, tmp_path: Path) -> None:
    client = FakeCfbdClient([[{"id": 1, "school": "Alpha", "classification": "fbs", "conference": "A"}]])
    with session_factory() as session:
        service = _service(session, tmp_path, client)
        first = service.ingest("teams", {"year": 2024, "authorization": "secret"})
        session.commit()
        second = service.ingest("teams", {"year": 2024, "authorization": "different-secret"})
        session.commit()
        assert first.manifest_id == second.manifest_id
        assert second.cache_hit is True
        assert second.provider_calls == 0
        assert client.calls == 1
        assert session.scalar(select(func.count()).select_from(SourceManifest)) == 1
        assert session.scalar(select(func.count()).select_from(ProviderProgramMapping)) == 1
        assert session.scalar(select(func.count()).select_from(ProgramAlias)) == 1
        manifest = session.scalar(select(SourceManifest))
        assert manifest is not None
        assert manifest.request_parameters == {"year": 2024}
        assert "secret" not in manifest.request_hash
        assert "secret" not in manifest.artifact_uri


def test_changed_response_creates_superseding_source_version(session_factory: Any, tmp_path: Path) -> None:
    client = FakeCfbdClient([
        [{"id": 1, "school": "Alpha", "classification": "fbs"}],
        [{"id": 1, "school": "Alpha State", "classification": "fbs"}],
    ])
    with session_factory() as session:
        service = _service(session, tmp_path, client)
        first = service.ingest("teams", {"year": 2024})
        session.commit()
        second = service.ingest("teams", {"year": 2024}, refresh=True)
        session.commit()
        manifests = session.scalars(select(SourceManifest).order_by(SourceManifest.retrieved_at)).all()
        assert len(manifests) == 2
        assert second.manifest_id != first.manifest_id
        assert manifests[1].supersedes_manifest_id == manifests[0].id
        assert session.scalar(select(func.count()).select_from(ProviderProgramMapping)) == 1
        assert session.scalar(select(func.count()).select_from(ProgramAlias)) == 2


def test_program_membership_is_effective_dated(session_factory: Any, tmp_path: Path) -> None:
    client = FakeCfbdClient([[{"id": 1, "school": "Alpha", "classification": "fbs", "conference": "Old"}]])
    with session_factory() as session:
        service = _service(session, tmp_path, client)
        service.ingest("teams", {"year": 2023})
        session.commit()
        client.payloads = [[{"id": 1, "school": "Alpha", "classification": "fbs", "conference": "New"}]]
        service.ingest("teams", {"year": 2024})
        session.commit()
        memberships = session.scalars(select(ProgramSeasonMembership).order_by(ProgramSeasonMembership.season)).all()
        assert [(item.season, item.conference_name) for item in memberships] == [(2023, "Old"), (2024, "New")]


def test_game_ingestion_uses_exact_provider_mapping_and_no_duplicate_facts(
    session_factory: Any,
    tmp_path: Path,
) -> None:
    teams = [
        {"id": 1, "school": "Alpha", "classification": "fbs"},
        {"id": 2, "school": "Beta", "classification": "fbs"},
    ]
    client = FakeCfbdClient([teams])
    with session_factory() as session:
        service = _service(session, tmp_path, client)
        service.ingest("teams", {"year": 2024})
        session.commit()
        client.payloads = [[_game()]]
        game_result = service.ingest("games", {"year": 2024, "classification": "fbs"})
        session.commit()
        replay = service.ingest("games", {"year": 2024, "classification": "fbs"})
        session.commit()
        assert replay.manifest_id == game_result.manifest_id
        assert replay.provider_calls == 0
        assert session.scalar(select(func.count()).select_from(FootballGameFact)) == 1
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 1
        mapping = session.scalar(select(ProviderEventMapping))
        assert mapping is not None
        assert mapping.provider_event_id == "100"
        assert mapping.review_status == "matched"
        fact = session.scalar(select(FootballGameFact))
        assert fact is not None
        assert fact.model_eligible is True
        assert fact.target_margin == 7
        assert fact.target_total == 55
        assert fact.neutral_site is True


def test_artifact_index_tracks_game_ids_and_resume(session_factory: Any, tmp_path: Path) -> None:
    records = [{"gameId": 100, "id": "play-1"}, {"gameId": 101, "id": "play-2"}]
    client = FakeCfbdClient([records])
    with session_factory() as session:
        service = _service(session, tmp_path, client)
        result = service.ingest("plays", {"year": 2024, "week": 1})
        session.commit()
        resumed = service.ingest("plays", {"year": 2024, "week": 1})
        session.commit()
        index = session.scalar(select(SourceArtifactIndex))
        assert index is not None
        assert index.included_game_ids == [100, 101]
        assert index.row_count == 2
        assert resumed.manifest_id == result.manifest_id
        assert session.scalar(select(func.count()).select_from(SourceArtifactIndex)) == 1


def test_venue_identity_uses_provider_id_and_preserves_source_vintage(session_factory: Any, tmp_path: Path) -> None:
    records = [
        {
            "id": 10,
            "name": "Example Stadium",
            "timezone": "America/New_York",
            "latitude": 40.0,
            "longitude": -75.0,
            "elevation": 200,
            "dome": False,
            "grass": True,
        }
    ]
    with session_factory() as session:
        _service(session, tmp_path, FakeCfbdClient([records])).ingest("venues", {})
        session.commit()
        venue = session.scalar(select(CanonicalVenue))
        mapping = session.scalar(select(ProviderVenueMapping))
        assert venue is not None and mapping is not None
        assert venue.timezone == "America/New_York"
        assert venue.surface == "grass"
        assert venue.source_vintage is not None
        assert venue.source_vintage.replace(tzinfo=UTC) == datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
        assert mapping.provider_venue_id == "10"


def test_ingestion_transaction_can_roll_back_manifest_and_identity(
    session_factory: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeCfbdClient([[{"id": 1, "school": "Alpha"}]])
    with session_factory() as session:
        service = _service(session, tmp_path, client)

        def fail(*args: Any, **kwargs: Any) -> int:
            raise RuntimeError("normalization failed")

        monkeypatch.setattr(service.repository, "upsert_programs", fail)
        with pytest.raises(RuntimeError, match="normalization failed"):
            service.ingest("teams", {"year": 2024})
        session.rollback()
        assert session.scalar(select(func.count()).select_from(SourceManifest)) == 0
        assert session.scalar(select(func.count()).select_from(ProviderProgramMapping)) == 0


class FakeHttpResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.content = body
        self.headers = {"Authorization": "secret", "ETag": '"safe"'}


class FakeHttpSession:
    def __init__(self, response: FakeHttpResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeHttpResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_cfbd_client_keeps_secret_out_of_url_parameters_and_metadata() -> None:
    session = FakeHttpSession(FakeHttpResponse(200, b'[{"id":1}]'))
    result = CfbdClient("super-secret", session=cast(Any, session)).get(
        "games", {"year": 2024, "api_key": "bad"}
    )
    call = session.calls[0]
    assert "super-secret" not in call["url"]
    assert call["params"] == {"year": 2024}
    assert call["headers"]["Authorization"] == "Bearer super-secret"
    assert result.headers == {"etag": '"safe"'}
    assert "super-secret" not in repr(result)


def test_cfbd_error_is_sanitized() -> None:
    session = FakeHttpSession(FakeHttpResponse(401, b'{"detail":"credential-bearing failure"}'))
    with pytest.raises(CfbdProviderError, match="HTTP 401") as error:
        CfbdClient("super-secret", session=cast(Any, session)).get("games", {"year": 2024})
    assert "super-secret" not in str(error.value)
    assert "credential-bearing" not in str(error.value)


def test_ncaaf_manifest_and_fact_schema_compile_for_postgresql() -> None:
    manifest_sql = str(
        CreateTable(cast(Table, SourceManifest.__table__)).compile(dialect=postgresql.dialect())
    ).lower()
    fact_sql = str(
        CreateTable(cast(Table, FootballGameFact.__table__)).compile(dialect=postgresql.dialect())
    ).lower()
    assert "jsonb" in manifest_sql
    assert "uq_source_manifest_version" in manifest_sql
    assert "uq_football_game_fact_version" in fact_sql
    assert "foreign key(manifest_id)" in fact_sql


def _game() -> dict[str, Any]:
    return {
        "id": 100,
        "season": 2024,
        "week": 1,
        "seasonType": "regular",
        "startDate": "2024-08-31T19:00:00Z",
        "completed": True,
        "status": "completed",
        "neutralSite": True,
        "homeId": 1,
        "homeTeam": "Alpha",
        "homeClassification": "fbs",
        "homePoints": 31,
        "awayId": 2,
        "awayTeam": "Beta",
        "awayClassification": "fbs",
        "awayPoints": 24,
    }
