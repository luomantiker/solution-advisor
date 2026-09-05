from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from solution_advisor.persistence.database import Base


class PlatformCatalog(Base):
    """Immutable reviewed platform package version; never derived from an image."""
    __tablename__ = "platform_catalogs"
    __table_args__ = (UniqueConstraint("platform_id", "version", name="uq_platform_catalog_version"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"catalog_{uuid4().hex}")
    platform_type_id: Mapped[str | None] = mapped_column(ForeignKey("platform_types.id"), nullable=True, index=True)
    platform_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="PENDING_INTEGRATION", index=True)
    package_manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    image_lock: Mapped[dict] = mapped_column(JSON, default=dict)
    runner: Mapped[dict] = mapped_column(JSON, default=dict)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    review: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlatformCandidate(Base):
    __tablename__ = "platform_candidates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"candidate_{uuid4().hex}")
    platform_type_id: Mapped[str | None] = mapped_column(ForeignKey("platform_types.id"), nullable=True, index=True)
    target_version: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    image_ref: Mapped[str] = mapped_column(String)
    image_id: Mapped[str] = mapped_column(String)
    toolchain_version: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String, default="CANDIDATE_IMAGE", index=True)
    catalog_id: Mapped[str | None] = mapped_column(ForeignKey("platform_catalogs.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String, default="admin")
    claimed_by: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    claimed_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Legacy audit compatibility only.  Candidate authorization is perpetual
    # manual `claimed_by` ownership; this field is cleared by migration 0027
    # and is never interpreted as a deadline.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_handled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    last_handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    archived_by: Mapped[str | None] = mapped_column(String, nullable=True)
    archive_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformType(Base):
    """Global platform-family asset, reused by every versioned Candidate."""
    __tablename__ = "platform_types"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"platform_type_{uuid4().hex}")
    name: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    created_by: Mapped[str] = mapped_column(String, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HostAgent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    host_state: Mapped[str] = mapped_column(String, default="OFFLINE")
    agent_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    discovery_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class HostImage(Base):
    """Read-only image fact reported by a HostAgent; not a platform candidate."""
    __tablename__ = "host_images"
    __table_args__ = (UniqueConstraint("agent_id", "image_id", name="uq_host_image_agent_digest"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"host_image_{uuid4().hex}")
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    image_ref: Mapped[str] = mapped_column(String)
    image_id: Mapped[str] = mapped_column(String, index=True)
    toolchain_version: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    hidden: Mapped[bool] = mapped_column(default=False)
    hidden_by: Mapped[str | None] = mapped_column(String, nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformBinding(Base):
    __tablename__ = "platform_bindings"
    __table_args__ = (UniqueConstraint("agent_id", "catalog_id", name="uq_platform_binding_agent_catalog"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"binding_{uuid4().hex}")
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    catalog_id: Mapped[str] = mapped_column(ForeignKey("platform_catalogs.id"), index=True)
    platform_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, default="HEALTHY", index=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    image_lock_version: Mapped[str] = mapped_column(String)
    actual_image_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_image_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    image_match_status: Mapped[str] = mapped_column(String, default="MATCH")
    runner_version: Mapped[str] = mapped_column(String)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformWorker(Base):
    __tablename__ = "platform_workers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"worker_{uuid4().hex}")
    binding_id: Mapped[str] = mapped_column(ForeignKey("platform_bindings.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    platform_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String, default="READY", index=True)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    runner: Mapped[dict] = mapped_column(JSON, default=dict)
    current_task_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformAudit(Base):
    __tablename__ = "platform_audits"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"platform_audit_{uuid4().hex}")
    action: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    catalog_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    binding_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    result: Mapped[str] = mapped_column(String, default="SUCCEEDED")
    summary: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserAccount(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_source: Mapped[str] = mapped_column(String(16), default="SSO")
    # 人员来源是治理分类，不参与认证或授权决策。认证仍由 auth_source /
    # provider link 统一处理，避免把“谁创建账号”误当成身份可信度。
    person_source: Mapped[str] = mapped_column(String(24), default="INTERNAL_GENERATED", index=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ``id`` remains the durable business subject.  These fields make the
    # authentication-provider link explicit without tying authorization to a
    # local password implementation.
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", index=True)
    quota: Mapped[dict] = mapped_column(JSON, default=dict)
    capability_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    auth_provider_type: Mapped[str] = mapped_column(String(24), default="SSO")
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identity_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IdentityLink(Base):
    """One Account may later be linked to a local or external provider identity."""
    __tablename__ = "identity_links"
    __table_args__ = (UniqueConstraint("provider_type", "issuer", "subject", name="uq_identity_link"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"identity_{uuid4().hex}")
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider_type: Mapped[str] = mapped_column(String(24))
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuthenticationSession(Base):
    """Opaque server-side session; its random id is the only cookie value."""
    __tablename__ = "authentication_sessions"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AccountAudit(Base):
    __tablename__ = "account_audits"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"account_audit_{uuid4().hex}")
    actor: Mapped[str] = mapped_column(String, index=True)
    account_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    old_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserNotificationState(Base):
    """Per-account display state for a redacted notification projection.

    Business facts stay in their original audit/flow tables.  This table only
    records whether one account has read or hidden a projected notification.
    """
    __tablename__ = "user_notification_states"
    __table_args__ = (UniqueConstraint("account_id", "notification_key", name="uq_user_notification_state"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"notification_state_{uuid4().hex}")
    account_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    notification_key: Mapped[str] = mapped_column(String(96), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CandidateHistory(Base):
    __tablename__ = "candidate_history"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"candidate_history_{uuid4().hex}")
    candidate_id: Mapped[str] = mapped_column(ForeignKey("platform_candidates.id"), index=True)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    old_revision: Mapped[int] = mapped_column(Integer)
    new_revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CandidateValidationTask(Base):
    """A HostAgent-only real validation bound to one immutable Candidate revision."""
    __tablename__ = "candidate_validation_tasks"
    __table_args__ = (UniqueConstraint("candidate_id", "candidate_revision", "attempt", name="uq_candidate_validation_revision_attempt"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: f"candidate_validation_{uuid4().hex}")
    candidate_id: Mapped[str] = mapped_column(ForeignKey("platform_candidates.id"), index=True)
    candidate_revision: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    runner_release: Mapped[str] = mapped_column(String, nullable=False)
    worker_instance_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
