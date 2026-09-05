from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, JSON, String, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from solution_advisor.persistence.database import Base


class AnalyzerConfiguration(Base):
    __tablename__ = "analyzer_configurations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="default")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    modules: Mapped[dict] = mapped_column(JSON)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class AnalyzerConfigVersion(Base):
    __tablename__ = "analyzer_config_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda:f"config_{uuid4().hex}")
    version: Mapped[int] = mapped_column(Integer, unique=True)
    modules: Mapped[dict] = mapped_column(JSON); max_concurrency: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64)); created_by: Mapped[str] = mapped_column(String)
    change_note: Mapped[str] = mapped_column(String); state: Mapped[str] = mapped_column(String, default="PUBLISHED")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AnalyzerConfigAudit(Base):
    __tablename__ = "analyzer_config_audits"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda:f"audit_{uuid4().hex}")
    action: Mapped[str] = mapped_column(String); actor: Mapped[str] = mapped_column(String); old_version: Mapped[int | None] = mapped_column(Integer, nullable=True); new_version: Mapped[int | None] = mapped_column(Integer, nullable=True); summary: Mapped[str] = mapped_column(String); result: Mapped[str] = mapped_column(String, default="SUCCEEDED"); error_code: Mapped[str | None] = mapped_column(String, nullable=True); draft_id: Mapped[str | None] = mapped_column(String, nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class AnalyzerConfigDraft(Base):
    __tablename__ = "analyzer_config_drafts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"draft_{uuid4().hex}")
    base_version: Mapped[int] = mapped_column(Integer, index=True)
    modules: Mapped[dict] = mapped_column(JSON)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    config_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String, default="1")
    created_by: Mapped[str] = mapped_column(String)
    updated_by: Mapped[str] = mapped_column(String)
    change_note: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="DRAFT", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class WorkerCapacityLease(Base):
    __tablename__ = "worker_capacity_leases"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda:f"lease_{uuid4().hex}")
    worker_instance_id: Mapped[str] = mapped_column(String, index=True); slot_index: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[str] = mapped_column(String); attempt_id: Mapped[str] = mapped_column(String); lease_token: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String, default="ACTIVE"); expires_at: Mapped[datetime] = mapped_column(DateTime); last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkerInstance(Base):
    """Persistent worker facts; registration credentials never enter this table."""
    __tablename__ = "worker_instances"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_type: Mapped[str] = mapped_column(String)
    image_ref: Mapped[str] = mapped_column(String)
    image_id: Mapped[str | None] = mapped_column(String, nullable=True)
    toolchain_version: Mapped[str | None] = mapped_column(String, nullable=True)
    platform_package_version: Mapped[str | None] = mapped_column(String, nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON)
    max_concurrency: Mapped[int] = mapped_column(Integer)
    health: Mapped[str] = mapped_column(String, default="OFFLINE")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"analysis_{uuid4().hex}")
    model_asset_id: Mapped[str] = mapped_column(ForeignKey("model_assets.id"), index=True)
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnalysisEvent(Base):
    __tablename__ = "analysis_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"event_{uuid4().hex}")
    task_id: Mapped[str] = mapped_column(ForeignKey("analysis_tasks.id"), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stage_id: Mapped[str] = mapped_column(String)
    module_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    progress_percent: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    analyzer_version: Mapped[str] = mapped_column(String)
    result_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
