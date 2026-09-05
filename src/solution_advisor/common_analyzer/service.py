from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from solution_advisor.artifacts.domain import Artifact
from solution_advisor.common_analyzer.domain import (
    AnalysisEvent, AnalysisTask, AnalyzerConfigAudit, AnalyzerConfigDraft,
    AnalyzerConfigVersion, AnalyzerConfiguration, WorkerCapacityLease, WorkerInstance,
)
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.model_assets.onnx_analyzer import analyze, load_model

ANALYZER_VERSION = "2.0.0"
LEASE_SECONDS = 600
WORKER_ID = "common-analyzer"
# This is the installed-module catalogue, deliberately independent of any draft
# or active configuration. No free-form command/path/image fields exist.
DEFAULT_MODULES = {
    "core_profile": {"version": "1.0.0", "enabled": True, "core": True, "dependencies": [], "parameters": {}},
    "model_size": {"version": "1.0.0", "enabled": True, "dependencies": [], "parameters": {}},
    "dynamic_shape": {"version": "1.0.0", "enabled": True, "dependencies": [], "parameters": {}},
}
FORBIDDEN_KEYS = {"command", "shell", "script", "path", "image", "docker", "url"}


class ConfigError(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def config_hash(modules: dict, max_concurrency: int) -> str:
    return hashlib.sha256(json.dumps({"modules": modules, "max_concurrency": max_concurrency}, sort_keys=True).encode()).hexdigest()


def ensure_configuration(session: Session) -> AnalyzerConfiguration:
    config = session.get(AnalyzerConfiguration, "default")
    if config is None:
        config = AnalyzerConfiguration(id="default", modules=deepcopy(DEFAULT_MODULES), max_concurrency=1)
        session.add(config)
        session.flush()
    # Seed a first immutable version for databases upgraded from R1.
    if session.scalar(select(AnalyzerConfigVersion).where(AnalyzerConfigVersion.version == config.revision)) is None:
        session.add(AnalyzerConfigVersion(version=config.revision, modules=config.modules,
            max_concurrency=config.max_concurrency, config_hash=config_hash(config.modules, config.max_concurrency),
            created_by="system", change_note="初始活动配置"))
        session.flush()
    return config


def validate_configuration(modules: dict, max_concurrency: int) -> None:
    if not isinstance(modules, dict) or not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 32:
        raise ConfigError("invalid_concurrency")
    if set(modules) != set(DEFAULT_MODULES):
        raise ConfigError("unknown_module")
    graph: dict[str, list[str]] = {}
    for module_id, installed in DEFAULT_MODULES.items():
        value = modules.get(module_id)
        if not isinstance(value, dict) or set(value) - {"enabled", "parameters", "dependencies", "max_concurrency", "version", "core"}:
            raise ConfigError("invalid_module_schema")
        if not isinstance(value.get("enabled"), bool):
            raise ConfigError("invalid_module_enabled")
        if installed.get("core") and not value["enabled"]:
            raise ConfigError("core_module_required")
        parameters = value.get("parameters", {})
        if not isinstance(parameters, dict) or any(k.lower() in FORBIDDEN_KEYS for k in parameters):
            raise ConfigError("invalid_parameter")
        if any(not isinstance(v, (bool, int, float, str)) or (isinstance(v, str) and len(v) > 200) for v in parameters.values()):
            raise ConfigError("invalid_parameter")
        limit = value.get("max_concurrency", max_concurrency)
        if not isinstance(limit, int) or not 1 <= limit <= max_concurrency:
            raise ConfigError("invalid_module_concurrency")
        deps = value.get("dependencies", [])
        if not isinstance(deps, list) or any(dep not in DEFAULT_MODULES for dep in deps):
            raise ConfigError("invalid_dependency")
        if any(not modules[dep].get("enabled") for dep in deps):
            raise ConfigError("disabled_dependency")
        graph[module_id] = deps
    visiting, visited = set(), set()
    def visit(node: str):
        if node in visiting: raise ConfigError("cyclic_dependency")
        if node not in visited:
            visiting.add(node)
            for child in graph[node]: visit(child)
            visiting.remove(node); visited.add(node)
    for item in graph: visit(item)


def audit(session: Session, action: str, actor: str, *, draft_id: str | None = None,
          old_version: int | None = None, new_version: int | None = None,
          summary: str = "", result: str = "SUCCEEDED", error_code: str | None = None) -> None:
    session.add(AnalyzerConfigAudit(action=action, actor=actor, draft_id=draft_id, old_version=old_version,
        new_version=new_version, summary=summary[:500], result=result, error_code=error_code))


def draft_payload(draft: AnalyzerConfigDraft) -> dict:
    return {"id": draft.id, "base_version": draft.base_version, "modules": draft.modules,
            "max_concurrency": draft.max_concurrency, "config_hash": draft.config_hash,
            "schema_version": draft.schema_version, "created_by": draft.created_by, "updated_by": draft.updated_by,
            "change_note": draft.change_note, "status": draft.status,
            "created_at": draft.created_at.isoformat() if draft.created_at else None,
            "updated_at": draft.updated_at.isoformat() if draft.updated_at else None}


def create_draft(session: Session, actor: str, *, source: AnalyzerConfigVersion | None = None, note: str = "") -> AnalyzerConfigDraft:
    current = ensure_configuration(session)
    source_modules = source.modules if source else current.modules
    source_limit = source.max_concurrency if source else current.max_concurrency
    draft = AnalyzerConfigDraft(base_version=current.revision, modules=source_modules,
        max_concurrency=source_limit, config_hash=config_hash(source_modules, source_limit),
        created_by=actor, updated_by=actor, change_note=note)
    session.add(draft); session.flush(); audit(session, "DRAFT_CREATE", actor, draft_id=draft.id,
        old_version=current.revision, summary="创建配置草稿"); session.commit(); return draft


def update_draft(session: Session, draft: AnalyzerConfigDraft, modules: dict, max_concurrency: int, note: str, actor: str) -> AnalyzerConfigDraft:
    try: validate_configuration(modules, max_concurrency)
    except ConfigError as exc:
        audit(session, "DRAFT_VALIDATE", actor, draft_id=draft.id, old_version=draft.base_version,
              summary="草稿校验失败", result="REJECTED", error_code=str(exc)); session.commit(); raise
    if draft.status != "DRAFT": raise ConfigError("draft_not_editable")
    draft.modules, draft.max_concurrency, draft.change_note, draft.updated_by = modules, max_concurrency, note, actor
    draft.config_hash = config_hash(modules, max_concurrency)
    audit(session, "DRAFT_UPDATE", actor, draft_id=draft.id, old_version=draft.base_version, summary="更新配置草稿")
    session.commit(); return draft


def publish_draft(session: Session, draft: AnalyzerConfigDraft, actor: str, expected: int) -> AnalyzerConfigVersion:
    current = ensure_configuration(session)
    if draft.status != "DRAFT" or expected != current.revision or draft.base_version != current.revision:
        audit(session, "DRAFT_PUBLISH", actor, draft_id=draft.id, old_version=current.revision,
              summary="活动配置已变化", result="REJECTED", error_code="version_conflict"); session.commit()
        raise ConfigError("version_conflict")
    validate_configuration(draft.modules, draft.max_concurrency)
    version = current.revision + 1
    record = AnalyzerConfigVersion(version=version, modules=draft.modules, max_concurrency=draft.max_concurrency,
        config_hash=draft.config_hash, created_by=actor, change_note=draft.change_note)
    session.add(record); current.revision, current.modules, current.max_concurrency = version, draft.modules, draft.max_concurrency
    draft.status = "PUBLISHED"; audit(session, "DRAFT_PUBLISH", actor, draft_id=draft.id, old_version=version - 1,
        new_version=version, summary=draft.change_note or "发布配置草稿")
    session.commit(); return record


def release_lease(session: Session, lease: WorkerCapacityLease | None, status: str = "RELEASED") -> None:
    if lease and lease.status == "ACTIVE":
        lease.status, lease.released_at = status, now()
        session.flush()


def reclaim_expired_leases(session: Session) -> list[str]:
    expired = list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.status == "ACTIVE", WorkerCapacityLease.expires_at < now())))
    task_ids = []
    for lease in expired:
        lease.status, lease.released_at = "EXPIRED", now(); task_ids.append(lease.task_id)
        task = session.get(AnalysisTask, lease.task_id)
        if task and task.status == "RUNNING" and task.attempt_id == lease.attempt_id:
            task.status, task.lease_expires_at, task.error_code = "QUEUED", None, "lease_expired"
            audit(session, "LEASE_RECLAIM", "recovery", summary=f"回收 {lease.worker_instance_id} 槽位 {lease.slot_index}")
    return task_ids


