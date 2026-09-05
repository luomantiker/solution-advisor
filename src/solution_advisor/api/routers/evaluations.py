from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select, or_

from solution_advisor.evaluations.service import DemoEvaluationService, DemoTaskError
from solution_advisor.reports.service import flow_report_pdf, flow_report_view_model, report_pdf, report_view_model
from solution_advisor.reports.flow_delivery import (
    create_flow_report_revision,
    latest_flow_report_revision,
    list_flow_report_revisions,
)
from solution_advisor.artifacts.service import ArtifactService
from solution_advisor.artifacts.domain import Artifact, Evidence
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.model_assets.domain import ModelAssetAccess
from solution_advisor.model_assets.domain import ResourceAccessAudit
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationResult, EvaluationTask, EvaluationTaskShare, ReportRevision, TaskSnapshot
from solution_advisor.evaluations.flow_service import EvaluationFlowService, FlowError
from solution_advisor.platforms.domain import PlatformCatalog, PlatformType, UserAccount
from solution_advisor.platforms.service import PlatformRegistry
from solution_advisor.security import ADMIN, SUPER_ADMIN, resolve_principal

router = APIRouter(prefix="/api/v1", tags=["evaluations"])

def _principal(request: Request, authorization: str | None):
    return resolve_principal(request, authorization, "USER", ADMIN, SUPER_ADMIN)

def _owns_task(session, principal, task) -> bool:
    return principal.role in {ADMIN, SUPER_ADMIN} or task.owner_subject == principal.subject or bool(session.scalar(
        select(EvaluationTaskShare).where(EvaluationTaskShare.task_id == task.id,
                                          EvaluationTaskShare.subject == principal.subject)))


def _can_share_task(principal, task) -> bool:
    return principal.role in {ADMIN, SUPER_ADMIN} or task.owner_subject == principal.subject


def _can_delete_task(principal, task) -> bool:
    return _can_share_task(principal, task)


def _can_delete_flow(principal, flow) -> bool:
    return principal.role in {ADMIN, SUPER_ADMIN} or flow.owner_subject == principal.subject


def _can_read_flow(principal, flow) -> bool:
    """A user-visible Flow is private to its owner; admin roles are diagnostic readers."""
    return principal.role in {ADMIN, SUPER_ADMIN} or flow.owner_subject == principal.subject


def _recipient(session, value: str) -> UserAccount | None:
    return session.scalar(select(UserAccount).where(or_(UserAccount.id == value, UserAccount.username == value)))


class ShareInput(BaseModel):
    recipient: str = Field(min_length=1, max_length=128)
    include_model: bool = False


class BatchShareInput(ShareInput):
    task_ids: list[str] = Field(min_length=1, max_length=100)


class CreateDemoTask(BaseModel):
    model_profile_id: str
    mode: str = "DEMO"
    platforms: list[str]

class CreateEvaluationFlow(BaseModel):
    model_profile_id: str
    catalog_ids: list[str] = Field(min_length=1, max_length=8)
    preset: str = Field(default="standard-performance-1.0", pattern=r"^standard-performance-1\.0$")


