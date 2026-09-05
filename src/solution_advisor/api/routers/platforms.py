import json
import re
import shlex
from zipfile import BadZipFile
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from solution_advisor.api.routers.analysis import admin
from solution_advisor.artifacts.domain import EvidencePhase, EvidenceType
from solution_advisor.artifacts.service import ArtifactService, EvidenceService
from solution_advisor.platforms.domain import CandidateHistory, CandidateValidationTask, HostImage, PlatformAudit, PlatformBinding, PlatformCandidate, PlatformCatalog, PlatformType, PlatformWorker, UserAccount
from solution_advisor.platforms.service import PlatformError, PlatformRegistry, binding_payload, catalog_payload, is_governance_service_image, utcnow, worker_payload
from solution_advisor.security import ADMIN, SUPER_ADMIN

router = APIRouter(tags=["platform-governance"])


def problem(exc: PlatformError, status: int = 422):
    raise HTTPException(status, {"code": str(exc)})


class CatalogInput(BaseModel):
    platform_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,61}$")
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    package_manifest: dict
    image_lock: dict
    runner: dict
    checks: dict
    review: dict


class BindingInput(BaseModel):
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    catalog_id: str = Field(pattern=r"^catalog_[a-zA-Z0-9_]+$")
    host_image_id: str | None = Field(default=None, pattern=r"^host_image_[a-zA-Z0-9_]+$")
    capabilities: list[str]
    max_concurrency: int = Field(ge=1, le=32)


class BindingCapacityInput(BaseModel):
    max_concurrency: int = Field(ge=1, le=32)


class StateInput(BaseModel):
    state: str
    reason: str = Field(default="", max_length=500)


class ReviewInput(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=500)

class CandidateFromImage(BaseModel):
    package_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,62}$")
    note: str = Field(default="", max_length=500)
    platform_type_id: str | None = None
    custom_platform_type: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,61}$")
    target_version: str | None = Field(default=None, max_length=64)
    source_catalog_id: str | None = Field(default=None, pattern=r"^catalog_[a-zA-Z0-9_]+$")


class CandidateCatalogInput(BaseModel):
    """Review-only fields; platform type and version are frozen on Candidate."""
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=120)
    approved: bool = False
    review_note: str = Field(default="", max_length=500)


class CandidateCatalogReleaseInput(BaseModel):
    """Create a new immutable release; never alter the prior Catalog."""
    model_config = ConfigDict(extra="forbid")
    release_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    review_note: str = Field(min_length=1, max_length=500)


# A release is only accepted when its HostAgent result proves the exact
# reviewed runner module.  Keep this list deliberately tiny and versioned.
S100_RUNNER_RELEASES = {
    "s100-runner-1.0.0": {
        "content_sha256": "332a1ed0d71f3a7d22914034d6d453e3ea259fbef3ebd5217a78541fff1a0e2d",
    },
}

@router.get("/api/admin/platform-types")
def platform_types(request: Request, authorization: str | None = Header(None)) -> list[dict]:
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        return [{"id": item.id, "name": item.name, "display_name": item.display_name}
                for item in session.scalars(select(PlatformType).order_by(PlatformType.name))]
    finally: session.close()


class HostImageVisibilityInput(BaseModel):
    hidden: bool

class CandidateEdit(BaseModel):
    note: str = Field(max_length=500)


class CandidateWorkspaceInput(BaseModel):
    """Platform rule facts; execution still renders them through a reviewed Runner."""
    display_name: str = Field(default="", max_length=120)
    archive_note: str = Field(default="", max_length=500)
    compile_command_template: str = Field(default="", max_length=500)
    board_command_template: str = Field(default="", max_length=500)

    @field_validator("compile_command_template", "board_command_template")
    @classmethod
    def fixed_command_template_only(cls, value: str, info):
        value = value.strip()
        if not value:
            return value
        if any(mark in value for mark in (";", "|", "&", "$", "`", "\n", "\r", "\\")):
            raise ValueError("command_template_shell_syntax_not_allowed")
        try:
            tokens = shlex.split(value)
        except ValueError as exc:
            raise ValueError("command_template_invalid") from exc
        if not tokens or "/" in tokens[0] or tokens[0].lower().startswith("docker"):
            raise ValueError("command_template_program_not_allowed")
        allowed = {"{model}", "{profile_dir}"}
        placeholders = set(re.findall(r"\{[^{}]+\}", value))
        if placeholders - allowed or ("{" in value and not placeholders):
            raise ValueError("command_template_placeholder_not_allowed")
        if "{model}" not in placeholders:
            raise ValueError("command_template_model_placeholder_required")
        if re.search(r"(?i)(password|secret|token|private[_-]?key)", value):
            raise ValueError("command_template_secret_not_allowed")
        return value


def default_candidate_workspace(note: str = "") -> dict:
    return {
        "display_name": "",
        "archive_note": note,
        "compile_command_template": "",
        "board_command_template": "",
        "policy": {
            "shell": "NOT_ACCEPTED", "docker_parameters": "NOT_ACCEPTED",
            "host_paths": "NOT_ACCEPTED", "credentials": "NOT_ACCEPTED",
        },
    }


def candidate_workspace(item: PlatformCandidate) -> dict:
    value = {**default_candidate_workspace(item.evidence.get("note", "")),
             **item.evidence.get("workspace", {})}
    # Old field-by-field declarations never become executable templates by
    # inference.  Their next edit records an explicit reviewed template.
    value.pop("compiler", None); value.pop("compiler_fast_perf", None)
    value.pop("compiler_march", None); value.pop("model_format", None)
    value.pop("board_tool", None); value.pop("board_mode", None)
    return value


def catalog_workspace_rules(catalog: PlatformCatalog) -> dict:
    """Return only the reviewed, declarative rules that may seed a new Candidate."""
    rules = catalog.runner.get("integration_rules", {})
    allowed = {key: rules[key] for key in CandidateWorkspaceInput.model_fields if key in rules}
    return {**default_candidate_workspace(), **allowed}


def candidate_real_validation(item: PlatformCandidate) -> dict:
    """The latest validation is valid only for the Candidate revision that launched it."""
    run = item.evidence.get("real_validation", {})
    return {**run, "current": bool(run and run.get("candidate_revision") == item.revision)}


def candidate_integration_test(item: PlatformCandidate) -> dict:
    """The offline contract result is also bound to the revision it checked."""
    run = item.evidence.get("integration_test", {})
    return {**run, "current": bool(run and run.get("candidate_revision") == item.revision)}

class CandidateAction(BaseModel):
    reason: str = Field(default="", max_length=500)


class CandidateForceAssignInput(BaseModel):
    """A controlled reassignment, never a transfer of an old workspace."""
    target_subject: str = Field(pattern=r"^[A-Za-z0-9._:@-]{1,128}$")
    reason: str = Field(min_length=1, max_length=500)

class CandidateReopenInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

class UserInput(BaseModel):
    subject: str = Field(pattern=r"^[A-Za-z0-9._:@-]{1,128}$")
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern=r"^(USER|ADMIN|SUPER_ADMIN)$")
    username: str | None = Field(default=None, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,63}$")
    password: str | None = Field(default=None, min_length=1, max_length=256)

class HandoverInput(BaseModel):
    successor_subject: str = Field(pattern=r"^[A-Za-z0-9._:@-]{1,128}$")
    reason: str = Field(min_length=1, max_length=500)


class PlatformMigrationExportInput(BaseModel):
    """Selection only; migration packages never contain runtime host facts."""
    catalog_ids: list[str] = Field(min_length=1, max_length=100)


MIGRATION_SCHEMA = "platform-migration-1.0"
MIGRATION_MAX_BYTES = 1024 * 1024


def _migration_catalog_key(item: dict) -> tuple[str, str]:
    platform_id = item.get("platform_type")
    version = item.get("version")
    if not isinstance(platform_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,61}", platform_id):
        raise HTTPException(422, {"code": "invalid_platform_migration_platform_type"})
    if not isinstance(version, str) or not version or len(version) > 64:
        raise HTTPException(422, {"code": "invalid_platform_migration_version"})
    return platform_id, version


def _validate_migration_catalog(item: object) -> dict:
    if not isinstance(item, dict):
        raise HTTPException(422, {"code": "invalid_platform_migration_catalog"})
    platform_id, version = _migration_catalog_key(item)
    required_dicts = ("package_manifest", "image_lock", "runner", "checks", "review")
    if item.get("schema_version") != MIGRATION_SCHEMA or not isinstance(item.get("display_name"), str):
        raise HTTPException(422, {"code": "invalid_platform_migration_catalog"})
    if not item["display_name"].strip() or len(item["display_name"]) > 120 or any(not isinstance(item.get(name), dict) for name in required_dicts):
        raise HTTPException(422, {"code": "invalid_platform_migration_catalog"})
    runner = item["runner"]
    if not isinstance(runner.get("version"), str) or not runner["version"].strip():
        raise HTTPException(422, {"code": "platform_migration_runner_missing"})
    # A migration archive records portable Catalog facts only. Refuse common
    # runtime/secret fields even if a hand-crafted zip tries to inject them.
    forbidden = {"token", "password", "secret", "ssh", "host", "worker", "board_address", "private_key"}
    def safe(value: object) -> bool:
        if isinstance(value, dict):
            return all(not any(word in str(key).lower() for word in forbidden) and safe(child) for key, child in value.items())
        if isinstance(value, list):
            return all(safe(child) for child in value)
        return True
    if not safe({name: item[name] for name in required_dicts}):
        raise HTTPException(422, {"code": "platform_migration_contains_runtime_or_secret"})
    return {"schema_version": MIGRATION_SCHEMA, "platform_type": platform_id, "version": version,
            "display_name": item["display_name"].strip(), "package_manifest": item["package_manifest"],
            "image_lock": item["image_lock"], "runner": runner, "checks": item["checks"],
            "review": item["review"], "source_catalog_id": item.get("source_catalog_id")}