def acquire_lease(session: Session, task: AnalysisTask) -> WorkerCapacityLease | None:
    """Acquire a persisted slot. The partial unique index is the final guard.

    PostgreSQL locks the active config row before determining capacity. A concurrent
    contender either sees the committed lease or loses the unique-index race; it is
    then returned to QUEUED rather than exceeding capacity.
    """
    config = session.execute(select(AnalyzerConfiguration).where(AnalyzerConfiguration.id == "default").with_for_update()).scalar_one()
    reclaim_expired_leases(session)
    active = list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.worker_instance_id == WORKER_ID, WorkerCapacityLease.status == "ACTIVE").with_for_update()))
    used = {lease.slot_index for lease in active}
    if len(active) >= config.max_concurrency: return None
    slot = next(index for index in range(config.max_concurrency) if index not in used)
    lease = WorkerCapacityLease(worker_instance_id=WORKER_ID, slot_index=slot, task_id=task.id,
        attempt_id=task.attempt_id or "", lease_token=uuid4().hex, expires_at=now() + timedelta(seconds=LEASE_SECONDS),
        last_heartbeat_at=now())
    session.add(lease); session.flush(); return lease


def acquire_worker_lease(session: Session, worker_instance_id: str, task_id: str,
                         attempt_id: str) -> WorkerCapacityLease | None:
    """Atomically reserve one persisted slot for any registered Worker.

    The Worker row is locked before slots are counted.  The partial unique index
    on ``(worker_instance_id, slot_index) WHERE status='ACTIVE'`` remains the
    final database guard if two transactions race at a database boundary.
    """
    worker = session.execute(select(WorkerInstance).where(
        WorkerInstance.id == worker_instance_id
    ).with_for_update()).scalar_one_or_none()
    if worker is None:
        # Platform execution Workers are dynamic children of a Binding; they
        # share this PostgreSQL lease protocol instead of inventing another lock.
        from solution_advisor.platforms.domain import PlatformWorker
        worker = session.execute(select(PlatformWorker).where(
            PlatformWorker.id == worker_instance_id
        ).with_for_update()).scalar_one_or_none()
    if worker is None:
        return None
    expired = list(session.scalars(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id == worker_instance_id,
        WorkerCapacityLease.status == "ACTIVE",
        WorkerCapacityLease.expires_at < now(),
    ).with_for_update()))
    for lease in expired:
        lease.status, lease.released_at = "EXPIRED", now()
    active = list(session.scalars(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id == worker_instance_id,
        WorkerCapacityLease.status == "ACTIVE",
    ).with_for_update()))
    if len(active) >= worker.max_concurrency:
        return None
    used = {item.slot_index for item in active}
    slot = next(index for index in range(worker.max_concurrency) if index not in used)
    lease = WorkerCapacityLease(
        worker_instance_id=worker_instance_id, slot_index=slot, task_id=task_id,
        attempt_id=attempt_id, lease_token=uuid4().hex,
        status="ACTIVE", expires_at=now() + timedelta(seconds=LEASE_SECONDS),
        last_heartbeat_at=now(),
    )
    session.add(lease)
    session.flush()
    return lease