@router.get("/evaluation-platforms")
def evaluation_platforms(request: Request, authorization: str | None = Header(None)) -> list[dict]:
    """User-facing availability, derived from the governed catalog and Worker state."""
    _principal(request, authorization)
    session = request.app.state.session_factory()
    try:
        catalogs = list(session.scalars(select(PlatformCatalog).order_by(PlatformCatalog.platform_id, PlatformCatalog.version.desc())))
        types = {item.id: item for item in session.scalars(select(PlatformType))}
        catalog_platforms = {catalog.platform_id for catalog in catalogs}
        # Names without a Catalog remain visible as unavailable placeholders.
        platform_ids = ["X5", "S100", "Intel"]
        rows = []
        for catalog in catalogs:
            platform_id = catalog.platform_id
            catalog, binding, worker, reason = PlatformRegistry(session).availability(platform_id, catalog.id)
            # The control plane, rather than a platform-specific UI switch,
            # is the sole admission decision.  A suspended old Release stays
            # visible for provenance but cannot be selected.
            available = reason == "READY"
            if available: status, detail = "AVAILABLE", "已接入并可调度"
            elif catalog.state == "PENDING_INTEGRATION": status, detail = "INTEGRATING", "正在接入，暂不可用"
            elif catalog.state == "AVAILABLE":
                status, detail = "UNAVAILABLE", {"healthy_binding_required": "已接入，但没有健康 Binding", "agent_offline": "HostAgent 离线", "ready_worker_required": "没有 READY Worker"}.get(reason, "已接入，但当前不可调度")
            else: status, detail = "UNAVAILABLE", "平台未发布或已暂停"
            platform_type = types.get(catalog.platform_type_id)
            rows.append({"id": catalog.id, "platform_id": platform_id, "platform_type_id": catalog.platform_type_id,
                         "platform_type_name": platform_type.display_name if platform_type else platform_id, "version": catalog.version,
                         "display_name": catalog.display_name, "available": available, "status": status, "detail": detail,
                         "catalog_state": catalog.state, "binding_id": binding.id if binding else None,
                         "worker_id": worker.id if worker else None})
        for platform_id in platform_ids:
            if platform_id not in catalog_platforms:
                rows.append({"id": f"unmanaged:{platform_id}", "platform_id": platform_id, "platform_type_id": None, "platform_type_name": platform_id, "version": None,
                             "display_name": platform_id, "available": False, "status": "UNAVAILABLE",
                             "detail": "尚未接入可执行能力", "catalog_state": None, "binding_id": None, "worker_id": None})
        return rows
    finally:
        session.close()