# Candidate 是人工接入工作项，不是平台发布或 Worker 任务租约。认领没有自然到期：
# 只有认领管理员主动释放，或超级管理员带原因强制释放/指定，才会清理工作资料。

def principal_admin(request: Request, authorization: str | None):
    return admin(request, authorization)

def persist_principal(session, principal):
    user = session.get(UserAccount, principal.subject)
    if user is None or user.role != principal.role or not user.active:
        raise HTTPException(403, {"code": "persistent_role_mismatch"})

def candidate_claimed(item: PlatformCandidate) -> bool:
    """`claimed_by` is the sole authority for a human Candidate claim.

    `lease_expires_at` is retained only as a historical database column after
    M4-C-R3.  It must never influence authorization, Workbench state, or
    automatic cleanup.
    """
    return bool(item.claimed_by)


def _candidate_evidence_ids(item: PlatformCandidate) -> set[str]:
    """Collect only the temporary Evidence explicitly owned by a Candidate."""
    values = item.evidence or {}
    ids = {
        values.get("package", {}).get("evidence_id"),
        values.get("integration_test", {}).get("evidence_id"),
        values.get("real_validation", {}).get("evidence_id"),
    }
    ids.update(values.get("real_validation", {}).get("evidence_ids", []) or [])
    return {value for value in ids if isinstance(value, str)}


def _candidate_artifact_ids(item: PlatformCandidate) -> set[str]:
    values = item.evidence or {}
    ids = {
        values.get("package", {}).get("artifact_id"),
        values.get("integration_test", {}).get("artifact_id"),
        values.get("real_validation", {}).get("artifact_id"),
    }
    return {value for value in ids if isinstance(value, str)}


def clear_candidate_work_materials(session, storage, item: PlatformCandidate, *, actor, action: str, reason: str = "") -> dict:
    """Erase one abandoned integration attempt but retain a minimal audit fact.

    Catalog-linked Candidates are immutable historical provenance and never enter
    this path.  Candidate packages, offline checks, validation tasks and their
    Evidence are temporary work products; retaining them would let a later
    claimant accidentally continue somebody else's integration attempt.
    """
    from solution_advisor.artifacts.domain import Artifact, Evidence

    evidence_ids = _candidate_evidence_ids(item)
    artifact_ids = _candidate_artifact_ids(item)
    tasks = list(session.scalars(select(CandidateValidationTask).where(
        CandidateValidationTask.candidate_id == item.id
    )))
    for task in tasks:
        evidence_ids.update(value for value in (task.evidence_ids or []) if isinstance(value, str))
        session.delete(task)
    evidence_filter = []
    if evidence_ids:
        evidence_filter.append(Evidence.id.in_(evidence_ids))
    if artifact_ids:
        evidence_filter.append(Evidence.artifact_id.in_(artifact_ids))
    evidences = list(session.scalars(select(Evidence).where(or_(*evidence_filter)))) if evidence_filter else []
    artifact_ids.update(row.artifact_id for row in evidences if row.task_id is None)
    for row in evidences:
        # A task-bound Evidence can be a durable evaluation record. Candidate
        # validation Evidence is deliberately task-less, so never delete an
        # unrelated user-evaluation reference.
        if row.task_id is None:
            session.delete(row)
    session.flush()
    deleted_artifacts = 0
    for artifact_id in artifact_ids:
        if session.scalar(select(func.count()).select_from(Evidence).where(Evidence.artifact_id == artifact_id)):
            continue
        artifact = session.get(Artifact, artifact_id)
        if artifact:
            storage.delete(artifact.uri)
            session.delete(artifact)
            deleted_artifacts += 1
    item.evidence = {}
    item.state = "PENDING_INTEGRATION"
    summary = {"validation_tasks": len(tasks), "evidence": len(evidences), "artifacts": deleted_artifacts}
    # 调用方已在释放/超时前推进 revision；审计记录仍要能还原本次
    # 工作资料从哪个修订被清理，而不是错误地记录为同一修订。
    history(session, item, actor, action, max(0, item.revision - 1), reason or "已清理本次接入工作资料")
    session.add(PlatformAudit(action="CANDIDATE_WORK_MATERIALS_CLEARED", actor=actor.subject,
                result="SUCCEEDED", summary=f"{action} 后清理 Candidate 临时资料：任务 {summary['validation_tasks']}，Evidence {summary['evidence']}，制品 {summary['artifacts']}"))
    return summary


def seed_candidate_work_materials(session, storage, item: PlatformCandidate) -> None:
    """Create a clean package for a newly claimed Candidate attempt."""
    image = session.scalar(select(HostImage).where(HostImage.agent_id == item.agent_id,
                                                    HostImage.image_id == item.image_id))
    if image is None:
        image = HostImage(agent_id=item.agent_id, image_ref=item.image_ref, image_id=item.image_id,
                          toolchain_version=item.toolchain_version)
    platform_type = session.get(PlatformType, item.platform_type_id) if item.platform_type_id else None
    package_id = generated_candidate_package_id(platform_type, item.target_version or "1.0.0", image) if platform_type else item.id
    package = candidate_package(package_id=package_id, image=image, note="")
    artifact = ArtifactService(session, storage).put(candidate_package_bundle(package), content_type="application/zip")
    evidence = EvidenceService(session).record(evidence_type=EvidenceType.PLATFORM_INTEGRATION_PACKAGE.value,
        phase=EvidencePhase.INTEGRATION.value, artifact_id=artifact.id, platform=package_id,
        toolchain_version=item.toolchain_version, rule_package_version=package["version"])
    session.flush()
    item.evidence = {"package": {"id": package_id, "version": package["version"], "artifact_id": artifact.id,
        "evidence_id": evidence.id, "sha256": artifact.sha256, "image_lock_digest": item.image_id,
        "runner_id": "candidate-integration-runner-v1"}, "workspace": default_candidate_workspace()}


def history(session, item, actor, action: str, old: int, reason: str = ""):
    session.add(CandidateHistory(candidate_id=item.id, actor=actor.subject, action=action,
                old_revision=old, new_revision=item.revision, reason=reason or None))

def require_claim(item: PlatformCandidate, principal, if_match: str | None):
    if if_match is None or if_match != str(item.revision):
        raise HTTPException(409, {"code": "candidate_revision_conflict", "revision": item.revision,
                                  "claimed_by": item.claimed_by_name})
    if not candidate_claimed(item):
        raise HTTPException(409, {"code": "candidate_claim_required"})
    if item.claimed_by != principal.subject:
        raise HTTPException(423, {"code": "candidate_claim_forbidden", "claimed_by": item.claimed_by_name})


def candidate_payload(item: PlatformCandidate, principal=None) -> dict:
    package = item.evidence.get("package", {})
    test = candidate_integration_test(item)
    workspace = candidate_workspace(item)
    real_validation = candidate_real_validation(item)
    actions = []
    if principal:
        if item.archived_at:
            actions = ["restore"] if principal.role == SUPER_ADMIN else []
        elif not candidate_claimed(item):
            actions = ["claim"] + (["archive"] if principal.role == SUPER_ADMIN else [])
        elif item.claimed_by == principal.subject:
            actions = ["release", "edit", "test", "advance", "archive"]
        elif principal.role == SUPER_ADMIN:
            actions = ["force_release", "force_assign", "archive"]
    return {"id": item.id, "agent_id": item.agent_id, "image_ref": item.image_ref,
            "image_id": item.image_id, "toolchain_version": item.toolchain_version,
            "platform_type_id": item.platform_type_id, "target_version": item.target_version,
            "state": item.state, "catalog_id": item.catalog_id, "created_by": item.created_by,
            "claimed_by": item.claimed_by, "claimed_by_name": item.claimed_by_name,
            "claimed_at": item.claimed_at.isoformat() if item.claimed_at else None,
            "claim_state": "CLAIMED" if candidate_claimed(item) else "UNCLAIMED",
            "last_handled_by": item.last_handled_by,
            "last_handled_at": item.last_handled_at.isoformat() if item.last_handled_at else None,
            "revision": item.revision, "archived_at": item.archived_at.isoformat() if item.archived_at else None,
            "archived_by": item.archived_by, "archive_reason": item.archive_reason,
            "package": package, "integration_test": test, "workspace": workspace,
            "rule_copy": item.evidence.get("rule_copy", {}),
            "real_validation": real_validation,
            "review_ready": bool(package.get("artifact_id") and test.get("passed") and test.get("current")
                                 and real_validation.get("current")
                                 and real_validation.get("status") == "SUCCEEDED"),
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "actions": actions}


def validation_payload(item: CandidateValidationTask) -> dict:
    return {"id": item.id, "candidate_id": item.candidate_id, "candidate_revision": item.candidate_revision,
            "agent_id": item.agent_id, "status": item.status, "runner_release": item.runner_release,
            "worker_instance_id": item.worker_instance_id, "error_code": item.error_code,
            "result": item.result, "evidence_ids": item.evidence_ids,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "started_at": item.started_at.isoformat() if item.started_at else None,
            "finished_at": item.finished_at.isoformat() if item.finished_at else None}


def candidate_package(*, package_id: str, image: HostImage, note: str) -> dict:
    """A deterministic review artifact.  It contains no runnable command or host path."""
    return {"schema_version": "platform-candidate-package-v1", "id": package_id,
            "version": "0.1.0-candidate", "state": "PENDING_INTEGRATION",
            "image_lock": {"image": image.image_ref, "digest": image.image_id},
            "runner": {"id": "candidate-integration-runner-v1", "mode": "offline-contract-only"},
            "checks": ["manifest", "immutable_image_digest", "offline_runner_contract"],
            "boundaries": {"shell": "NOT_ACCEPTED", "docker_parameters": "NOT_ACCEPTED",
                           "host_paths": "NOT_ACCEPTED", "credentials": "NOT_ACCEPTED",
                           "board_access": "NOT_EXECUTED", "compilation": "NOT_EXECUTED"},
            "note": note}