def renew_worker_lease(session: Session, worker_instance_id: str, task_id: str,
                       attempt_id: str) -> bool:
    lease = session.scalar(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id == worker_instance_id,
        WorkerCapacityLease.task_id == task_id,
        WorkerCapacityLease.attempt_id == attempt_id,
        WorkerCapacityLease.status == "ACTIVE",
    ))
    if lease is None:
        return False
    lease.last_heartbeat_at = now()
    lease.expires_at = now() + timedelta(seconds=LEASE_SECONDS)
    return True


def release_worker_task_lease(session: Session, worker_instance_id: str,
                              task_id: str, attempt_id: str, status: str = "RELEASED") -> None:
    lease = session.scalar(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id == worker_instance_id,
        WorkerCapacityLease.task_id == task_id,
        WorkerCapacityLease.attempt_id == attempt_id,
        WorkerCapacityLease.status == "ACTIVE",
    ))
    release_lease(session, lease, status)


def snapshot(config: AnalyzerConfiguration) -> dict:
    value = {"revision": config.revision, "analyzer_version": ANALYZER_VERSION, "modules": config.modules,
             "max_concurrency": config.max_concurrency, "profile_schema_major": 1}
    value["snapshot_hash"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


class AnalysisService:
    def __init__(self, session: Session, storage, queue): self.session, self.storage, self.queue = session, storage, queue

    def create(self, asset: ModelAsset) -> AnalysisTask:
        # The active row is locked so snapshot creation cannot race a publish.
        config = self.session.execute(select(AnalyzerConfiguration).where(AnalyzerConfiguration.id == "default").with_for_update()).scalar_one_or_none()
        if config is None: config = ensure_configuration(self.session)
        task = AnalysisTask(model_asset_id=asset.id, artifact_id=asset.artifact_id, config_snapshot=snapshot(config))
        self.session.add(task); self.session.flush(); self._event(task, "queue", None, "QUEUED", 0); self.session.commit(); self.queue.enqueue(task.id); return task

    def _event(self, task, stage, module, status, progress, error_code=None, result_ref=None):
        sequence = len(list(self.session.scalars(select(AnalysisEvent).where(AnalysisEvent.task_id == task.id)))) + 1
        self.session.add(AnalysisEvent(task_id=task.id, attempt_id=task.attempt_id, stage_id=stage, module_id=module, status=status, progress_percent=progress, sequence=sequence, analyzer_version=ANALYZER_VERSION, error_code=error_code, result_ref=result_ref))

    def recover(self) -> list[str]:
        ids = reclaim_expired_leases(self.session)
        for task in self.session.scalars(select(AnalysisTask).where(AnalysisTask.status == "QUEUED")): ids.append(task.id)
        self.session.commit()
        for task_id in set(ids): self.queue.enqueue(task_id)
        return list(set(ids))

    def run(self, task_id: str) -> None:
        task = self.session.get(AnalysisTask, task_id)
        if task is None or task.status == "SUCCEEDED": return
        if task.status == "RUNNING" and task.lease_expires_at and task.lease_expires_at > now(): return
        task.status, task.attempt_id, task.attempts, task.started_at = "RUNNING", f"attempt_{uuid4().hex}", task.attempts + 1, now()
        try:
            lease = acquire_lease(self.session, task)
            if lease is None: task.status = "QUEUED"; self.session.commit(); return
            task.lease_expires_at = lease.expires_at; self._event(task, "core", "core_profile", "RUNNING", 10); self.session.commit()
        except IntegrityError:
            self.session.rollback(); task = self.session.get(AnalysisTask, task_id); task.status = "QUEUED"; self.session.commit(); return
        try:
            asset, artifact = self.session.get(ModelAsset, task.model_asset_id), self.session.get(Artifact, task.artifact_id)
            with self.storage.open(artifact.uri) as stream: payload = stream.read()
            analysis = analyze(load_model(payload), filename=asset.original_filename, size_bytes=asset.size_bytes, sha256=asset.sha256)
            self._event(task, "core", "core_profile", "SUCCEEDED", 55); enabled = task.config_snapshot["modules"]
            def module_result(module_id): return {"file_size_bytes": len(payload)} if module_id == "model_size" else {"has_dynamic_shape": analysis["summary"]["structure_flags"]["has_dynamic_shape"]}
            module_ids = [key for key, val in enabled.items() if key != "core_profile" and val.get("enabled") and not val.get("dependencies")]
            with ThreadPoolExecutor(max_workers=max(1, task.config_snapshot["max_concurrency"])) as pool: results = dict(zip(module_ids, pool.map(module_result, module_ids)))
            for module_id in module_ids: self._event(task, "optional", module_id, "SUCCEEDED", 80)
            analysis["analyzer_modules"], analysis["analyzer_snapshot"] = results, task.config_snapshot
            analysis["analysis_policy"] = {
                "revision": task.config_snapshot["revision"],
                "base_checks": ["core_profile"],
                "extensions": {
                    module_id: ("EXECUTED" if enabled.get("enabled") else "NOT_ENABLED")
                    for module_id, enabled in task.config_snapshot["modules"].items()
                    if module_id != "core_profile"
                },
            }
            profile_version = f"{ANALYZER_VERSION}:{task.config_snapshot['snapshot_hash'][:12]}"
            profile = self.session.scalar(select(ModelProfile).where(ModelProfile.onnx_sha256 == asset.sha256, ModelProfile.analyzer_version == profile_version))
            if profile is None: profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version=profile_version, analysis=analysis); self.session.add(profile); self.session.flush()
            task.profile_id, task.status, task.finished_at, task.lease_expires_at = profile.id, "SUCCEEDED", now(), None; self._event(task, "aggregate", None, "SUCCEEDED", 100, result_ref=profile.id); release_lease(self.session, lease); self.session.commit()
        except Exception:
            task.status, task.error_code, task.lease_expires_at = ("FAILED" if task.attempts >= task.max_attempts else "QUEUED"), "analysis_failed", None
            self._event(task, "aggregate", None, task.status, 0, "analysis_failed"); release_lease(self.session, lease, "FAILED"); self.session.commit()
            if task.status == "QUEUED": self.queue.enqueue(task.id)
