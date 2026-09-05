from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from solution_advisor.persistence.database import Base


class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"task_{uuid4().hex}")
    model_profile_id: Mapped[str] = mapped_column(ForeignKey("model_profiles.id"), index=True)
    mode: Mapped[str] = mapped_column(String)
    platforms: Mapped[list] = mapped_column(JSON)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("task_snapshots.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    worker_instance_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    task_kind: Mapped[str] = mapped_column(String, default="X5_COMPILE", index=True)
    source_task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    flow_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    owner_subject: Mapped[str] = mapped_column(String, default="system-admin", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvaluationFlow(Base):
    """One user-visible governed evaluation; execution tasks remain internal."""
    __tablename__ = "evaluation_flows"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"flow_{uuid4().hex}")
    model_profile_id: Mapped[str] = mapped_column(ForeignKey("model_profiles.id"), index=True)
    owner_subject: Mapped[str] = mapped_column(String, index=True)
    preset: Mapped[str] = mapped_column(String, default="standard-performance-1.0")
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    platform_snapshots: Mapped[dict] = mapped_column(JSON, default=dict)
    # The common ONNX/Profile analysis is frozen with the user-visible Flow.
    # Reports must never re-read a newer profile and rewrite an old conclusion.
    model_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReportRevision(Base):
    """Append-only customer-report revision for one EvaluationFlow."""
    __tablename__ = "report_revisions"
    __table_args__ = (UniqueConstraint("flow_id", "version", name="uq_report_revision_flow_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"report_{uuid4().hex}")
    flow_id: Mapped[str] = mapped_column(ForeignKey("evaluation_flows.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    template_version: Mapped[str] = mapped_column(String)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    pdf_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvaluationTaskShare(Base):
    __tablename__ = "evaluation_task_shares"
    __table_args__ = (UniqueConstraint("task_id", "subject", name="uq_evaluation_task_share_subject"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"task_share_{uuid4().hex}")
    task_id: Mapped[str] = mapped_column(ForeignKey("evaluation_tasks.id"), index=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    shared_by: Mapped[str] = mapped_column(String)
    include_model: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"result_{uuid4().hex}")
    task_id: Mapped[str] = mapped_column(ForeignKey("evaluation_tasks.id"), index=True)
    platform: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    fixture_version: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
    schema_version: Mapped[str] = mapped_column(String, default="1.0.0")
    common_result: Mapped[dict] = mapped_column(JSON, default=dict)
    platform_result: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)


class TaskSnapshot(Base):
    __tablename__ = "task_snapshots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"snapshot_{uuid4().hex}")
    task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    model_asset_id: Mapped[str] = mapped_column(ForeignKey("model_assets.id"), index=True)
    model_profile_id: Mapped[str] = mapped_column(ForeignKey("model_profiles.id"), index=True)
    evaluation_template_version: Mapped[str] = mapped_column(String, default="demo-template-1.0.0")
    report_template_version: Mapped[str] = mapped_column(String, default="mock-report-1.0.0")
    platform_package_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    platform_governance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