@router.post("/evaluation-flows", status_code=201)
def create_flow(payload: CreateEvaluationFlow, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        profile = session.get(ModelProfile, payload.model_profile_id)
        asset = session.get(ModelAsset, profile.model_asset_id) if profile else None
        if not profile or not asset: raise HTTPException(404, {"code": "profile_not_found"})
        if principal.role not in {ADMIN, SUPER_ADMIN} and asset.owner_subject != principal.subject and not session.scalar(select(ModelAssetAccess).where(ModelAssetAccess.model_asset_id == asset.id, ModelAssetAccess.subject == principal.subject)):
            raise HTTPException(403, {"code": "resource_owner_forbidden"})
        try: flow = EvaluationFlowService(session).create(payload.model_profile_id, principal.subject, payload.catalog_ids, payload.preset)
        except FlowError as exc: raise HTTPException(422, {"code": exc.code, "platform_reasons": exc.reasons})
        return EvaluationFlowService(session).payload(flow)
    finally: session.close()


@router.get("/evaluation-flows/{flow_id}")
def get_flow(flow_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow): raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        return EvaluationFlowService(session).payload(flow)
    finally: session.close()


@router.get("/evaluation-workbench")
def evaluation_workbench(request: Request, authorization: str | None = Header(None)) -> dict:
    """Compact, owner-scoped data source for the ordinary-user workbench.

    It intentionally returns only Flow summaries.  Internal task, Worker,
    Binding and Runner identities remain out of the normal workbench view.
    """
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flows = list(session.scalars(select(EvaluationFlow).where(
            EvaluationFlow.owner_subject == principal.subject
        ).order_by(EvaluationFlow.created_at.desc())))
        profiles = {item.id: item for item in session.scalars(select(ModelProfile).where(
            ModelProfile.id.in_([flow.model_profile_id for flow in flows] or [""])
        ))}
        # The model workbench follows the same access policy as the model list:
        # owners and explicitly shared recipients can see their accessible model.
        # It still never exposes another user's Flow or internal execution data.
        assets = {item.id: item for item in session.scalars(
            select(ModelAsset).join(
                ModelAssetAccess, ModelAssetAccess.model_asset_id == ModelAsset.id
            ).where(ModelAssetAccess.subject == principal.subject)
        )}
        flow_rows = []
        for flow in flows:
            payload = EvaluationFlowService(session).payload(flow)
            profile = profiles.get(flow.model_profile_id)
            asset = assets.get(profile.model_asset_id) if profile else None
            flow_rows.append({
                "id": flow.id, "status": payload["status"], "preset": flow.preset,
                "platforms": list(dict.fromkeys(stage["platform"] for stage in payload["stages"])),
                "model_asset_id": asset.id if asset else None,
                "model_name": asset.original_filename if asset else "受控模型",
                "created_at": flow.created_at.isoformat() if flow.created_at else None,
            })
        terminal = {"SUCCEEDED", "PARTIALLY_SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
        return {
            "metrics": {
                "in_progress": sum(item["status"] not in terminal for item in flow_rows),
                "completed": sum(item["status"] in terminal for item in flow_rows),
                "models": len(assets),
                "reports": sum(item["status"] in terminal for item in flow_rows),
            },
            "continue_flows": [item for item in flow_rows if item["status"] not in terminal][:6],
            "recent_flows": flow_rows[:8],
            "recent_reports": [item for item in flow_rows if item["status"] in terminal][:6],
        }
    finally: session.close()


@router.get("/evaluation-flows/{flow_id}/evidence")
def flow_evidence(flow_id: str, request: Request, authorization: str | None = Header(None)) -> list[dict]:
    """Metadata-only Evidence listing, bounded to the current Flow's stages."""
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        tasks = list(session.scalars(select(EvaluationTask).where(EvaluationTask.flow_id == flow.id)))
        task_ids = [task.id for task in tasks]
        if not task_ids:
            return []
        artifacts = {item.id: item for item in session.scalars(select(Artifact).join(
            Evidence, Evidence.artifact_id == Artifact.id
        ).where(Evidence.task_id.in_(task_ids)))}
        return [{
            "id": item.id, "task_id": item.task_id, "platform": item.platform,
            "type": item.evidence_type, "phase": item.phase,
            "sha256": artifacts[item.artifact_id].sha256 if item.artifact_id in artifacts else None,
            "size_bytes": artifacts[item.artifact_id].size_bytes if item.artifact_id in artifacts else None,
            "created_at": item.produced_at.isoformat() if item.produced_at else None,
            "can_download": item.artifact_id in artifacts,
        } for item in session.scalars(select(Evidence).where(Evidence.task_id.in_(task_ids)).order_by(Evidence.produced_at.desc()))]
    finally: session.close()


@router.get("/evaluation-flows/{flow_id}/evidence/{evidence_id}/download")
def download_flow_evidence(flow_id: str, evidence_id: str, request: Request, authorization: str | None = Header(None)):
    from fastapi.responses import Response
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        task_ids = list(session.scalars(select(EvaluationTask.id).where(EvaluationTask.flow_id == flow.id)))
        evidence = session.scalar(select(Evidence).where(Evidence.id == evidence_id, Evidence.task_id.in_(task_ids)))
        artifact = session.get(Artifact, evidence.artifact_id) if evidence else None
        if not evidence or not artifact:
            raise HTTPException(404, {"code": "flow_evidence_not_found"})
        with request.app.state.artifact_storage.open(artifact.uri) as stream:
            payload = stream.read()
        filename = f"{flow.id}-{evidence.platform or 'platform'}-{evidence.evidence_type}"
        return Response(payload, media_type=artifact.content_type,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    finally: session.close()


def _delete_terminal_tasks(session, task_ids: list[str], storage_uris: list[str]) -> None:
    """Delete completed internal stages and only their unreferenced bytes."""
    tasks = [session.get(EvaluationTask, task_id) for task_id in task_ids]
    tasks = [task for task in tasks if task is not None]
    task_ids = [task.id for task in tasks]
    if not task_ids:
        return
    shares = list(session.scalars(select(EvaluationTaskShare).where(EvaluationTaskShare.task_id.in_(task_ids))))
    evidence_rows = list(session.scalars(select(Evidence).where(Evidence.task_id.in_(task_ids))))
    artifact_ids = {item.artifact_id for item in evidence_rows}
    snapshot_ids = {item.snapshot_id for item in tasks if item.snapshot_id}
    for item in session.scalars(select(EvaluationResult).where(EvaluationResult.task_id.in_(task_ids))):
        session.delete(item)
    for item in shares:
        session.delete(item)
    for item in evidence_rows:
        session.delete(item)
    for item in session.scalars(select(ResourceAccessAudit).where(
        ResourceAccessAudit.resource_type == "TASK", ResourceAccessAudit.resource_id.in_(task_ids)
    )):
        session.delete(item)
    for item in tasks:
        session.delete(item)
    session.flush()

    # An explicit shared-model grant is an independent logical reference to
    # deduplicated ONNX bytes.  Deleting the sharer's report must not revoke it
    # or remove the bytes while the recipient still references the model.

    for snapshot_id in snapshot_ids:
        if not session.scalar(select(EvaluationTask.id).where(EvaluationTask.snapshot_id == snapshot_id)):
            snapshot = session.get(TaskSnapshot, snapshot_id)
            if snapshot:
                session.delete(snapshot)
    for artifact_id in artifact_ids:
        if session.scalar(select(Evidence.id).where(Evidence.artifact_id == artifact_id)):
            continue
        if session.scalar(select(ModelAsset.id).where(ModelAsset.artifact_id == artifact_id)):
            continue
        artifact = session.get(Artifact, artifact_id)
        if artifact:
            storage_uris.append(artifact.uri)
            session.delete(artifact)


def delete_terminal_flow_records(session, flow: EvaluationFlow, storage_uris: list[str]) -> None:
    """Delete one terminal Flow and every internal record it exclusively owns.

    This is deliberately shared with model deletion so that a model removal
    cannot leave reports, stage rows or Evidence behind.
    """
    tasks = list(session.scalars(select(EvaluationTask).where(EvaluationTask.flow_id == flow.id)))
    terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
    if any(task.status not in terminal for task in tasks):
        raise ValueError("evaluation_flow_not_terminal")
    report_artifact_ids = {item.pdf_artifact_id for item in session.scalars(
        select(ReportRevision).where(ReportRevision.flow_id == flow.id)
    ) if item.pdf_artifact_id}
    for revision in session.scalars(select(ReportRevision).where(ReportRevision.flow_id == flow.id)):
        session.delete(revision)
    session.flush()
    for artifact_id in report_artifact_ids:
        if session.scalar(select(ReportRevision.id).where(ReportRevision.pdf_artifact_id == artifact_id)):
            continue
        artifact = session.get(Artifact, artifact_id)
        if artifact:
            storage_uris.append(artifact.uri)
            session.delete(artifact)
    _delete_terminal_tasks(session, [task.id for task in tasks], storage_uris)
    session.delete(flow)


@router.delete("/evaluation-flows/{flow_id}", status_code=204)
def delete_evaluation_flow(flow_id: str, request: Request, authorization: str | None = Header(None)):
    """Delete one user-visible completed evaluation and all of its internal stages."""
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    storage_uris: list[str] = []
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_delete_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        tasks = list(session.scalars(select(EvaluationTask).where(EvaluationTask.flow_id == flow.id)))
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
        if any(task.status not in terminal for task in tasks):
            raise HTTPException(409, {"code": "evaluation_flow_not_terminal"})
        delete_terminal_flow_records(session, flow, storage_uris)
        session.commit()
    finally:
        session.close()
    for uri in storage_uris:
        try:
            request.app.state.artifact_storage.delete(uri)
        except Exception:
            pass


@router.get("/evaluation-flows/{flow_id}/report/revisions")
def list_flow_reports(flow_id: str, request: Request, authorization: str | None = Header(None)) -> list[dict]:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        return list_flow_report_revisions(session, flow)
    finally: session.close()


@router.delete("/evaluation-flows/{flow_id}/report/revisions/{version}", status_code=204)
def delete_flow_report_revision(flow_id: str, version: int, request: Request,
                                authorization: str | None = Header(None)):
    """Delete one report version and only its unreferenced PDF artifact.

    The Flow, execution stages and their Evidence are deliberately retained.
    A durable access audit records who performed this destructive operation.
    """
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    storage_uri: str | None = None
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_delete_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        revision = session.scalar(select(ReportRevision).where(
            ReportRevision.flow_id == flow.id, ReportRevision.version == version,
        ))
        if revision is None:
            raise HTTPException(404, {"code": "flow_report_revision_not_found"})
        revision_id, artifact_id = revision.id, revision.pdf_artifact_id
        session.delete(revision)
        session.flush()
        if artifact_id and not session.scalar(select(ReportRevision.id).where(
            ReportRevision.pdf_artifact_id == artifact_id,
        )):
            artifact = session.get(Artifact, artifact_id)
            if artifact:
                storage_uri = artifact.uri
                session.delete(artifact)
        session.add(ResourceAccessAudit(
            resource_type="REPORT_REVISION", resource_id=revision_id,
            action="REPORT_REVISION_DELETED", actor_subject=principal.subject,
            recipient_subject=flow.owner_subject,
        ))
        session.commit()
    finally:
        session.close()
    if storage_uri:
        try:
            request.app.state.artifact_storage.delete(storage_uri)
        except Exception:
            # Storage cleanup can be retried separately; an authorized report
            # deletion must never resurrect the revision or its access.
            pass


@router.post("/evaluation-flows/{flow_id}/report/revisions", status_code=201)
def create_flow_report(flow_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    """Create a new append-only report version from the current Flow facts."""
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        revision = create_flow_report_revision(session, flow)
        session.commit()
        return {"id": revision.id, "version": revision.version, "template_version": revision.template_version,
                "created_at": revision.created_at.isoformat() if revision.created_at else None,
                "message": "已生成新的报告版本；历史版本保持可追溯。"}
    finally: session.close()


@router.get("/evaluation-flows/{flow_id}/report")
def preview_flow_report(flow_id: str, request: Request, authorization: str | None = Header(None), version: int | None = None) -> dict:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        report = flow_report_view_model(session, flow_id, version)
        if report is None: raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        # First preview of a historical/new Flow creates V1.  Subsequent
        # reads always use that immutable snapshot instead of recalculating.
        session.commit()
        return report
    finally: session.close()


@router.get("/evaluation-flows/{flow_id}/report/download")
def download_flow_report(flow_id: str, request: Request, authorization: str | None = Header(None), version: int | None = None):
    from fastapi.responses import Response
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        flow = session.get(EvaluationFlow, flow_id)
        if not flow or not _can_read_flow(principal, flow):
            raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        revision = latest_flow_report_revision(session, flow, version)
        if revision is None:
            raise HTTPException(404, {"code": "flow_report_revision_not_found"})
        report = flow_report_view_model(session, flow_id, revision.version)
        if report is None: raise HTTPException(404, {"code": "evaluation_flow_not_found"})
        artifact = session.get(Artifact, revision.pdf_artifact_id) if revision.pdf_artifact_id else None
        if artifact:
            with request.app.state.artifact_storage.open(artifact.uri) as stream:
                pdf = stream.read()
        else:
            pdf = flow_report_pdf(report)
            artifact = ArtifactService(session, request.app.state.artifact_storage).put(pdf, content_type="application/pdf")
            revision.pdf_artifact_id = artifact.id
            session.commit()
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{flow_id}-report-v{revision.version}.pdf"'})
    finally: session.close()


@router.post("/evaluation-tasks", status_code=201)
def create_task(payload: CreateDemoTask, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    session = request.app.state.session_factory()
    try:
        profile = session.get(ModelProfile, payload.model_profile_id)
        asset = session.get(ModelAsset, profile.model_asset_id) if profile else None
        if profile is None or asset is None: raise HTTPException(404, "Model profile not found")
        if principal.role not in {ADMIN, SUPER_ADMIN} and not session.scalar(select(ModelAssetAccess).where(
            ModelAssetAccess.model_asset_id == asset.id, ModelAssetAccess.subject == principal.subject)):
            raise HTTPException(403, {"code": "resource_owner_forbidden"})
        try:
            task = DemoEvaluationService(session).create(payload.model_profile_id, payload.mode, payload.platforms, principal.subject)
        except DemoTaskError as exc:
            raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"id": task.id, "model_profile_id": task.model_profile_id, "mode": task.mode,
                "platforms": task.platforms, "snapshot_id": task.snapshot_id,
                "mock_notice": "Mock / 不可用于交付结论"}
    finally:
        session.close()


@router.get("/evaluation-tasks")
def list_tasks(request: Request, authorization: str | None = Header(None)) -> list[dict]:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        query = select(EvaluationTask).order_by(EvaluationTask.created_at.desc())
        if principal.role not in {ADMIN, SUPER_ADMIN}:
            shared = select(EvaluationTaskShare.task_id).where(EvaluationTaskShare.subject == principal.subject)
            query = query.where(or_(EvaluationTask.owner_subject == principal.subject, EvaluationTask.id.in_(shared)))
        tasks = list(session.scalars(query))
        return [{"id": task.id, "model_profile_id": task.model_profile_id, "mode": task.mode,
                 "task_kind": task.task_kind, "platforms": task.platforms, "status": task.status,
                 "owner_subject": task.owner_subject,
                 "access": "ADMIN" if principal.role in {ADMIN, SUPER_ADMIN} and task.owner_subject != principal.subject else ("OWNER" if task.owner_subject == principal.subject else "SHARED"),
                "created_at": task.created_at.isoformat() if task.created_at else None} for task in tasks]
    finally: session.close()


@router.get("/evaluation-tasks/{task_id}")
def get_task(task_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    session = request.app.state.session_factory()
    try:
        task = DemoEvaluationService(session).get(task_id)
        if task is None or not _owns_task(session, principal, task):
            raise HTTPException(404, "Evaluation task not found")
        return {"id": task.id, "model_profile_id": task.model_profile_id, "mode": task.mode,
                "task_kind": task.task_kind, "status": task.status, "source_task_id": task.source_task_id,
                "platforms": task.platforms,
                "snapshot_id": task.snapshot_id,
                "owner_subject": task.owner_subject, "can_share": _can_share_task(principal, task),
                "can_delete": task.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"} and _can_delete_task(principal, task),
                "results": [{"platform": r.platform, "status": r.payload["status"], "source": r.source,
                             "fixture_version": r.fixture_version} for r in DemoEvaluationService(session).results(task.id)]}
    finally:
        session.close()


def _share_tasks(session, principal, body: BatchShareInput) -> tuple[str, list[EvaluationTaskShare]]:
    recipient = _recipient(session, body.recipient)
    if not recipient or not recipient.active: raise HTTPException(404, {"code": "share_recipient_not_found"})
    unique_ids = list(dict.fromkeys(body.task_ids))
    tasks = [session.get(EvaluationTask, task_id) for task_id in unique_ids]
    if any(task is None or not _can_share_task(principal, task) for task in tasks):
        raise HTTPException(404, "Evaluation task not found")
    if any(task.status != "SUCCEEDED" for task in tasks):
        raise HTTPException(409, {"code": "evaluation_not_completed"})
    if any(recipient.id == task.owner_subject for task in tasks):
        raise HTTPException(422, {"code": "share_recipient_is_owner"})
    profiles = [session.get(ModelProfile, task.model_profile_id) for task in tasks]
    assets = [session.get(ModelAsset, profile.model_asset_id) if profile else None for profile in profiles]
    if not all(assets) or len({asset.id for asset in assets}) != 1:
        raise HTTPException(422, {"code": "share_tasks_must_belong_to_same_model"})
    shares: list[EvaluationTaskShare] = []
    for task in tasks:
        share = session.scalar(select(EvaluationTaskShare).where(EvaluationTaskShare.task_id == task.id,
                                                                   EvaluationTaskShare.subject == recipient.id))
        if share:
            if body.include_model and not share.include_model:
                share.include_model = True
            else:
                shares.append(share)
                continue
        else:
            share = EvaluationTaskShare(task_id=task.id, subject=recipient.id, shared_by=principal.subject,
                                        include_model=body.include_model)
            session.add(share)
        shares.append(share)
        session.add(ResourceAccessAudit(resource_type="TASK", resource_id=task.id, action="SHARED",
                                        actor_subject=principal.subject, recipient_subject=recipient.id))
    if body.include_model:
        asset = assets[0]
        grant = session.scalar(select(ModelAssetAccess).where(ModelAssetAccess.model_asset_id == asset.id,
                                                                ModelAssetAccess.subject == recipient.id))
        if grant is None:
            session.add(ModelAssetAccess(model_asset_id=asset.id, subject=recipient.id, access_kind="SHARED",
                                         granted_by=principal.subject))
    return recipient.id, shares


@router.post("/evaluation-task-shares", status_code=201)
def share_tasks(body: BatchShareInput, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        recipient, shares = _share_tasks(session, principal, body); session.commit()
        return {"recipient": recipient, "task_ids": [share.task_id for share in shares],
                "include_model": body.include_model}
    finally: session.close()


@router.post("/evaluation-tasks/{task_id}/shares", status_code=201)
def share_task(task_id: str, body: ShareInput, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        recipient, shares = _share_tasks(session, principal, BatchShareInput(recipient=body.recipient,
                                                                              include_model=body.include_model,
                                                                              task_ids=[task_id]))
        session.commit(); share = shares[0]
        return {"task_id": share.task_id, "recipient": recipient, "access": "SHARED", "include_model": share.include_model}
    finally: session.close()


@router.get("/evaluation-tasks/{task_id}/shares")
def list_task_shares(task_id: str, request: Request, authorization: str | None = Header(None)) -> list[dict]:
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        task = DemoEvaluationService(session).get(task_id)
        if not task or not _can_share_task(principal, task): raise HTTPException(404, "Evaluation task not found")
        rows = session.execute(
            select(EvaluationTaskShare, UserAccount.username)
            .outerjoin(UserAccount, UserAccount.id == EvaluationTaskShare.subject)
            .where(EvaluationTaskShare.task_id == task.id)
            .order_by(EvaluationTaskShare.created_at.asc())
        ).all()
        return [{"recipient": share.subject, "username": username, "shared_by": share.shared_by,
                 "include_model": share.include_model,
                 "created_at": share.created_at.isoformat() if share.created_at else None} for share, username in rows]
    finally: session.close()


@router.delete("/evaluation-tasks/{task_id}/shares/{recipient}", status_code=204)
def revoke_task_share(task_id: str, recipient: str, request: Request, authorization: str | None = Header(None)):
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    try:
        task = DemoEvaluationService(session).get(task_id)
        if not task or not _can_share_task(principal, task): raise HTTPException(404, "Evaluation task not found")
        share = session.scalar(select(EvaluationTaskShare).where(EvaluationTaskShare.task_id == task.id,
                                                                   EvaluationTaskShare.subject == recipient))
        if not share: raise HTTPException(404, {"code": "task_share_not_found"})
        profile = session.get(ModelProfile, task.model_profile_id)
        asset = session.get(ModelAsset, profile.model_asset_id) if profile else None
        session.delete(share); session.flush()
        if share.include_model and asset:
            still_included = session.scalar(
                select(EvaluationTaskShare).join(EvaluationTask, EvaluationTask.id == EvaluationTaskShare.task_id)
                .join(ModelProfile, ModelProfile.id == EvaluationTask.model_profile_id)
                .where(EvaluationTaskShare.subject == recipient, EvaluationTaskShare.include_model.is_(True),
                       ModelProfile.model_asset_id == asset.id)
            )
            grant = session.scalar(select(ModelAssetAccess).where(ModelAssetAccess.model_asset_id == asset.id,
                                                                    ModelAssetAccess.subject == recipient))
            if not still_included and grant and grant.access_kind == "SHARED": session.delete(grant)
        session.add(ResourceAccessAudit(resource_type="TASK", resource_id=task.id, action="REVOKED",
                                                                actor_subject=principal.subject, recipient_subject=recipient)); session.commit()
    finally: session.close()


@router.delete("/evaluation-tasks/{task_id}", status_code=204)
def delete_evaluation_task(task_id: str, request: Request, authorization: str | None = Header(None)):
    """Delete a terminal report, cascading the completed internal X5 stages."""
    principal = _principal(request, authorization); session = request.app.state.session_factory()
    storage_uris: list[str] = []
    try:
        task = DemoEvaluationService(session).get(task_id)
        if not task or not _can_delete_task(principal, task):
            raise HTTPException(404, "Evaluation task not found")
        if task.flow_id:
            raise HTTPException(409, {"code": "evaluation_flow_delete_required"})
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
        if task.status not in terminal:
            raise HTTPException(409, {"code": "evaluation_not_terminal"})
        dependent_tasks = list(session.scalars(select(EvaluationTask).where(EvaluationTask.source_task_id == task.id)))
        if dependent_tasks and not (task.mode == "REAL" and task.task_kind == "X5_COMPILE"):
            raise HTTPException(409, {"code": "evaluation_has_dependent_tasks"})
        if any(item.status not in terminal for item in dependent_tasks):
            raise HTTPException(409, {"code": "x5_evaluation_stage_running"})
        tasks_to_delete = [task, *dependent_tasks]
        _delete_terminal_tasks(session, [item.id for item in tasks_to_delete], storage_uris)
        session.commit()
    finally:
        session.close()
    for uri in storage_uris:
        try:
            request.app.state.artifact_storage.delete(uri)
        except Exception:
            # The logical report is already gone; a later storage sweep may
            # reclaim a byte object if the backend is temporarily unavailable.
            pass


@router.get("/reports/{task_id}")
def preview_report(task_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    session = request.app.state.session_factory()
    try:
        task = DemoEvaluationService(session).get(task_id)
        if task is None or not _owns_task(session, principal, task): raise HTTPException(404, "Evaluation task not found")
        report = report_view_model(session, task_id)
        if report is None:
            raise HTTPException(404, "Evaluation task not found")
        return report
    finally:
        session.close()


@router.get("/reports/{task_id}/download")
def download_report(task_id: str, request: Request, authorization: str | None = Header(None)):
    from fastapi.responses import Response
    session = request.app.state.session_factory()
    try:
        principal = _principal(request, authorization)
        task = DemoEvaluationService(session).get(task_id)
        if task is None or not _owns_task(session, principal, task): raise HTTPException(404, "Evaluation task not found")
        report = report_view_model(session, task_id)
        if report is None:
            raise HTTPException(404, "Evaluation task not found")
        pdf = report_pdf(report)
        suffix = "real-board-performance" if report.get("task_kind") == "REAL_BOARD_SMOKE" else (
            "real-compile" if report["mode"] == "REAL" else "mock"
        )
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{task_id}-{suffix}.pdf"'})
    finally:
        session.close()
