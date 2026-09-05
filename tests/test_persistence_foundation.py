from __future__ import annotations

from io import BytesIO

from sqlalchemy import create_engine, inspect, select

from solution_advisor.artifacts.domain import Artifact, Evidence, EvidencePhase, EvidenceType, Visibility
from solution_advisor.artifacts.service import ArtifactService, EvidenceService
from solution_advisor.artifacts.storage import LocalArtifactStorage, S3ArtifactStorage
from solution_advisor.evaluations.domain import EvaluationResult, TaskSnapshot
from solution_advisor.persistence.database import make_session_factory
from solution_advisor.persistence.migrations import upgrade_database
from solution_advisor.config import Settings
from solution_advisor.common_analyzer.service import AnalysisService


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.buckets: set[str] = set()

    def head_bucket(self, *, Bucket):
        if Bucket not in self.buckets:
            raise RuntimeError("missing bucket")

    def create_bucket(self, *, Bucket):
        self.buckets.add(Bucket)

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise RuntimeError("missing object")

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.buckets.add(Bucket)
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)][0])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_migration_upgrades_empty_sqlite_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.sqlite3'}"
    upgrade_database(url)
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"artifacts", "evidences", "task_snapshots", "evaluation_results", "alembic_version"} <= tables


def test_postgresql_and_s3_configuration_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("SOLUTION_ADVISOR_DATABASE_URL", "postgresql+psycopg://user:pass@postgres:5432/advisor")
    monkeypatch.setenv("SOLUTION_ADVISOR_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("SOLUTION_ADVISOR_S3_ENDPOINT_URL", "http://minio:9000")
    settings = Settings.from_env()
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.storage_backend == "s3"
    assert settings.s3_endpoint_url == "http://minio:9000"


def test_local_artifact_storage_and_metadata_are_content_addressed(tmp_path):
    url = f"sqlite:///{tmp_path / 'metadata.sqlite3'}"
    upgrade_database(url)
    session = make_session_factory(url)()
    storage = LocalArtifactStorage(tmp_path / "objects")
    service = ArtifactService(session, storage)
    first = service.put(b"artifact bytes", content_type="application/octet-stream")
    second = service.put(b"artifact bytes", content_type="application/octet-stream")
    session.commit()
    assert first.id == second.id
    assert first.uri.startswith("file://")
    assert storage.open(first.uri).read() == b"artifact bytes"
    assert session.scalar(select(Artifact).where(Artifact.id == first.id)).sha256 == first.sha256
    session.close()


def test_s3_storage_uri_deduplication_and_object_operations():
    fake = FakeS3()
    storage = S3ArtifactStorage(fake, bucket="unit-bucket", prefix="solution-advisor")
    storage.ensure_bucket()
    stored = storage.put(b"s3 evidence", content_type="text/plain")
    assert stored.uri.startswith("s3://unit-bucket/solution-advisor/sha256/")
    assert storage.exists(stored.uri)
    assert storage.open(stored.uri).read() == b"s3 evidence"
    assert storage.put(b"s3 evidence", content_type="text/plain").uri == stored.uri
    storage.delete(stored.uri)
    assert not storage.exists(stored.uri)


def test_evidence_and_result_contracts_are_persisted(client, model_bytes):
    upload = client.post("/api/v1/model-assets", files={"file": ("minimal.onnx", model_bytes)}).json()
    session = client.app.state.session_factory()
    AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(upload["analysis_task"]["id"])
    session.close()
    profile_id = client.get(f"/api/v1/analysis-tasks/{upload['analysis_task']['id']}").json()["profile_id"]
    task = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "platforms": ["X5"]}).json()
    session = client.app.state.session_factory()
    artifact = session.scalar(select(Artifact))
    evidence = EvidenceService(session).record(
        evidence_type=EvidenceType.COMPILATION_LOG.value, phase=EvidencePhase.COMPILATION.value,
        task_id=task["id"], platform="X5", artifact_id=artifact.id,
        visibility=Visibility.INTERNAL.value, toolchain_version="future-contract")
    session.commit()
    result = session.scalar(select(EvaluationResult).where(EvaluationResult.task_id == task["id"]))
    snapshot = session.get(TaskSnapshot, task["snapshot_id"])
    assert result.source == "DEMO" and result.evidence_ids == []
    assert snapshot.model_profile_id == profile_id
    assert evidence.evidence_type == EvidenceType.COMPILATION_LOG.value
    with __import__("pytest").raises(ValueError, match="evidence type"):
        EvidenceService(session).record(evidence_type="arbitrary", phase=EvidencePhase.COMPILATION.value, artifact_id=artifact.id)
    session.close()
