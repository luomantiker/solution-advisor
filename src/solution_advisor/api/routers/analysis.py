from __future__ import annotations

from datetime import timedelta
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from solution_advisor.common_analyzer.domain import AnalysisEvent, AnalysisTask, AnalyzerConfigAudit, AnalyzerConfigDraft, AnalyzerConfigVersion, WorkerCapacityLease, WorkerInstance
from solution_advisor.model_assets.domain import ModelAssetAccess
from solution_advisor.platforms.domain import PlatformWorker
from solution_advisor.common_analyzer.service import (
    WORKER_ID, ConfigError, audit, create_draft, draft_payload, ensure_configuration,
    now, publish_draft, reclaim_expired_leases, update_draft, validate_configuration,
)

router = APIRouter(tags=["analysis"])


def lease_owner_ids(session, instance_id: str) -> list[str]:
    """Return all persisted lease owners represented by one HostAgent view.

    Generic analysis leases use the WorkerInstance id directly, while platform
    work is leased against its dynamic PlatformWorker id.  The management view
    must aggregate both; otherwise a Host with active platform containers is
    incorrectly displayed as idle.
    """
    platform_workers = list(session.scalars(select(PlatformWorker.id).where(
        PlatformWorker.agent_id == instance_id
    )))
    return [instance_id, *platform_workers]


def active_leases_for_instance(session, instance_id: str):
    return list(session.scalars(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id.in_(lease_owner_ids(session, instance_id)),
        WorkerCapacityLease.status == "ACTIVE",
    )))


def admin(request: Request, authorization: str | None):
    from solution_advisor.security import ADMIN, SUPER_ADMIN, resolve_principal
    return resolve_principal(request, authorization, ADMIN, SUPER_ADMIN)


def protected_error(exc: ConfigError, status: int = 422):
    raise HTTPException(status, {"code": str(exc)})


class DraftInput(BaseModel):
    modules: dict | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=32)
    change_note: str = Field(default="", max_length=500)


class PublishInput(BaseModel):
    if_match: int = Field(ge=1)


class RollbackInput(BaseModel):
    version: int = Field(ge=1)
    if_match: int = Field(ge=1)
    change_note: str = Field(default="", max_length=500)


@router.get("/api/v1/analysis-tasks/{task_id}")
def task(task_id: str, request: Request, authorization: str | None = Header(None)):
    from solution_advisor.security import ADMIN, SUPER_ADMIN, resolve_principal
    principal = resolve_principal(request, authorization, "USER", ADMIN, SUPER_ADMIN)
    session = request.app.state.session_factory()
    try:
        item = session.get(AnalysisTask, task_id)
        if not item: raise HTTPException(404, "Analysis task not found")
        if principal.role not in {ADMIN, SUPER_ADMIN} and not session.scalar(select(ModelAssetAccess).where(
            ModelAssetAccess.model_asset_id == item.model_asset_id, ModelAssetAccess.subject == principal.subject)):
            raise HTTPException(404, "Analysis task not found")
        events = list(session.scalars(select(AnalysisEvent).where(AnalysisEvent.task_id == task_id).order_by(AnalysisEvent.sequence)))
        return {"id": item.id, "status": item.status, "profile_id": item.profile_id, "error_code": item.error_code, "snapshot": item.config_snapshot, "events": [{"stage_id": x.stage_id, "module_id": x.module_id, "status": x.status, "progress_percent": x.progress_percent, "sequence": x.sequence, "error_code": x.error_code} for x in events]}
    finally: session.close()


def active_config(session):
    item = ensure_configuration(session); session.commit()
    version = session.scalar(select(AnalyzerConfigVersion).where(AnalyzerConfigVersion.version == item.revision))
    return {"revision": item.revision, "modules": item.modules, "max_concurrency": item.max_concurrency,
            "config_hash": version.config_hash if version else None, "created_by": version.created_by if version else "system",
            "change_note": version.change_note if version else "", "effective_at": version.created_at.isoformat() if version and version.created_at else None}


