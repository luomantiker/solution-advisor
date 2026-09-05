from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_advisor.artifacts.domain import Artifact, Evidence, EvidencePhase, EvidenceType, Visibility
from solution_advisor.artifacts.storage import ArtifactStorage, StoredObject


class ArtifactService:
    def __init__(self, session: Session, storage: ArtifactStorage):
        self.session = session
        self.storage = storage

    def put(self, payload: bytes, *, content_type: str) -> Artifact:
        stored: StoredObject = self.storage.put(payload, content_type=content_type)
        artifact = self.session.scalar(select(Artifact).where(Artifact.uri == stored.uri))
        if artifact is None:
            artifact = Artifact(uri=stored.uri, sha256=stored.sha256, size_bytes=stored.size_bytes,
                                content_type=stored.content_type, storage_backend=stored.backend)
            self.session.add(artifact)
            self.session.flush()
        return artifact


class EvidenceService:
    """Future Worker-facing boundary; no public Worker endpoint is enabled in M0."""

    def __init__(self, session: Session):
        self.session = session

    def record(self, *, evidence_type: str, phase: str, artifact_id: str, task_id: str | None = None,
               platform: str | None = None, visibility: str = Visibility.INTERNAL.value,
               toolchain_version: str | None = None, rule_package_version: str | None = None) -> Evidence:
        if evidence_type not in {item.value for item in EvidenceType}:
            raise ValueError("Unsupported evidence type")
        if phase not in {item.value for item in EvidencePhase}:
            raise ValueError("Unsupported evidence phase")
        if visibility not in {item.value for item in Visibility}:
            raise ValueError("Unsupported evidence visibility")
        evidence = Evidence(evidence_type=evidence_type, phase=phase, artifact_id=artifact_id, task_id=task_id,
                            platform=platform, visibility=visibility, toolchain_version=toolchain_version,
                            rule_package_version=rule_package_version)
        self.session.add(evidence)
        return evidence