def generated_candidate_package_id(platform_type: PlatformType, target_version: str, image: HostImage) -> str:
    """Create a readable, valid Package ID without asking operators to name an internal artifact."""
    def segment(value: str, limit: int) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-_")
        return normalized[:limit].strip("-_") or "platform"

    digest = segment((image.image_id or image.id).removeprefix("sha256:"), 12)
    return f"{segment(platform_type.name, 24)}-{segment(target_version, 20)}-{digest}"[:63].rstrip("-_")


def candidate_package_bundle(package: dict) -> bytes:
    """Create a reproducible, reviewable package without writing any Host path."""
    files = {
        "manifest.json": json.dumps(package, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "image.lock.json": json.dumps(package["image_lock"], ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        "runner.json": json.dumps({"module": "platform_runner", "version": "0.1.0",
                                    "entrypoint": "execute", "policy": "fixed"}, sort_keys=True, indent=2) + "\n",
        "tests/offline-contract.json": json.dumps({"package_id": package["id"], "expected_digest": package["image_lock"]["digest"],
                                                     "runner": "candidate-integration-runner-v1"}, sort_keys=True, indent=2) + "\n",
        "README.md": "# 候选 Platform Package\n\n仅用于受控接入测试；不包含 Shell、Docker 参数、路径、凭据或板卡操作。\n",
    }
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in files.items():
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, content.encode())
    return stream.getvalue()


@router.get("/api/admin/platform-catalogs")
def catalogs(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        registry = PlatformRegistry(session)
        values = []
        for item in session.scalars(select(PlatformCatalog).order_by(PlatformCatalog.platform_id, PlatformCatalog.created_at.desc())):
            # Every immutable Release is evaluated against its own Binding;
            # a newer Release must never make a retired one look schedulable.
            _, _, _, reason = registry.availability(item.platform_id, item.id)
            values.append(catalog_payload(item, schedulable=reason == "READY", reason=reason))
        return values
    finally: session.close()


def migration_catalog_payload(item: PlatformCatalog) -> dict:
    """Portable, reviewable Catalog facts, deliberately excluding deployment secrets.

    A target deployment must still install its reviewed Runner and create a
    local Binding/Worker.  This package records the compatible platform
    capability; it cannot smuggle a Host, token, board connection, or evidence
    artifact into another environment.
    """
    # Do not copy a historical JSON blob and then try to blacklist deployment
    # keys. Older Catalogs legitimately retain provenance and policy
    # declarations (for example ``host_paths: NOT_ACCEPTED``). Those are not
    # Host configuration, but a broad blacklist would mistake them for it.
    # The backup format therefore has an explicit small allowlist: only facts
    # needed to recreate a Catalog, never Host/Binding/Worker runtime state.
    package_source = item.package_manifest or {}
    package = {key: package_source[key] for key in ("id", "version", "sha256", "capabilities")
               if key in package_source}
    image_source = item.image_lock or {}
    image_lock = {key: image_source[key] for key in ("image", "digest", "reference")
                  if key in image_source}
    runner_source = item.runner or {}
    runner = {key: runner_source[key] for key in ("module", "version", "content_sha256", "entrypoint")
              if key in runner_source}
    rules = runner_source.get("integration_rules")
    if isinstance(rules, dict):
        runner["integration_rules"] = {
            key: rules[key]
            for key in ("display_name", "archive_note", "compile_command_template", "board_command_template")
            if key in rules
        }
    checks_source = item.checks or {}
    checks = {key: checks_source[key] for key in ("self_check", "offline_test", "compile", "board")
              if key in checks_source}
    return {"schema_version": "platform-migration-1.0", "platform_type": item.platform_id,
            "version": item.version, "display_name": item.display_name, "state": item.state,
            "package_manifest": package, "image_lock": image_lock, "runner": runner,
            "checks": checks, "review": {"approved": bool((item.review or {}).get("approved")),
                                             "note": (item.review or {}).get("note", "")},
            "source_catalog_id": item.id}


@router.post("/api/admin/platform-migrations/export")
def export_platform_migration(body: PlatformMigrationExportInput, request: Request,
                              authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization)
    session = request.app.state.session_factory()
    try:
        catalog_ids = list(dict.fromkeys(body.catalog_ids))
        catalogs = [session.get(PlatformCatalog, catalog_id) for catalog_id in catalog_ids]
        if any(item is None for item in catalogs):
            raise HTTPException(404, {"code": "platform_catalog_not_found"})
        selected = [item for item in catalogs if item is not None]
        if any(item.state != "AVAILABLE" for item in selected):
            raise HTTPException(422, {"code": "only_available_catalogs_exportable"})
        portable_catalogs = [migration_catalog_payload(item) for item in selected]
        # Export follows the same boundary as import.  A malformed historical
        # Catalog must be corrected at the source, never copied into a ZIP
        # where a secret or deployment-specific field could spread.
        portable_catalogs = [_validate_migration_catalog(item) for item in portable_catalogs]
        payload = {"schema_version": "platform-migration-1.0", "exported_by": principal.subject,
                   "catalogs": portable_catalogs,
                   "boundary": {"includes": ["已发布 Catalog", "平台类型/版本", "镜像兼容约束", "固定 Runner 规则", "审核摘要"],
                                "excludes": ["HostAgent", "Binding", "Worker", "用户模型与评测", "Artifact/Evidence 二进制", "Token/SSH/板端资料"]}}
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
        stream = BytesIO()
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            info = ZipInfo("platform-migration.json", date_time=(2020, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
            readme = "# 平台配置备份包\n\n本包只保存已发布平台的受控能力定义。目标 Host 仍需安装匹配的固定 Runner，并根据本机发现的镜像建立健康 Binding 与 READY Worker。\n"
            info = ZipInfo("README.md", date_time=(2020, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED
            archive.writestr(info, readme.encode())
        session.add(PlatformAudit(action="PLATFORM_CONFIGURATION_EXPORTED", actor=principal.subject,
                                  summary=f"备份 {len(selected)} 个已发布平台的 Catalog 定义"))
        session.commit()
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/zip", headers={"Content-Disposition": "attachment; filename=solution-advisor-platform-migration.zip"})
    finally:
        session.close()


@router.post("/api/admin/platform-migrations/import")
async def import_platform_migration(request: Request, archive: UploadFile = File(...),
                                    authorization: str | None = Header(None)) -> dict:
    """Import portable Catalog definitions, never source runtime resources.

    Imported Catalogs are marked AVAILABLE for review provenance, but have no
    Binding or Worker.  The normal availability gate therefore keeps them out
    of user selection until the target Host proves its local runner/image.
    """
    principal = principal_admin(request, authorization)
    raw = await archive.read(MIGRATION_MAX_BYTES + 1)
    if len(raw) > MIGRATION_MAX_BYTES:
        raise HTTPException(413, {"code": "platform_migration_too_large"})
    try:
        with ZipFile(BytesIO(raw)) as bundle:
            names = set(bundle.namelist())
            if "platform-migration.json" not in names or not names.issubset({"platform-migration.json", "README.md"}):
                raise HTTPException(422, {"code": "invalid_platform_migration_archive"})
            info = bundle.getinfo("platform-migration.json")
            if info.file_size > MIGRATION_MAX_BYTES:
                raise HTTPException(413, {"code": "platform_migration_too_large"})
            payload = json.loads(bundle.read("platform-migration.json").decode("utf-8"))
    except (BadZipFile, UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(422, {"code": "invalid_platform_migration_archive"})
    if not isinstance(payload, dict) or payload.get("schema_version") != MIGRATION_SCHEMA or not isinstance(payload.get("catalogs"), list):
        raise HTTPException(422, {"code": "invalid_platform_migration_archive"})
    if not payload["catalogs"] or len(payload["catalogs"]) > 100:
        raise HTTPException(422, {"code": "invalid_platform_migration_catalog_count"})
    catalogs = [_validate_migration_catalog(item) for item in payload["catalogs"]]
    keys = [_migration_catalog_key(item) for item in catalogs]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, {"code": "duplicate_platform_migration_catalog"})

    session = request.app.state.session_factory()
    imported: list[str] = []
    skipped: list[str] = []
    try:
        for item in catalogs:
            existing = session.scalar(select(PlatformCatalog).where(
                PlatformCatalog.platform_id == item["platform_type"], PlatformCatalog.version == item["version"],
            ))
            if existing:
                comparable = migration_catalog_payload(existing)
                for key in ("display_name", "package_manifest", "image_lock", "runner", "checks"):
                    if comparable.get(key) != item.get(key):
                        raise HTTPException(409, {"code": "platform_migration_catalog_conflict", "platform": item["platform_type"], "version": item["version"]})
                skipped.append(existing.id)
                continue
            platform_type = session.scalar(select(PlatformType).where(PlatformType.name == item["platform_type"]))
            if platform_type is None:
                platform_type = PlatformType(name=item["platform_type"], display_name=item["platform_type"], created_by=principal.subject)
                session.add(platform_type)
                session.flush()
            catalog = PlatformCatalog(
                platform_type_id=platform_type.id, platform_id=item["platform_type"], version=item["version"],
                display_name=item["display_name"], state="AVAILABLE", package_manifest=item["package_manifest"],
                image_lock=item["image_lock"], runner=item["runner"], checks=item["checks"],
                review={**item["review"], "migration": {"schema": MIGRATION_SCHEMA, "source_catalog_id": item.get("source_catalog_id"), "imported_by": principal.subject}},
                created_by=principal.subject, published_at=utcnow(),
            )
            session.add(catalog); session.flush(); imported.append(catalog.id)
        session.add(PlatformAudit(action="PLATFORM_CONFIGURATION_IMPORTED", actor=principal.subject, result="SUCCEEDED",
                                  summary=f"恢复 {len(imported)} 个平台能力定义；跳过 {len(skipped)} 个相同 Catalog"))
        session.commit()
        return {"imported_catalog_ids": imported, "skipped_catalog_ids": skipped,
                "message": "平台配置已恢复；请在目标 Host 安装匹配 Runner 并建立健康 Binding/READY Worker 后再供用户评估。"}
    finally:
        session.close()


@router.post("/api/admin/platform-catalogs", status_code=201)
def create_catalog(body: CatalogInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).create_catalog(**body.model_dump())
        except PlatformError as exc: problem(exc)
        return catalog_payload(item)
    finally: session.close()


@router.post("/api/admin/platform-catalogs/{catalog_id}/publish")
def publish_catalog(catalog_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).publish(catalog_id)
        except PlatformError as exc: problem(exc)
        return catalog_payload(item)
    finally: session.close()


@router.post("/api/admin/platform-catalogs/{catalog_id}/review")
def review_catalog(catalog_id: str, body: ReviewInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).review_catalog(catalog_id, **body.model_dump())
        except PlatformError as exc: problem(exc)
        return catalog_payload(item)
    finally: session.close()


@router.post("/api/admin/platform-catalogs/{catalog_id}/suspend")
def suspend_catalog(catalog_id: str, body: StateInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).suspend(catalog_id, body.reason)
        except PlatformError as exc: problem(exc)
        return catalog_payload(item)
    finally: session.close()


@router.post("/api/admin/platform-catalogs/{catalog_id}/state")
def catalog_state(catalog_id: str, body: StateInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).set_catalog_state(catalog_id, body.state, body.reason)
        except PlatformError as exc: problem(exc)
        return catalog_payload(item)
    finally: session.close()


@router.get("/api/admin/platform-candidates")
def candidates(request: Request, include_hidden: bool = False, include_archived: bool = False, authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        result = []
        for item in session.scalars(select(PlatformCandidate).order_by(PlatformCandidate.created_at.desc())):
            if item.archived_at and not include_archived:
                continue
            image = session.scalar(select(HostImage).where(HostImage.agent_id == item.agent_id,
                                                           HostImage.image_id == item.image_id))
            if image and image.hidden and not include_hidden:
                continue
            payload = candidate_payload(item, principal)
            payload["hidden"] = bool(image and image.hidden)
            payload["host_image_id"] = image.id if image else None
            result.append(payload)
        return result
    finally: session.close()


@router.get("/api/admin/host-images")
def host_images(request: Request, include_hidden: bool = False, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        catalogs = list(session.scalars(select(PlatformCatalog)))
        candidates = list(session.scalars(select(PlatformCandidate).where(PlatformCandidate.catalog_id.is_(None), PlatformCandidate.archived_at.is_(None))))
        bindings = list(session.scalars(select(PlatformBinding)))
        result=[]
        for image in session.scalars(select(HostImage).order_by(HostImage.agent_id, HostImage.image_ref)):
            if is_governance_service_image(image.image_ref):
                continue
            if image.hidden and not include_hidden:
                continue
            binding = next((x for x in bindings if x.agent_id == image.agent_id and (x.actual_image_digest or x.image_lock_version) == image.image_id), None)
            catalog = session.get(PlatformCatalog, binding.catalog_id) if binding else next((x for x in catalogs if x.image_lock.get("digest") == image.image_id), None)
            candidate = next((x for x in candidates if x.agent_id == image.agent_id and x.image_id == image.image_id), None)
            if candidate and candidate.catalog_id:
                catalog = session.get(PlatformCatalog, candidate.catalog_id) or catalog
            # A Candidate linked to an AVAILABLE Catalog is historical audit
            # context, not an active integration.  Only an unlinked Candidate
            # may occupy the integrating region.
            state = "MANAGED" if catalog and catalog.state == "AVAILABLE" else "INTEGRATING" if (candidate or catalog) else "DISCOVERED"
            result.append({"id":image.id,"agent_id":image.agent_id,"image_ref":image.image_ref,"image_id":image.image_id,"toolchain_version":image.toolchain_version,"state":state,"catalog_id":catalog.id if catalog else None,"candidate_id":candidate.id if candidate else None,"hidden":image.hidden,"hidden_by":image.hidden_by,"hidden_at":image.hidden_at.isoformat() if image.hidden_at else None})
        return result
    finally: session.close()


@router.post("/api/admin/host-images/{image_id}/visibility")
def set_host_image_visibility(image_id: str, body: HostImageVisibilityInput, request: Request,
                              authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        image = session.get(HostImage, image_id)
        if not image: raise HTTPException(404, {"code": "host_image_not_found"})
        if is_governance_service_image(image.image_ref):
            raise HTTPException(422, {"code": "governance_service_image_not_manageable"})
        image.hidden, image.hidden_by, image.hidden_at = body.hidden, (principal.subject if body.hidden else None), (utcnow() if body.hidden else None)
        session.add(PlatformAudit(action="HOST_IMAGE_HIDDEN" if body.hidden else "HOST_IMAGE_UNHIDDEN", actor=principal.subject,
                    summary="管理员更新全局镜像可见性"))
        session.commit()
        return {"id": image.id, "hidden": image.hidden, "hidden_by": image.hidden_by,
                "hidden_at": image.hidden_at.isoformat() if image.hidden_at else None}
    finally: session.close()

@router.get("/api/admin/platform-workbench")
def platform_workbench(request: Request, include_hidden: bool = False, include_archived: bool = False, authorization: str | None = Header(None)):
    """Authoritative mutually-exclusive image state for the platform workbench."""
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        persist_principal(session, principal)
        catalogs = list(session.scalars(select(PlatformCatalog)))
        active_candidates = {(x.agent_id, x.image_id): x for x in session.scalars(select(PlatformCandidate).where(PlatformCandidate.catalog_id.is_(None), PlatformCandidate.archived_at.is_(None)))}
        historical_candidates = {(x.agent_id, x.image_id): x for x in session.scalars(select(PlatformCandidate).where(PlatformCandidate.catalog_id.is_not(None), PlatformCandidate.archived_at.is_(None)))}
        archived_candidates = list(session.scalars(select(PlatformCandidate).where(PlatformCandidate.archived_at.is_not(None)))) if include_archived else []
        bindings = list(session.scalars(select(PlatformBinding)))
        workers = list(session.scalars(select(PlatformWorker)))
        items = []
        for image in session.scalars(select(HostImage).order_by(HostImage.agent_id, HostImage.image_ref)):
            if is_governance_service_image(image.image_ref) or (image.hidden and not include_hidden): continue
            binding_for_image = next((x for x in bindings if x.agent_id == image.agent_id and (x.actual_image_digest or x.image_lock_version) == image.image_id), None)
            catalog = session.get(PlatformCatalog, binding_for_image.catalog_id) if binding_for_image else next((x for x in catalogs if x.image_lock.get("digest") == image.image_id), None)
            candidate = active_candidates.get((image.agent_id, image.image_id))
            historical_candidate = historical_candidates.get((image.agent_id, image.image_id))
            if candidate and candidate.catalog_id:
                catalog = session.get(PlatformCatalog, candidate.catalog_id) or catalog
            # Archiving hides the historical Candidate by default, rather than
            # hiding the HostImage itself.  The image must return to
            # DISCOVERED so an administrator can create a new active
            # Candidate for the same (agent_id, image_digest).
            # Catalog publication wins over its source Candidate for the
            # three-state workbench.  This preserves Candidate history while
            # ensuring one Host image appears in exactly one visual region.
            state = "MANAGED" if catalog and catalog.state == "AVAILABLE" else "INTEGRATING" if (candidate or catalog) else "DISCOVERED"
            related = [x for x in bindings if catalog and x.catalog_id == catalog.id and x.agent_id == image.agent_id]
            related_workers = [worker_payload(session, w) for w in workers if any(w.binding_id == b.id for b in related)]
            items.append({"image_key": f"{image.agent_id}:{image.image_id}", "state": state,
                "host_image": {"id": image.id, "agent_id": image.agent_id, "image_ref": image.image_ref,
                               "image_id": image.image_id, "toolchain_version": image.toolchain_version,
                               "hidden": image.hidden, "hidden_by": image.hidden_by},
                # Keep prior Candidate provenance inspectable in the managed
                # card without letting it occupy the active integration slot.
                "candidate": candidate_payload(candidate or historical_candidate, principal) if (candidate or historical_candidate) else None,
                "catalog": catalog_payload(catalog) if catalog else None,
                "bindings": [binding_payload(session, x) for x in related], "workers": related_workers,
                "actions": ([] if state == "MANAGED" else (candidate_payload(candidate, principal)["actions"] if candidate else ["create_candidate", "hide"]))})
        for candidate in archived_candidates:
            image = session.scalar(select(HostImage).where(HostImage.agent_id == candidate.agent_id, HostImage.image_id == candidate.image_id))
            if image and image.hidden and not include_hidden:
                continue
            items.append({"image_key": f"archived:{candidate.id}", "state": "ARCHIVED",
                "host_image": {"id": image.id if image else None, "agent_id": candidate.agent_id, "image_ref": candidate.image_ref,
                               "image_id": candidate.image_id, "toolchain_version": candidate.toolchain_version,
                               "hidden": bool(image and image.hidden), "hidden_by": image.hidden_by if image else None},
                "candidate": candidate_payload(candidate, principal), "catalog": None, "bindings": [], "workers": [],
                "actions": candidate_payload(candidate, principal)["actions"]})
        assignable_admins = []
        if principal.role == SUPER_ADMIN:
            assignable_admins = [{"subject": user.id, "display_name": user.display_name}
                                 for user in session.scalars(select(UserAccount).where(
                                     UserAccount.role == ADMIN, UserAccount.active.is_(True),
                                     UserAccount.status == "ACTIVE").order_by(UserAccount.display_name))]
        return {"principal": {"subject": principal.subject, "display_name": principal.display_name, "role": principal.role},
                "assignable_admins": assignable_admins, "items": items}
    finally: session.close()


@router.post("/api/admin/host-images/{image_id}/platform-candidates", status_code=201)
def candidate_from_image(image_id: str, body: CandidateFromImage, request: Request, authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        persist_principal(session, principal)
        image=session.get(HostImage,image_id)
        if not image: raise HTTPException(404,{"code":"host_image_not_found"})
        # A Catalog-linked Candidate is immutable historical provenance, not
        # an active integration slot.  A successor Release must be able to
        # revalidate the same Host image without altering that history.
        if session.scalar(select(PlatformCandidate).where(PlatformCandidate.agent_id==image.agent_id, PlatformCandidate.image_id==image.image_id,
                                                           PlatformCandidate.catalog_id.is_(None), PlatformCandidate.archived_at.is_(None))):
            raise HTTPException(409,{"code":"platform_candidate_exists"})
        platform_type = session.get(PlatformType, body.platform_type_id) if body.platform_type_id else None
        if body.custom_platform_type:
            platform_type = session.scalar(select(PlatformType).where(PlatformType.name == body.custom_platform_type))
            if platform_type is None:
                platform_type = PlatformType(name=body.custom_platform_type, display_name=body.custom_platform_type, created_by=principal.subject)
                session.add(platform_type); session.flush()
        # Compatibility for pre-versioned API clients; the management UI always
        # sends an explicit selection or custom type and version.
        if platform_type is None:
            if not body.package_id:
                raise HTTPException(422,{"code":"platform_type_required"})
            platform_type = PlatformType(name=body.package_id, display_name=body.package_id, created_by=principal.subject)
            session.add(platform_type); session.flush()
        target_version = body.target_version or "1.0.0"
        copied_workspace = default_candidate_workspace(body.note)
        rule_copy = {}
        if body.source_catalog_id:
            source_catalog = session.get(PlatformCatalog, body.source_catalog_id)
            if not source_catalog or source_catalog.state != "AVAILABLE":
                raise HTTPException(422, {"code": "available_source_catalog_required"})
            if source_catalog.platform_type_id != platform_type.id:
                raise HTTPException(422, {"code": "source_catalog_platform_type_mismatch"})
            copied_workspace = catalog_workspace_rules(source_catalog)
            copied_workspace["archive_note"] = body.note or copied_workspace.get("archive_note", "")
            rule_copy = {"source_catalog_id": source_catalog.id, "source_platform_version": source_catalog.version,
                         "copied": bool(source_catalog.runner.get("integration_rules")),
                         "message": "已复制已审核的结构化接入规则，可在步骤 1 修改后重新验证。"}
        package_id = body.package_id or generated_candidate_package_id(platform_type, target_version, image)
        package = candidate_package(package_id=package_id, image=image, note=body.note)
        artifact = ArtifactService(session, request.app.state.artifact_storage).put(
            candidate_package_bundle(package), content_type="application/zip")
        evidence = EvidenceService(session).record(evidence_type=EvidenceType.PLATFORM_INTEGRATION_PACKAGE.value,
            phase=EvidencePhase.INTEGRATION.value, artifact_id=artifact.id, platform=package_id,
            toolchain_version=image.toolchain_version, rule_package_version=package["version"])
        session.flush()
        candidate=PlatformCandidate(agent_id=image.agent_id,image_ref=image.image_ref,image_id=image.image_id,
            platform_type_id=platform_type.id, target_version=target_version,
            toolchain_version=image.toolchain_version,state="PENDING_INTEGRATION", created_by=principal.subject,
            claimed_by=None, claimed_by_name=None, claimed_at=None, lease_expires_at=None,
            last_handled_by=principal.subject, last_handled_at=utcnow(), revision=1,
            evidence={"package":{"id":package_id,"version":package["version"],"artifact_id":artifact.id,
                      "evidence_id":evidence.id,"sha256":artifact.sha256,"image_lock_digest":image.image_id,
                      "runner_id":"candidate-integration-runner-v1"},"note":body.note,
                      "workspace": copied_workspace, "rule_copy": rule_copy})
        session.add(candidate); session.flush(); history(session, candidate, principal, "CANDIDATE_CREATED", 0)
        summary = "管理员创建未认领的可审查候选 Package"
        if rule_copy: summary += f"；复制 Catalog {rule_copy['source_catalog_id']} 的规则草稿"
        session.add(PlatformAudit(action="CANDIDATE_CREATED_FROM_IMAGE",actor=principal.subject,summary=summary)); session.commit()
        return candidate_payload(candidate, principal)
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, {"code": "platform_candidate_exists"})
    finally: session.close()

@router.post("/api/admin/platform-candidates/{candidate_id}/claim")
def claim_candidate(candidate_id: str, request: Request, authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        persist_principal(session, principal); item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        if item.archived_at: raise HTTPException(409, {"code": "candidate_archived"})
        if item.catalog_id and not item.evidence.get("workspace_reopened"):
            raise HTTPException(409, {"code": "candidate_catalog_linked"})
        if item.claimed_by == principal.subject:
            return candidate_payload(item, principal)
        now = utcnow()
        claimed = session.execute(update(PlatformCandidate).where(
            PlatformCandidate.id == candidate_id,
            PlatformCandidate.claimed_by.is_(None),
        ).values(claimed_by=principal.subject, claimed_by_name=principal.display_name,
                 claimed_at=now, lease_expires_at=None,
                 last_handled_by=principal.subject, last_handled_at=now,
                 revision=PlatformCandidate.revision + 1))
        if claimed.rowcount != 1:
            session.rollback(); item = session.get(PlatformCandidate, candidate_id)
            raise HTTPException(423, {"code": "candidate_claimed_by_other", "claimed_by": item.claimed_by_name if item else None})
        session.expire_all(); item = session.get(PlatformCandidate, candidate_id); old = item.revision - 1
        if not item.evidence.get("package"):
            seed_candidate_work_materials(session, request.app.state.artifact_storage, item)
        history(session, item, principal, "CANDIDATE_CLAIMED", old); session.commit()
        return candidate_payload(item, principal)
    finally: session.close()

@router.post("/api/admin/platform-candidates/{candidate_id}/release")
def release_candidate(candidate_id: str, body: CandidateAction, request: Request, if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        item.claimed_by=item.claimed_by_name=item.claimed_at=item.lease_expires_at=None; item.last_handled_by, item.last_handled_at, item.revision=principal.subject, utcnow(), old+1
        clear_candidate_work_materials(session, request.app.state.artifact_storage, item, actor=principal,
                                       action="CANDIDATE_RELEASED", reason=body.reason)
        session.add(PlatformAudit(action="CANDIDATE_RELEASED", actor=principal.subject, result="SUCCEEDED",
                    summary="管理员主动释放 Candidate，已清理本次接入工作资料"))
        session.commit(); return candidate_payload(item,principal)
    finally: session.close()

@router.post("/api/admin/platform-candidates/{candidate_id}/takeover")
def takeover_candidate(candidate_id: str, body: CandidateAction, request: Request, if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    # Deliberately retained as a stable rejection for older clients.  A
    # super administrator can only force-release; work is never transferred.
    principal_admin(request, authorization)
    raise HTTPException(410, {"code": "candidate_takeover_removed"})


@router.post("/api/admin/platform-candidates/{candidate_id}/force-release")
def force_release_candidate(candidate_id: str, body: CandidateAction, request: Request,
                            if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        if principal.role != SUPER_ADMIN: raise HTTPException(403, {"code": "super_admin_required"})
        if not body.reason: raise HTTPException(422, {"code": "force_release_reason_required"})
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        if if_match != str(item.revision): raise HTTPException(409, {"code": "candidate_revision_conflict", "revision": item.revision})
        old = item.revision; item.claimed_by = item.claimed_by_name = item.claimed_at = item.lease_expires_at = None
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        clear_candidate_work_materials(session, request.app.state.artifact_storage, item, actor=principal,
                                       action="CANDIDATE_FORCE_RELEASED", reason=body.reason)
        session.add(PlatformAudit(action="CANDIDATE_FORCE_RELEASED", actor=principal.subject, result="SUCCEEDED",
                    summary="超级管理员强制释放 Candidate，未转交任何进行中资料"))
        session.commit()
        return candidate_payload(item, principal)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/force-assign")
def force_assign_candidate(candidate_id: str, body: CandidateForceAssignInput, request: Request,
                           if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Clear the old attempt and atomically give a clean Candidate to an active admin."""
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        if principal.role != SUPER_ADMIN:
            raise HTTPException(403, {"code": "super_admin_required"})
        item = session.get(PlatformCandidate, candidate_id)
        if not item:
            raise HTTPException(404, {"code": "candidate_not_found"})
        if item.archived_at or item.catalog_id:
            raise HTTPException(409, {"code": "candidate_not_assignable"})
        if not candidate_claimed(item):
            raise HTTPException(409, {"code": "candidate_claim_required"})
        if if_match != str(item.revision):
            raise HTTPException(409, {"code": "candidate_revision_conflict", "revision": item.revision,
                                      "claimed_by": item.claimed_by_name})
        target = session.get(UserAccount, body.target_subject)
        if target is None or target.role != ADMIN or not target.active or target.status != "ACTIVE":
            raise HTTPException(422, {"code": "candidate_assign_target_must_be_active_admin"})
        old_owner = item.claimed_by or "未认领"
        old = item.revision
        # Clearing first is intentional.  The new owner can never inherit a
        # package, validation, evidence, or temporary artifact from the old one.
        item.claimed_by = item.claimed_by_name = item.claimed_at = item.lease_expires_at = None
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        summary = clear_candidate_work_materials(session, request.app.state.artifact_storage, item, actor=principal,
                                                 action="CANDIDATE_FORCE_ASSIGNED_CLEARED", reason=body.reason)
        clear_revision = item.revision
        item.claimed_by, item.claimed_by_name, item.claimed_at = target.id, target.display_name, utcnow()
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), clear_revision + 1
        seed_candidate_work_materials(session, request.app.state.artifact_storage, item)
        history(session, item, principal, "CANDIDATE_FORCE_ASSIGNED", clear_revision,
                f"原认领人 {old_owner} 的资料已清理；指定 {target.id}：{body.reason}")
        session.add(PlatformAudit(action="CANDIDATE_FORCE_ASSIGNED", actor=principal.subject, result="SUCCEEDED",
                    summary=f"清理原认领人 {old_owner} 的资料后指定 {target.id}；清理摘要 {summary}"))
        session.commit()
        return candidate_payload(item, principal)
    finally:
        session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/reopen-workspace")
def reopen_candidate_workspace(candidate_id: str, body: CandidateReopenInput, request: Request,
                               if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Stable rejection: published Candidate work cannot be reopened or transferred."""
    principal_admin(request, authorization)
    raise HTTPException(410, {"code": "candidate_workspace_reopen_removed"})


@router.patch("/api/admin/platform-candidates/{candidate_id}")
def edit_candidate(candidate_id: str, body: CandidateEdit, request: Request,
                   if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        item.evidence = {**item.evidence, "note": body.note}
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        history(session, item, principal, "CANDIDATE_EDITED", old); session.commit()
        return candidate_payload(item, principal)
    finally: session.close()


@router.get("/api/admin/platform-candidates/{candidate_id}/workspace")
def get_candidate_workspace(candidate_id: str, request: Request, authorization: str | None = Header(None)):
    """Expose the persisted Candidate package structure, never a Host filesystem."""
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        package = item.evidence.get("package", {})
        files = [{"path": "manifest.json", "purpose": "immutable image and package declaration"},
                 {"path": "runner.json", "purpose": "fixed runner contract"}]
        return {"candidate": candidate_payload(item, principal), "workspace": candidate_workspace(item),
                "package_files": files, "validation": candidate_real_validation(item),
                "steps": ["配置接入资料", "离线契约检查", "真实接入验证", "生成待审核 Catalog", "审核发布与 Binding"]}
    finally: session.close()


@router.put("/api/admin/platform-candidates/{candidate_id}/workspace")
def update_candidate_workspace(candidate_id: str, body: CandidateWorkspaceInput, request: Request,
                               if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        workspace = {**default_candidate_workspace(), **body.model_dump()}
        # Configurations are declarative preset identifiers.  Commands, Docker flags,
        # paths and credentials deliberately have no API representation.
        item.evidence = {**item.evidence, "workspace": workspace}
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        history(session, item, principal, "CANDIDATE_WORKSPACE_UPDATED", old)
        session.add(PlatformAudit(action="CANDIDATE_WORKSPACE_UPDATED", actor=principal.subject,
                    summary="更新 Candidate 受控资料与预设；旧真实验证不再适用于新修订"))
        session.commit(); return candidate_payload(item, principal)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/real-validation-runs")
def run_candidate_real_validation(candidate_id: str, request: Request,
                                  if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Queue a current-revision validation; only the installed HostAgent can execute it."""
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match)
        workspace = candidate_workspace(item)
        integration_test = candidate_integration_test(item)
        if not (integration_test.get("passed") and integration_test.get("current")):
            raise HTTPException(422, {"code": "candidate_current_integration_required"})
        platform_type = session.get(PlatformType, item.platform_type_id) if item.platform_type_id else None
        # `3.7.0-r1` is an immutable Runner release of the verified 3.7.0
        # platform line, so it uses the same reviewed S100 validation Agent.
        if not platform_type or platform_type.name.upper() != "S100" or not str(item.target_version or "").startswith("3.7.0"):
            result = {"kind": "REAL_INTEGRATION", "status": "BLOCKED", "progress_percent": 0,
                      "candidate_revision": item.revision, "runner_id": "NOT_INSTALLED",
                      "reason_code": "real_validation_runner_not_installed"}
            artifact = ArtifactService(session, request.app.state.artifact_storage).put(json.dumps(result, sort_keys=True).encode(), content_type="application/json")
            evidence = EvidenceService(session).record(evidence_type=EvidenceType.PLATFORM_INTEGRATION_RESULT.value,
                phase=EvidencePhase.INTEGRATION.value, artifact_id=artifact.id, platform=item.id,
                toolchain_version=item.toolchain_version, rule_package_version=item.evidence.get("package", {}).get("version"))
            session.flush(); result.update({"artifact_id": artifact.id, "evidence_id": evidence.id, "sha256": artifact.sha256})
            item.evidence = {**item.evidence, "real_validation": result}
            history(session, item, principal, "CANDIDATE_REAL_VALIDATION_BLOCKED", item.revision, "未安装固定真实接入 Runner")
            session.commit(); return candidate_payload(item, principal)
        active = session.scalar(select(CandidateValidationTask).where(
            CandidateValidationTask.candidate_id == item.id, CandidateValidationTask.candidate_revision == item.revision,
            CandidateValidationTask.status.in_(["QUEUED", "CLAIMED", "RUNNING"])))
        if active:
            return {**candidate_payload(item, principal), "validation_task": validation_payload(active)}
        previous_attempt = session.scalar(select(func.max(CandidateValidationTask.attempt)).where(
            CandidateValidationTask.candidate_id == item.id,
            CandidateValidationTask.candidate_revision == item.revision)) or 0
        task = CandidateValidationTask(candidate_id=item.id, candidate_revision=item.revision, agent_id=item.agent_id,
                                       attempt=previous_attempt + 1, status="QUEUED", runner_release="s100-runner-1.0.0")
        session.add(task); session.flush()
        result = {"kind": "REAL_INTEGRATION", "status": "QUEUED", "progress_percent": 0,
                  "candidate_revision": item.revision, "runner_release": task.runner_release,
                  "validation_task_id": task.id, "requested_by": principal.subject, "requested_at": utcnow().isoformat()}
        item.evidence = {**item.evidence, "real_validation": result}
        item.last_handled_by, item.last_handled_at = principal.subject, utcnow()
        history(session, item, principal, "CANDIDATE_REAL_VALIDATION_QUEUED", item.revision)
        session.add(PlatformAudit(action="CANDIDATE_REAL_VALIDATION_QUEUED", actor=principal.subject,
                    result="QUEUED", summary="S100 当前修订真实验证已由固定 Runner 排队"))
        session.commit(); return {**candidate_payload(item, principal), "validation_task": validation_payload(task)}
    finally: session.close()


@router.post("/api/internal/workers/{worker_id}/candidate-validations/claim")
def claim_candidate_validation(worker_id: str, request: Request, authorization: str | None = Header(None)):
    from solution_advisor.api.routers.workers import worker_auth
    worker_auth(request, authorization); session = request.app.state.session_factory()
    try:
        task = session.scalar(select(CandidateValidationTask).where(
            CandidateValidationTask.agent_id == worker_id, CandidateValidationTask.status == "QUEUED").order_by(CandidateValidationTask.created_at).with_for_update())
        if task is None: return None
        task.status, task.worker_instance_id, task.started_at = "CLAIMED", worker_id, utcnow()
        session.commit(); return validation_payload(task)
    finally: session.close()


@router.post("/api/internal/workers/{worker_id}/candidate-validations/{task_id}/start")
def start_candidate_validation(worker_id: str, task_id: str, request: Request, authorization: str | None = Header(None)):
    from solution_advisor.api.routers.workers import worker_auth
    worker_auth(request, authorization); session = request.app.state.session_factory()
    try:
        task = session.get(CandidateValidationTask, task_id)
        if not task or task.worker_instance_id != worker_id or task.status != "CLAIMED": raise HTTPException(409, {"code":"validation_not_claimed"})
        task.status = "RUNNING"; session.commit(); return validation_payload(task)
    finally: session.close()


@router.post("/api/internal/workers/{worker_id}/candidate-validations/{task_id}/evidence", status_code=201)
def upload_candidate_validation_evidence(worker_id: str, task_id: str, request: Request, evidence_type: str = Form(...),
                                         phase: str = Form(...), file: UploadFile = File(...), authorization: str | None = Header(None)):
    from solution_advisor.api.routers.workers import worker_auth
    worker_auth(request, authorization); session = request.app.state.session_factory()
    allowed = {"s100_static_check", "s100_compile_log", "s100_compile_summary", "s100_runner_result", "s100_compiled_model", "s100_board_preflight", "s100_board_load_log", "s100_board_inference_log", "s100_board_profile_log", "s100_board_profile_csv", "s100_board_result"}
    try:
        task = session.get(CandidateValidationTask, task_id)
        if not task or task.worker_instance_id != worker_id or task.status not in {"CLAIMED", "RUNNING"}: raise HTTPException(409, {"code":"validation_not_active"})
        if evidence_type not in allowed or phase not in {"COMPILATION", "BOARD_TEST", "INTEGRATION"}: raise HTTPException(422, {"code":"s100_evidence_not_allowed"})
        payload = file.file.read()
        if not payload: raise HTTPException(422, {"code":"empty_evidence"})
        artifact = ArtifactService(session, request.app.state.artifact_storage).put(payload, content_type="application/octet-stream")
        evidence = EvidenceService(session).record(evidence_type=evidence_type, phase=phase, artifact_id=artifact.id,
            platform="S100", toolchain_version="hb_compile 3.5.3", rule_package_version="s100-runner-1.0.0")
        session.flush(); session.commit(); return {"id":evidence.id,"artifact_id":artifact.id,"uri":artifact.uri,"sha256":artifact.sha256,"size_bytes":artifact.size_bytes}
    finally: session.close()


class ValidationComplete(BaseModel):
    result: dict
    evidence_ids: list[str]


@router.post("/api/internal/workers/{worker_id}/candidate-validations/{task_id}/complete")
def complete_candidate_validation(worker_id: str, task_id: str, body: ValidationComplete, request: Request, authorization: str | None = Header(None)):
    from solution_advisor.api.routers.workers import worker_auth
    worker_auth(request, authorization); session = request.app.state.session_factory()
    try:
        task = session.get(CandidateValidationTask, task_id)
        if not task or task.worker_instance_id != worker_id or task.status not in {"CLAIMED", "RUNNING"}: raise HTTPException(409,{"code":"validation_not_active"})
        candidate = session.get(PlatformCandidate, task.candidate_id)
        evidence_by_type = body.result.get("evidence_by_type", {})
        required_evidence = {"s100_compile_log", "s100_runner_result", "s100_compiled_model",
                             "s100_board_preflight", "s100_board_inference_log", "s100_board_result"}
        evidence_complete = required_evidence.issubset(evidence_by_type) and set(evidence_by_type.values()).issubset(set(body.evidence_ids))
        expected_release = S100_RUNNER_RELEASES.get(task.runner_release, {})
        result_runner_ok = (body.result.get("runner_release") == task.runner_release
                            and body.result.get("runner_content_sha256") == expected_release.get("content_sha256"))
        success = (body.result.get("status") == "SUCCEEDED" and candidate
                   and candidate.revision == task.candidate_revision and evidence_complete)
        success = bool(success and result_runner_ok)
        task.status, task.result, task.evidence_ids, task.finished_at = ("SUCCEEDED" if success else "BLOCKED"), body.result, body.evidence_ids, utcnow()
        task.error_code = None if success else ("candidate_revision_changed" if candidate and candidate.revision != task.candidate_revision else ("s100_runner_release_or_content_mismatch" if not result_runner_ok else ("s100_evidence_incomplete" if not evidence_complete else body.result.get("reason_code", "validation_failed"))))
        if candidate:
            validation = {**body.result, "candidate_revision": task.candidate_revision, "validation_task_id": task.id,
                          "runner_release": task.runner_release, "evidence_ids": body.evidence_ids,
                          "status": task.status, "reason_code": task.error_code}
            candidate.evidence = {**candidate.evidence, "real_validation": validation}
            history(session, candidate, type("WorkerPrincipal", (), {"subject": worker_id})(),
                    "CANDIDATE_REAL_VALIDATION_COMPLETED", candidate.revision, task.error_code)
            session.add(PlatformAudit(action="CANDIDATE_REAL_VALIDATION_COMPLETED", actor=worker_id, result=task.status,
                        summary="S100 HostAgent 固定 Runner 已回传真实验证结果"))
        session.commit(); return validation_payload(task)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/quick-validation")
def quick_validate_candidate(candidate_id: str, request: Request,
                             if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Revalidate the current Candidate revision through both fixed validation stages."""
    offline = run_candidate_integration(candidate_id, request, if_match, authorization)
    if not offline["integration_test"].get("passed"):
        return {**offline, "quick_validation": {"status": "FAILED", "stages": ["OFFLINE_FAILED"]}}
    validated = run_candidate_real_validation(candidate_id, request, str(offline["revision"]), authorization)
    status = "VERIFIED" if validated["real_validation"].get("status") == "SUCCEEDED" else "BLOCKED"
    return {**validated, "quick_validation": {"status": status, "stages": ["OFFLINE_PASSED", validated["real_validation"].get("status", "UNKNOWN")]}}


@router.get("/api/admin/platform-candidates/{candidate_id}/history")
def candidate_history(candidate_id: str, request: Request, authorization: str | None = Header(None)):
    principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        if not session.get(PlatformCandidate, candidate_id): raise HTTPException(404, {"code": "candidate_not_found"})
        return [{"actor": x.actor, "action": x.action, "old_revision": x.old_revision,
                 "new_revision": x.new_revision, "reason": x.reason,
                 "created_at": x.created_at.isoformat() if x.created_at else None}
                for x in session.scalars(select(CandidateHistory).where(CandidateHistory.candidate_id == candidate_id).order_by(CandidateHistory.created_at.desc()))]
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/archive")
def archive_candidate(candidate_id: str, body: CandidateAction, request: Request,
                      if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        if item.catalog_id: raise HTTPException(409, {"code": "candidate_catalog_linked"})
        if item.archived_at: raise HTTPException(409, {"code": "candidate_already_archived"})
        if if_match != str(item.revision): raise HTTPException(409, {"code": "candidate_revision_conflict", "revision": item.revision})
        is_owner = candidate_claimed(item) and item.claimed_by == principal.subject
        if not is_owner and principal.role != SUPER_ADMIN:
            raise HTTPException(423, {"code": "candidate_claim_forbidden", "claimed_by": item.claimed_by_name})
        if not is_owner and not body.reason:
            raise HTTPException(422, {"code": "archive_reason_required"})
        old = item.revision; archived_at = utcnow()
        item.archived_at, item.archived_by, item.archive_reason = archived_at, principal.subject, body.reason or None
        item.claimed_by = item.claimed_by_name = item.claimed_at = item.lease_expires_at = None
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, archived_at, old + 1
        package = item.evidence.get("package", {})
        history(session, item, principal, "CANDIDATE_ARCHIVED", old, body.reason)
        session.add(PlatformAudit(action="CANDIDATE_ARCHIVED", actor=principal.subject, result="SUCCEEDED",
                    summary=f"归档未关联 Candidate；保留 History、Artifact {package.get('artifact_id', 'unknown')} 与 Evidence"))
        session.commit(); return candidate_payload(item, principal)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/restore")
def restore_candidate(candidate_id: str, body: CandidateAction, request: Request,
                      if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        if principal.role != SUPER_ADMIN: raise HTTPException(403, {"code": "super_admin_required"})
        if not body.reason: raise HTTPException(422, {"code": "restore_reason_required"})
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        if not item.archived_at: raise HTTPException(409, {"code": "candidate_not_archived"})
        if if_match != str(item.revision): raise HTTPException(409, {"code": "candidate_revision_conflict", "revision": item.revision})
        old = item.revision
        item.archived_at = item.archived_by = item.archive_reason = None
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        history(session, item, principal, "CANDIDATE_RESTORED", old, body.reason)
        session.add(PlatformAudit(action="CANDIDATE_RESTORED", actor=principal.subject, result="SUCCEEDED",
                    summary=f"恢复归档 Candidate：{body.reason}"))
        try:
            session.commit()
        except IntegrityError:
            session.rollback(); raise HTTPException(409, {"code": "platform_candidate_exists"})
        return candidate_payload(item, principal)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/integration")
def pending_integration(candidate_id: str, request: Request, if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        item.state = "PENDING_INTEGRATION"; item.revision = old + 1
        history(session, item, principal, "CANDIDATE_RESET", old); session.commit()
        return {"id": item.id, "state": item.state, "notice": "候选仅进入待接入，不会自动发布或创建 Binding。"}
    finally: session.close()


@router.get("/api/admin/users")
def users(request: Request, authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization)
    if principal.role != SUPER_ADMIN: raise HTTPException(403, {"code": "super_admin_required"})
    session = request.app.state.session_factory()
    try:
        return [{"subject": x.id, "display_name": x.display_name, "role": x.role, "active": x.active,
                 "username": x.username, "auth_source": x.auth_source}
                for x in session.scalars(select(UserAccount).order_by(UserAccount.created_at))]
    finally: session.close()


@router.post("/api/admin/users", status_code=201)
def create_user(body: UserInput, request: Request, authorization: str | None = Header(None)):
    # The legacy endpoint activated arbitrary local accounts immediately.
    # Personnel lifecycle, revision and session revocation now live under
    # /api/admin/people; retain only a stable, auditable rejection.
    principal = principal_admin(request, authorization)
    raise HTTPException(410, {"code": "use_personnel_management_api"})


@router.post("/api/admin/users/super-admin-handover")
def handover_super_admin(body: HandoverInput, request: Request, authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization)
    if principal.role != SUPER_ADMIN: raise HTTPException(403, {"code": "super_admin_required"})
    session = request.app.state.session_factory()
    try:
        successor = session.get(UserAccount, body.successor_subject)
        if successor is None or not successor.active or successor.status != "ACTIVE": raise HTTPException(404, {"code": "handover_successor_not_found"})
        if successor.id == principal.subject: raise HTTPException(422, {"code": "handover_successor_must_differ"})
        current = session.get(UserAccount, principal.subject)
        # Demote first so the partial unique index protects the invariant throughout the transaction.
        current.role = ADMIN; successor.role = SUPER_ADMIN
        session.add(PlatformAudit(action="SUPER_ADMIN_HANDED_OVER", actor=principal.subject,
                    summary=f"向 {successor.id} 交接超级管理员：{body.reason}")); session.commit()
        return {"previous_subject": current.id, "successor_subject": successor.id, "reason": body.reason}
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/integration-runs")
def run_candidate_integration(candidate_id: str, request: Request, if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Run the only candidate Runner: deterministic offline contract verification.

    No supplied command, image option, path, credential, compiler, Docker daemon or board is reachable here.
    """
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        package = item.evidence.get("package", {})
        package_valid = False
        if package.get("artifact_id"):
            artifact = ArtifactService(session, request.app.state.artifact_storage)
            from solution_advisor.artifacts.domain import Artifact
            stored = session.get(Artifact, package["artifact_id"])
            if stored:
                try:
                    with ZipFile(request.app.state.artifact_storage.open(stored.uri)) as archive:
                        manifest = json.loads(archive.read("manifest.json"))
                        runner = json.loads(archive.read("runner.json"))
                        package_valid = (manifest.get("id") == package.get("id")
                                         and manifest.get("image_lock", {}).get("digest") == item.image_id
                                         and runner == {"entrypoint": "execute", "module": "platform_runner",
                                                        "policy": "fixed", "version": "0.1.0"})
                except (KeyError, ValueError, OSError):
                    package_valid = False
        passed = bool(package_valid and package.get("image_lock_digest") == item.image_id
                      and package.get("runner_id") == "candidate-integration-runner-v1")
        result = {"runner_id": "candidate-integration-runner-v1", "status": "PASSED" if passed else "FAILED",
                  "checks": {"package_artifact": package_valid,
                             "immutable_digest": package.get("image_lock_digest") == item.image_id,
                             "offline_runner_contract": package.get("runner_id") == "candidate-integration-runner-v1"},
                  "boundaries": candidate_package(package_id=package.get("id", "unknown"), image=HostImage(image_ref=item.image_ref, image_id=item.image_id, agent_id=item.agent_id), note="")["boundaries"]}
        artifact = ArtifactService(session, request.app.state.artifact_storage).put(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode(), content_type="application/json")
        evidence = EvidenceService(session).record(evidence_type=EvidenceType.PLATFORM_INTEGRATION_RESULT.value,
            phase=EvidencePhase.INTEGRATION.value, artifact_id=artifact.id, platform=package.get("id"),
            toolchain_version=item.toolchain_version, rule_package_version=package.get("version"))
        next_revision = old + 1
        item.evidence = {**item.evidence, "integration_test": {"passed": passed, "runner_id": result["runner_id"],
                         "candidate_revision": next_revision,
                         "artifact_id": artifact.id, "evidence_id": evidence.id, "sha256": artifact.sha256}}
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), next_revision
        history(session, item, principal, "CANDIDATE_TESTED", old)
        session.add(PlatformAudit(action="CANDIDATE_INTEGRATION_TESTED", actor="admin", summary="固定离线接入 Runner 已生成 Evidence"))
        session.commit(); return candidate_payload(item, principal)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/catalogs", status_code=201)
def create_catalog_from_candidate(candidate_id: str, body: CandidateCatalogInput, request: Request,
                                  if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match); old = item.revision
        existing_catalog = session.get(PlatformCatalog, item.catalog_id) if item.catalog_id else None
        if existing_catalog and not item.evidence.get("workspace_reopened"):
            raise HTTPException(409, {"code": "candidate_catalog_exists"})
        package, test = item.evidence.get("package", {}), candidate_integration_test(item)
        real_validation = candidate_real_validation(item)
        if not package.get("artifact_id") or not test.get("passed"):
            raise HTTPException(422, {"code": "candidate_integration_requirements_missing"})
        if not (test.get("passed") and test.get("current")
                and real_validation.get("current") and real_validation.get("status") == "SUCCEEDED"
                and (real_validation.get("evidence_id") or real_validation.get("evidence_ids"))):
            raise HTTPException(422, {"code": "candidate_real_validation_required"})
        platform_type = session.get(PlatformType, item.platform_type_id) if item.platform_type_id else None
        if not platform_type or not item.target_version:
            raise HTTPException(422, {"code": "candidate_platform_declaration_missing"})
        try:
            # The platform family and its version were explicitly selected
            # when this Candidate was created.  A review may name the display
            # label, but cannot silently redirect the immutable package to a
            # different platform identity or version.
            catalog_values = {"package_manifest": {"id": package["id"], "version": package["version"], "artifact_id": package["artifact_id"],
                              "sha256": package["sha256"]}, "image_lock": {"image": item.image_ref, "digest": item.image_id},
                "runner": {"module": "platform_runner", "version": real_validation.get("runner_release") or "0.1.0",
                        "content_sha256": real_validation.get("runner_content_sha256"), "entrypoint": "execute",
                        "package_artifact_id": package["artifact_id"],
                        "integration_rules": candidate_workspace(item)},
                "checks": {"self_check": True, "offline_test": True, "integration_evidence_id": test["evidence_id"],
                        "real_validation_evidence_id": real_validation.get("evidence_id") or real_validation["evidence_ids"][0]},
                "review": {"approved": body.approved, "note": body.review_note, "candidate_id": item.id}}
            if existing_catalog:
                existing_catalog.display_name = body.display_name or platform_type.display_name
                existing_catalog.platform_type_id = platform_type.id
                existing_catalog.package_manifest, existing_catalog.image_lock = catalog_values["package_manifest"], catalog_values["image_lock"]
                existing_catalog.runner, existing_catalog.checks, existing_catalog.review = catalog_values["runner"], catalog_values["checks"], catalog_values["review"]
                existing_catalog.state, existing_catalog.reason = "PENDING_INTEGRATION", None
                catalog = existing_catalog
            else:
                catalog = PlatformRegistry(session).create_catalog(platform_id=platform_type.name, version=item.target_version,
                    display_name=body.display_name or platform_type.display_name, platform_type_id=platform_type.id, **catalog_values)
        except PlatformError as exc: problem(exc)
        item.catalog_id = catalog.id
        item.evidence = {**item.evidence, "workspace_reopened": False}
        item.last_handled_by, item.last_handled_at, item.revision = principal.subject, utcnow(), old + 1
        history(session, item, principal, "CANDIDATE_ADVANCED", old)
        session.add(PlatformAudit(action="CANDIDATE_CATALOG_DRAFTED", actor="admin", catalog_id=catalog.id,
                    summary="真实接入验证 Evidence 已关联待审核 Catalog")); session.commit()
        return catalog_payload(catalog)
    finally: session.close()


@router.post("/api/admin/platform-candidates/{candidate_id}/catalog-releases", status_code=201)
def create_catalog_release_from_candidate(candidate_id: str, body: CandidateCatalogReleaseInput, request: Request,
                                          if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    """Publish a successor Catalog from the current, verified Candidate revision.

    The linked historical Catalog is intentionally left untouched.  This is
    the only supported route for changing a fixed Runner release.
    """
    principal = principal_admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate_id)
        if not item: raise HTTPException(404, {"code": "candidate_not_found"})
        require_claim(item, principal, if_match)
        package, offline = item.evidence.get("package", {}), candidate_integration_test(item)
        validation = candidate_real_validation(item)
        release = S100_RUNNER_RELEASES.get(validation.get("runner_release"), {})
        if not (offline.get("passed") and offline.get("current") and validation.get("current")
                and validation.get("status") == "SUCCEEDED" and release
                and validation.get("runner_content_sha256") == release.get("content_sha256")
                and validation.get("candidate_revision") == item.revision):
            raise HTTPException(422, {"code": "current_runner_verified_validation_required"})
        existing_release = session.scalar(select(PlatformCatalog).where(PlatformCatalog.platform_id == "S100", PlatformCatalog.version == body.release_version))
        if existing_release and existing_release.review.get("candidate_id") != item.id:
            raise HTTPException(409, {"code": "catalog_release_version_exists"})
        platform_type = session.get(PlatformType, item.platform_type_id) if item.platform_type_id else None
        if not platform_type or platform_type.name.upper() != "S100":
            raise HTTPException(422, {"code": "s100_platform_type_required"})
        validation_evidence = list(validation.get("evidence_ids", []))
        values = {
            "package_manifest": {"id": package.get("id"), "version": package.get("version"), "artifact_id": package.get("artifact_id"), "sha256": package.get("sha256")},
            "image_lock": {"image": item.image_ref, "digest": item.image_id},
            "runner": {"module": "platform_runner", "version": validation["runner_release"],
                       "content_sha256": validation["runner_content_sha256"], "entrypoint": "execute",
                       "package_artifact_id": package.get("artifact_id"), "integration_rules": candidate_workspace(item)},
            "checks": {"self_check": True, "offline_test": True,
                       "integration_evidence_id": offline.get("evidence_id"),
                       "real_validation_evidence_id": validation_evidence[0] if validation_evidence else None,
                       "real_validation_evidence_ids": validation_evidence,
                       "candidate_id": item.id, "candidate_revision": item.revision},
            "review": {"approved": True, "note": body.review_note, "candidate_id": item.id,
                       "release_of_catalog_id": item.catalog_id, "immutable": True},
        }
        try:
            if existing_release:
                catalog = existing_release
            else:
                catalog = PlatformRegistry(session).create_catalog(platform_id="S100", version=body.release_version,
                    display_name=body.display_name, platform_type_id=platform_type.id, **values)
                catalog = PlatformRegistry(session).review_catalog(catalog.id, approved=True, note=body.review_note)
                catalog = PlatformRegistry(session).publish(catalog.id)
        except PlatformError as exc:
            problem(exc)
        # The verified Candidate now becomes immutable provenance of this
        # successor Release.  It is no longer an active Candidate slot and
        # its lease must not block a later, independently reviewed release.
        item.catalog_id = catalog.id
        item.state = "PUBLISHED"
        item.claimed_by = item.claimed_by_name = None
        item.claimed_at = item.lease_expires_at = None
        history(session, item, principal, "CANDIDATE_CATALOG_RELEASED", item.revision,
                f"冻结为 Catalog Release {catalog.version}")
        session.add(PlatformAudit(action="CATALOG_RELEASE_PUBLISHED", actor=principal.subject, catalog_id=catalog.id,
                    summary=f"从 Candidate 当前修订 {item.revision} 冻结 S100 Runner {validation['runner_release']} 与内容哈希"))
        session.commit()
        return catalog_payload(catalog)
    finally:
        session.close()


@router.get("/api/admin/platform-bindings")
def bindings(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return [binding_payload(session, item) for item in session.scalars(select(PlatformBinding).order_by(PlatformBinding.created_at.desc()))]
    finally: session.close()


@router.post("/api/admin/platform-bindings", status_code=201)
def create_binding(body: BindingInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).create_binding(**body.model_dump())
        except PlatformError as exc: problem(exc, 409 if str(exc) == "binding_already_exists" else 422)
        return binding_payload(session, item)
    finally: session.close()


@router.post("/api/admin/platform-bindings/{binding_id}/capacity")
def binding_capacity(binding_id: str, body: BindingCapacityInput, request: Request,
                     authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).set_binding_capacity(binding_id, body.max_concurrency)
        except PlatformError as exc: problem(exc, 409 if str(exc) in {"binding_capacity_exceeds_agent_capacity", "binding_capacity_below_active_load"} else 422)
        return binding_payload(session, item)
    finally: session.close()


@router.post("/api/admin/platform-bindings/{binding_id}/state")
def binding_state(binding_id: str, body: StateInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try: item = PlatformRegistry(session).set_binding_state(binding_id, body.state, body.reason)
        except PlatformError as exc: problem(exc)
        return binding_payload(session, item)
    finally: session.close()


@router.get("/api/admin/platform-workers")
def platform_workers(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return [worker_payload(session, item) for item in session.scalars(select(PlatformWorker).order_by(PlatformWorker.created_at))]
    finally: session.close()


@router.get("/api/admin/platform-audits")
def audits(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return [{"action": x.action, "catalog_id": x.catalog_id, "binding_id": x.binding_id, "worker_id": x.worker_id, "result": x.result, "summary": x.summary, "created_at": x.created_at.isoformat() if x.created_at else None} for x in session.scalars(select(PlatformAudit).order_by(PlatformAudit.created_at.desc()).limit(100))]
    finally: session.close()