@router.get("/api/admin/analyzer-config")
def get_config(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return active_config(session)
    finally: session.close()


@router.get("/api/admin/analyzer-config/history")
def history(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        versions = [{"version": x.version, "hash": x.config_hash, "note": x.change_note, "created_by": x.created_by, "created_at": x.created_at.isoformat() if x.created_at else None} for x in session.scalars(select(AnalyzerConfigVersion).order_by(AnalyzerConfigVersion.version.desc()))]
        audits = [{"action": x.action, "actor": x.actor, "draft_id": x.draft_id, "old_version": x.old_version, "new_version": x.new_version, "summary": x.summary, "result": x.result, "error_code": x.error_code, "created_at": x.created_at.isoformat() if x.created_at else None} for x in session.scalars(select(AnalyzerConfigAudit).order_by(AnalyzerConfigAudit.created_at.desc()).limit(100))]
        return {"versions": versions, "audits": audits}
    finally: session.close()


@router.post("/api/admin/analyzer-config/drafts", status_code=201)
def new_draft(payload: DraftInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        draft = create_draft(session, "admin", note=payload.change_note)
        if payload.modules is not None or payload.max_concurrency is not None:
            update_draft(session, draft, payload.modules or draft.modules, payload.max_concurrency or draft.max_concurrency, payload.change_note, "admin")
        return draft_payload(draft)
    except ConfigError as exc: protected_error(exc)
    finally: session.close()


@router.get("/api/admin/analyzer-config/drafts/{draft_id}")
def get_draft(draft_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        item = session.get(AnalyzerConfigDraft, draft_id)
        if not item: raise HTTPException(404, {"code": "draft_not_found"})
        return draft_payload(item)
    finally: session.close()


@router.get("/api/admin/analyzer-config/drafts")
def list_drafts(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return [draft_payload(x) for x in session.scalars(select(AnalyzerConfigDraft).order_by(AnalyzerConfigDraft.updated_at.desc()))]
    finally: session.close()


@router.put("/api/admin/analyzer-config/drafts/{draft_id}")
def edit_draft(draft_id: str, payload: DraftInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        draft = session.get(AnalyzerConfigDraft, draft_id)
        if not draft: raise HTTPException(404, {"code": "draft_not_found"})
        if payload.modules is None or payload.max_concurrency is None: raise HTTPException(422, {"code": "draft_content_required"})
        return draft_payload(update_draft(session, draft, payload.modules, payload.max_concurrency, payload.change_note, "admin"))
    except ConfigError as exc: protected_error(exc)
    finally: session.close()


@router.post("/api/admin/analyzer-config/drafts/{draft_id}/validate")
def validate_draft(draft_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        draft = session.get(AnalyzerConfigDraft, draft_id)
        if not draft: raise HTTPException(404, {"code": "draft_not_found"})
        try: validate_configuration(draft.modules, draft.max_concurrency)
        except ConfigError as exc:
            audit(session, "DRAFT_VALIDATE", "admin", draft_id=draft.id, old_version=draft.base_version, summary="草稿校验失败", result="REJECTED", error_code=str(exc)); session.commit(); protected_error(exc)
        audit(session, "DRAFT_VALIDATE", "admin", draft_id=draft.id, old_version=draft.base_version, summary="草稿校验成功"); session.commit()
        return {"valid": True, "draft_id": draft.id}
    finally: session.close()


@router.post("/api/admin/analyzer-config/drafts/{draft_id}/publish")
def publish(draft_id: str, payload: PublishInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        draft = session.get(AnalyzerConfigDraft, draft_id)
        if not draft: raise HTTPException(404, {"code": "draft_not_found"})
        record = publish_draft(session, draft, "admin", payload.if_match)
        return {"version": record.version, "hash": record.config_hash, "draft_id": draft.id}
    except ConfigError as exc: protected_error(exc, 409 if str(exc) == "version_conflict" else 422)
    finally: session.close()


@router.delete("/api/admin/analyzer-config/drafts/{draft_id}")
def discard(draft_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        draft = session.get(AnalyzerConfigDraft, draft_id)
        if not draft: raise HTTPException(404, {"code": "draft_not_found"})
        if draft.status != "DRAFT": raise HTTPException(409, {"code": "draft_not_editable"})
        draft.status = "DISCARDED"; audit(session, "DRAFT_DISCARD", "admin", draft_id=draft.id, old_version=draft.base_version, summary="丢弃配置草稿"); session.commit()
        return {"id": draft.id, "status": draft.status}
    finally: session.close()


@router.post("/api/admin/analyzer-config/rollback")
def rollback(payload: RollbackInput, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        source = session.scalar(select(AnalyzerConfigVersion).where(AnalyzerConfigVersion.version == payload.version))
        if not source: raise HTTPException(404, {"code": "config_version_not_found"})
        draft = create_draft(session, "admin", source=source, note=payload.change_note or f"从版本 {payload.version} 创建回滚草稿")
        audit(session, "ROLLBACK_DRAFT", "admin", draft_id=draft.id, old_version=payload.version, summary="创建回滚草稿"); session.commit()
        record = publish_draft(session, draft, "admin", payload.if_match)
        return {"version": record.version, "rolled_back_from": payload.version, "draft_id": draft.id}
    except ConfigError as exc: protected_error(exc, 409 if str(exc) == "version_conflict" else 422)
    finally: session.close()


def worker_view(session, instance_id: str):
    if instance_id != WORKER_ID:
        item = session.get(WorkerInstance, instance_id)
        if item is None:
            raise HTTPException(404, {"code": "worker_not_found"})
        active = len(active_leases_for_instance(session, item.id))
        heartbeat_expired = not item.last_heartbeat_at or (now() - item.last_heartbeat_at).total_seconds() > 60
        state = "OFFLINE" if heartbeat_expired else ("BUSY" if active >= item.max_concurrency else item.health)
        return {
            "instance_id": item.id,
            "type": item.worker_type,
            "health": state,
            "health_reason": item.last_error or ("心跳已超时" if state == "OFFLINE" else ("容量已满" if state == "BUSY" else "Worker 已注册")),
            "image_ref": item.image_ref,
            "image_id": item.image_id,
            "toolchain_version": item.toolchain_version,
            "platform_package_version": item.platform_package_version,
            "capabilities": item.capabilities,
            "running_containers": active,
            "max_concurrency": item.max_concurrency,
            "free_slots": max(0, item.max_concurrency - active),
            "queue_count": 0,
            "last_heartbeat": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
            "last_error": item.last_error,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
    config = ensure_configuration(session); reclaim_expired_leases(session); session.commit()
    leases = list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.worker_instance_id == WORKER_ID, WorkerCapacityLease.status == "ACTIVE")))
    queued = len(list(session.scalars(select(AnalysisTask).where(AnalysisTask.status == "QUEUED"))))
    state = "BUSY" if len(leases) >= config.max_concurrency else "READY"
    return {"instance_id": WORKER_ID, "type": "common-analyzer", "health": state, "health_reason": "容量已满" if state == "BUSY" else "健康且有空闲槽位", "image_ref": "solution-advisor-common-analyzer", "capabilities": ["onnx_profile"], "running_containers": len(leases), "max_concurrency": config.max_concurrency, "free_slots": max(0, config.max_concurrency - len(leases)), "queue_count": queued, "last_heartbeat": max((x.last_heartbeat_at for x in leases if x.last_heartbeat_at), default=None), "last_error": None, "updated_at": now().isoformat()}


@router.get("/api/admin/worker-instances")
def workers(request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        values=[worker_view(session, WORKER_ID)]
        for item in session.scalars(select(WorkerInstance).order_by(WorkerInstance.id)):
            active=len(active_leases_for_instance(session, item.id))
            heartbeat_expired = not item.last_heartbeat_at or (now() - item.last_heartbeat_at).total_seconds() > 60
            state = "OFFLINE" if heartbeat_expired else ("BUSY" if active >= item.max_concurrency else item.health)
            values.append({"instance_id":item.id,"type":item.worker_type,"health":state,"health_reason":item.last_error or ("心跳已超时" if state=="OFFLINE" else ("容量已满" if state=="BUSY" else "Worker 已注册")),"image_ref":item.image_ref,"image_id":item.image_id,"toolchain_version":item.toolchain_version,"platform_package_version":item.platform_package_version,"capabilities":item.capabilities,"running_containers":active,"max_concurrency":item.max_concurrency,"free_slots":max(0,item.max_concurrency-active),"queue_count":0,"last_heartbeat":item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,"last_error":item.last_error,"updated_at":item.updated_at.isoformat() if item.updated_at else None})
        return values
    finally: session.close()


@router.get("/api/admin/worker-instances/{instance_id}/capacity")
@router.get("/api/admin/worker-instances/{instance_id}/health")
def capacity(instance_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try: return worker_view(session, instance_id)
    finally: session.close()


@router.get("/api/admin/worker-instances/{instance_id}/leases")
def leases(instance_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        worker_view(session, instance_id)
        return [{"slot_index": x.slot_index, "task_id": x.task_id, "attempt_id": x.attempt_id, "status": x.status, "expires_at": x.expires_at.isoformat(), "remaining_seconds": max(0, int((x.expires_at - now()).total_seconds()))} for x in session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.worker_instance_id.in_(lease_owner_ids(session, instance_id))).order_by(WorkerCapacityLease.created_at.desc()).limit(50))]
    finally: session.close()
