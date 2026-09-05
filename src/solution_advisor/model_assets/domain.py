from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from solution_advisor.persistence.database import Base


class ModelAsset(Base):
    __tablename__ = "model_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"asset_{uuid4().hex}")
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True, index=True)
    owner_subject: Mapped[str] = mapped_column(String, default="system-admin", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelAssetAccess(Base):
    """Per-user logical ownership/share over globally deduplicated model bytes."""
    __tablename__ = "model_asset_accesses"
    __table_args__ = (UniqueConstraint("model_asset_id", "subject", name="uq_model_asset_access_subject"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"model_access_{uuid4().hex}")
    model_asset_id: Mapped[str] = mapped_column(ForeignKey("model_assets.id"), index=True)
    subject: Mapped[str] = mapped_column(String, index=True)
    access_kind: Mapped[str] = mapped_column(String(16), default="OWNER")
    granted_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResourceAccessAudit(Base):
    __tablename__ = "resource_access_audits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"resource_audit_{uuid4().hex}")
    resource_type: Mapped[str] = mapped_column(String(16), index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String(24))
    actor_subject: Mapped[str] = mapped_column(String, index=True)
    recipient_subject: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ModelProfile(Base):
    __tablename__ = "model_profiles"
    __table_args__ = (UniqueConstraint("onnx_sha256", "analyzer_version", name="uq_profile_cache"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"profile_{uuid4().hex}")
    model_asset_id: Mapped[str] = mapped_column(ForeignKey("model_assets.id"), index=True)
    onnx_sha256: Mapped[str] = mapped_column(String(64), index=True)
    analyzer_version: Mapped[str] = mapped_column(String)
    analysis: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
