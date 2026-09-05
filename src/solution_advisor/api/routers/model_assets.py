from __future__ import annotations

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile, status
from sqlalchemy import or_, select
import hashlib
import tempfile
from pathlib import Path

from solution_advisor.model_assets.service import ModelAssetService
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationResult, EvaluationTask, EvaluationTaskShare
from solution_advisor.artifacts.domain import Artifact
from solution_advisor.common_analyzer.domain import AnalysisEvent, AnalysisTask
from solution_advisor.system_settings.service import model_deletion_enabled
from solution_advisor.evaluations.flow_service import EvaluationFlowService
from solution_advisor.platforms.domain import UserAccount
from solution_advisor.common_analyzer.service import AnalysisService
from solution_advisor.security import ADMIN, SUPER_ADMIN, resolve_principal

router = APIRouter(prefix="/api/v1", tags=["model-assets"])


def _service(request: Request) -> ModelAssetService:
    return ModelAssetService(
        request.app.state.session_factory(),
        request.app.state.artifact_storage,
        request.app.state.analyzer_version,
    )


def _profile_response(profile) -> dict:
    return {
        "id": profile.id,
        "model_asset_id": profile.model_asset_id,
        "onnx_sha256": profile.onnx_sha256,
        "analyzer_version": profile.analyzer_version,
        **profile.analysis,
    }

def _principal(request: Request, authorization: str | None):
    return resolve_principal(request, authorization, "USER", ADMIN, SUPER_ADMIN)

def _model_access(service, principal, asset):
    if principal.role in {ADMIN, SUPER_ADMIN}: return "ADMIN"
    record = service.access_for(asset, principal.subject)
    return record.access_kind if record else None


def _shared_results(session, asset_id: str, subject: str):
    return session.execute(
        select(EvaluationTaskShare, UserAccount.display_name)
        .join(EvaluationTask, EvaluationTask.id == EvaluationTaskShare.task_id)
        .join(ModelProfile, ModelProfile.id == EvaluationTask.model_profile_id)
        .outerjoin(UserAccount, UserAccount.id == EvaluationTaskShare.shared_by)
        .where(ModelProfile.model_asset_id == asset_id, EvaluationTaskShare.subject == subject)
    ).all()


def _asset_view(service, principal, asset: ModelAsset) -> dict | None:
    if principal.role in {ADMIN, SUPER_ADMIN}:
        return {"access": "ADMIN", "shared_by": [], "can_download_model": True, "can_create_task": True,
                # Super administrators manage the global retention policy, so
                # legacy model rows that predate per-user access grants must
                # not become undeletable merely because they lack a grant.
                "can_delete_model": principal.role == SUPER_ADMIN and model_deletion_enabled(service.session)}
    grant = service.access_for(asset, principal.subject)
    shared = _shared_results(service.session, asset.id, principal.subject)
    owns_report = bool(service.session.scalar(
        select(EvaluationTask.id).join(ModelProfile, ModelProfile.id == EvaluationTask.model_profile_id).where(
            EvaluationTask.owner_subject == principal.subject, ModelProfile.model_asset_id == asset.id)))
    if grant is None and not shared and not owns_report:
        return None
    names = sorted({name or share.shared_by for share, name in shared})
    if grant and grant.access_kind == "OWNER":
        access = "OWNER"
    elif grant:
        access = "SHARED_WITH_MODEL"
    elif owns_report:
        access = "OWN_RESULT_ONLY"
    else:
        access = "SHARED_RESULT_ONLY"
    return {"access": access, "shared_by": names, "can_download_model": grant is not None,
            "can_create_task": grant is not None,
            # A recipient may remove their own model reference, but cannot
            # delete another user's logical model entry.  The global policy is
            # deliberately checked again by the DELETE endpoint.
            "can_delete_model": bool(grant) and model_deletion_enabled(service.session)}


def _progress(status: str) -> dict:
    labels = {"QUEUED": (0, "等待执行"), "CLAIMED": (15, "已分配执行器"), "RUNNING": (50, "执行中"),
              "SUCCEEDED": (100, "已完成"), "FAILED": (100, "执行失败"), "CANCELLED": (100, "已取消"),
              "TIMEOUT": (100, "执行超时")}
    percent, label = labels.get(status, (0, status))
    return {"percent": percent, "label": label,
            "completed": status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}}


def _workflow_progress(session, task: EvaluationTask) -> dict:
    """Summarize controlled X5 stages as the one evaluation the user created."""
    compile_progress = _progress(task.status)
    if task.mode != "REAL" or task.task_kind != "X5_COMPILE":
        return {**compile_progress, "stages": [{"name": "评估", "status": task.status}]}
    if task.status != "SUCCEEDED":
        return {**compile_progress, "label": f"编译{compile_progress['label']}",
                "stages": [{"name": "编译", "status": task.status}]}
    board = session.scalar(select(EvaluationTask).where(
        EvaluationTask.source_task_id == task.id, EvaluationTask.task_kind == "REAL_BOARD_SMOKE"
    ).order_by(EvaluationTask.created_at.desc()))
    if board:
        board_progress = _progress(board.status)
        labels = {
            "QUEUED": (60, "编译完成，等待板端性能评测", False),
            "CLAIMED": (70, "编译完成，板端性能评测已分配", False),
            "RUNNING": (80, "编译完成，正在进行板端性能评测", False),
            "SUCCEEDED": (100, "评估完成（编译与板端性能）", True),
            "FAILED": (100, "板端性能评测失败（编译已完成）", True),
            "CANCELLED": (100, "板端性能评测已取消（编译已完成）", True),
            "TIMEOUT": (100, "板端性能评测超时（编译已完成）", True),
        }
        percent, label, completed = labels.get(board.status, (board_progress["percent"], board_progress["label"], board_progress["completed"]))
        return {"percent": percent, "label": label, "completed": completed,
                "stages": [{"name": "编译", "status": "SUCCEEDED"},
                           {"name": "板端性能", "status": board.status, "task_id": board.id,
                            "error_code": board.error_code}]}
    result = session.scalar(select(EvaluationResult).where(EvaluationResult.task_id == task.id, EvaluationResult.source == "REAL"))
    reason_code = (result.platform_result.get("board_stage", {}).get("reason_code") if result else None)
    if reason_code:
        return {"percent": 100, "label": "编译完成，板端性能未执行", "completed": True,
                "stages": [{"name": "编译", "status": "SUCCEEDED"},
                           {"name": "板端性能", "status": "NOT_EXECUTED", "error_code": reason_code}]}
    return {"percent": 55, "label": "编译完成，正在创建板端性能阶段", "completed": False,
            "stages": [{"name": "编译", "status": "SUCCEEDED"}, {"name": "板端性能", "status": "QUEUED"}]}


def _task_payload(session, principal, task: EvaluationTask, *, access: str, shared_by: str | None = None, include_model: bool = False) -> dict:
    source = session.scalar(select(EvaluationResult.source).where(EvaluationResult.task_id == task.id).limit(1))
    workflow = _workflow_progress(session, task)
    progress = {key: value for key, value in workflow.items() if key != "stages"}
    return {"id": task.id, "resource_kind": "TASK", "model_profile_id": task.model_profile_id, "mode": task.mode,
            "task_kind": task.task_kind, "platforms": task.platforms, "status": task.status,
            "owner_subject": task.owner_subject, "access": access, "shared_by": shared_by,
            "include_model": include_model, "source": source or "待执行", "progress": progress,
            "workflow": {"stages": workflow["stages"]},
            "can_share": task.status == "SUCCEEDED" and (principal.role in {ADMIN, SUPER_ADMIN} or task.owner_subject == principal.subject),
            "can_delete": task.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"} and (
                principal.role in {ADMIN, SUPER_ADMIN} or task.owner_subject == principal.subject
            ),
            "created_at": task.created_at.isoformat() if task.created_at else None}


def _flow_payload(session, principal, flow: EvaluationFlow, *, access: str) -> dict:
    payload = EvaluationFlowService(session).payload(flow)
    platforms = list(dict.fromkeys(stage["platform"] for stage in payload["stages"]))
    status = payload["status"]
    progress = _progress(status)
    labels = {
        "SUCCEEDED": "评估完成（所有平台）",
        "PARTIALLY_SUCCEEDED": "评估完成（部分平台成功）",
        "FAILED": "评估失败",
        "CANCELLED": "评估已取消",
        "TIMEOUT": "评估超时",
    }
    progress["label"] = labels.get(status, progress["label"])
    progress["completed"] = status in {"SUCCEEDED", "PARTIALLY_SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
    if progress["completed"]:
        progress["percent"] = 100
    return {
        "id": flow.id, "resource_kind": "FLOW", "model_profile_id": flow.model_profile_id,
        "mode": "REAL", "task_kind": "EVALUATION_FLOW", "platforms": platforms,
        "status": status, "owner_subject": flow.owner_subject, "access": access,
        "shared_by": None, "include_model": False, "source": "REAL", "progress": progress,
        "workflow": {"stages": [{"name": stage["kind"], "status": stage["status"], "task_id": stage["id"],
                                   "error_code": stage["error_code"]} for stage in payload["stages"]]},
        "can_share": False,
        "can_delete": progress["completed"] and (principal.role in {ADMIN, SUPER_ADMIN} or flow.owner_subject == principal.subject),
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
    }


@router.post("/model-assets", status_code=status.HTTP_201_CREATED)
async def upload_model_asset(request: Request, file: UploadFile = File(...), authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    limit = request.app.state.settings.upload_max_bytes; total = 0; digest = hashlib.sha256()
    request.app.state.settings.upload_temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=request.app.state.settings.upload_temp_root, delete=True) as received:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit: raise HTTPException(413, detail={"code": "upload_too_large"})
            digest.update(chunk); received.write(chunk)
        received.flush(); received.seek(0); payload = received.read()
    service = _service(request)
    try:
        asset, asset_reused = service.register(file.filename or "upload.onnx", payload, principal.subject)
        task = AnalysisService(service.session, request.app.state.artifact_storage, request.app.state.analysis_queue).create(asset)
    finally:
        service.session.close()
    return {
        "asset": {
            "id": asset.id,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
            "original_filename": asset.original_filename,
        },
        "analysis_task": {"id": task.id, "status": task.status, "sha256": digest.hexdigest(), "size_bytes": total},
        "reused": {"asset": asset_reused},
    }


@router.get("/model-assets")
def list_model_assets(request: Request, authorization: str | None = Header(None)) -> list[dict]:
    principal = _principal(request, authorization)
    service = _service(request)
    try:
        assets = service.list_assets(None if principal.role in {ADMIN, SUPER_ADMIN} else principal.subject)
        if principal.role not in {ADMIN, SUPER_ADMIN}:
            result_assets = service.session.scalars(
                select(ModelAsset).join(ModelProfile, ModelProfile.model_asset_id == ModelAsset.id)
                .join(EvaluationTask, EvaluationTask.model_profile_id == ModelProfile.id)
                .join(EvaluationTaskShare, EvaluationTaskShare.task_id == EvaluationTask.id)
                .where(or_(EvaluationTaskShare.subject == principal.subject,
                           EvaluationTask.owner_subject == principal.subject))
            )
            assets = list({asset.id: asset for asset in [*assets, *result_assets]}.values())
        rows = []
        for asset in assets:
            view = _asset_view(service, principal, asset)
            if view:
                profile = service.get_profile_for_asset(asset)
                rows.append({"id": asset.id, "sha256": asset.sha256, "size_bytes": asset.size_bytes,
                             "original_filename": asset.original_filename,
                             "created_at": asset.created_at.isoformat() if asset.created_at else None,
                             "profile": ({"id": profile.id, "analyzer_version": profile.analyzer_version,
                                          "summary": profile.analysis.get("summary", {})}
                                         if profile and view["can_create_task"] else None), **view})
        return sorted(rows, key=lambda item: item["id"], reverse=True)
    finally:
        service.session.close()


@router.get("/model-assets/{asset_id}")
def get_model_asset(asset_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    service = _service(request)
    try:
        asset = service.get_asset(asset_id)
        view = _asset_view(service, principal, asset) if asset else None
        if asset is None or not view:
            raise HTTPException(status_code=404, detail="Model asset not found")
        profile = service.get_profile_for_asset(asset)
        return {
            "id": asset.id,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
            "original_filename": asset.original_filename,
            **view,
            "can_share_results": view["access"] in {"OWNER", "ADMIN"},
            "profile": None if profile is None or not view["can_download_model"] else {
                "id": profile.id,
                "analyzer_version": profile.analyzer_version,
                "summary": profile.analysis["summary"],
            },
        }
    finally:
        service.session.close()


@router.delete("/model-assets/{asset_id}")
def delete_model_asset(asset_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    """Remove a model reference and its completed evaluations.

    Model bytes are globally deduplicated.  They are only deleted when the
    last logical reference disappears *and* no evaluation still refers to the
    profile.  This prevents one user's cleanup from breaking another user's
    shared model or historical work.
    """
    principal = _principal(request, authorization)
    service = _service(request); session = service.session
    storage_uris: list[str] = []
    try:
        if not model_deletion_enabled(session):
            raise HTTPException(403, {"code": "evaluated_model_deletion_disabled", "message": "系统设置未允许删除已评测模型"})
        asset = service.get_asset(asset_id)
        if asset is None:
            raise HTTPException(404, {"code": "model_asset_not_found"})
        grant = service.access_for(asset, principal.subject)
        global_removal = principal.role == SUPER_ADMIN
        if grant is None and not global_removal:
            raise HTTPException(403, {"code": "model_delete_not_owner", "message": "只能删除自己引用的模型"})

        profiles = list(session.scalars(select(ModelProfile).where(ModelProfile.model_asset_id == asset.id)))
        profile_ids = [profile.id for profile in profiles]
        flow_query = select(EvaluationFlow).where(EvaluationFlow.model_profile_id.in_(profile_ids or [""]))
        task_query = select(EvaluationTask).where(
            EvaluationTask.model_profile_id.in_(profile_ids or [""]), EvaluationTask.flow_id.is_(None),
        )
        if not global_removal:
            flow_query = flow_query.where(EvaluationFlow.owner_subject == principal.subject)
            task_query = task_query.where(EvaluationTask.owner_subject == principal.subject)
        flows = list(session.scalars(flow_query))
        standalone_tasks = list(session.scalars(task_query))
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
        if any(task.status not in terminal for flow in flows for task in session.scalars(
            select(EvaluationTask).where(EvaluationTask.flow_id == flow.id)
        )) or any(task.status not in terminal for task in standalone_tasks):
            raise HTTPException(409, {"code": "model_evaluation_not_terminal", "message": "存在正在执行的评估，请先等待结束或取消后再删除模型"})

        # Keep all deletion rules in the Flow endpoint helper rather than
        # reimplementing Evidence/PDF cleanup here.
        from solution_advisor.api.routers.evaluations import _delete_terminal_tasks, delete_terminal_flow_records
        for flow in flows:
            delete_terminal_flow_records(session, flow, storage_uris)
        _delete_terminal_tasks(session, [task.id for task in standalone_tasks], storage_uris)

        # A recipient removing their own reference must no longer retain
        # reports shared only through it. A global super-admin removal clears
        # every share and logical reference for this model.
        share_query = select(EvaluationTaskShare).where(
            EvaluationTaskShare.task_id.in_(select(EvaluationTask.id).where(EvaluationTask.model_profile_id.in_(profile_ids or [""]))),
        )
        if not global_removal:
            share_query = share_query.where(EvaluationTaskShare.subject == principal.subject)
        for share in session.scalars(share_query):
            session.delete(share)
        if global_removal:
            for access in session.scalars(select(ModelAssetAccess).where(ModelAssetAccess.model_asset_id == asset.id)):
                session.delete(access)
        else:
            session.delete(grant)
        session.flush()

        references_left = bool(session.scalar(select(ModelAssetAccess.id).where(ModelAssetAccess.model_asset_id == asset.id)))
        remaining_work = bool(session.scalar(select(EvaluationTask.id).where(EvaluationTask.model_profile_id.in_(profile_ids or [""])))) or bool(
            session.scalar(select(EvaluationFlow.id).where(EvaluationFlow.model_profile_id.in_(profile_ids or [""])))
        )
        physical_deleted = False
        if not references_left and not remaining_work:
            analysis_tasks = list(session.scalars(select(AnalysisTask).where(AnalysisTask.model_asset_id == asset.id)))
            for analysis_task in analysis_tasks:
                for event in session.scalars(select(AnalysisEvent).where(AnalysisEvent.task_id == analysis_task.id)):
                    session.delete(event)
                session.delete(analysis_task)
            for profile in profiles:
                session.delete(profile)
            model_artifact = session.get(Artifact, asset.artifact_id) if asset.artifact_id else None
            session.delete(asset)
            session.flush()
            if model_artifact:
                storage_uris.append(model_artifact.uri)
                session.delete(model_artifact)
            physical_deleted = True
        session.commit()
    finally:
        session.close()
    for uri in set(storage_uris):
        try:
            request.app.state.artifact_storage.delete(uri)
        except Exception:
            pass
    return {"deleted": True, "physical_model_deleted": physical_deleted,
            "message": (
                "已按全局管理员权限删除模型、全部相关评估记录和 ONNX 文件。" if global_removal else
                ("已删除该账号的模型引用及相关评估记录。" if not physical_deleted else "已删除模型、相关评估记录和 ONNX 文件。")
            )}


@router.get("/model-profiles/{profile_id}")
def get_model_profile(profile_id: str, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _principal(request, authorization)
    service = _service(request)
    try:
        profile = service.get_profile(profile_id)
        asset = service.get_asset(profile.model_asset_id) if profile else None
        view = _asset_view(service, principal, asset) if asset else None
        if profile is None or asset is None or not view or not view["can_download_model"]:
            raise HTTPException(status_code=404, detail="Model profile not found")
        return _profile_response(profile)
    finally:
        service.session.close()


@router.get("/model-assets/{asset_id}/download")
def download_model(asset_id: str, request: Request, authorization: str | None = Header(None)):
    from fastapi.responses import Response
    principal = _principal(request, authorization); service = _service(request); session = service.session
    try:
        asset = service.get_asset(asset_id); view = _asset_view(service, principal, asset) if asset else None
        if asset is None or not view: raise HTTPException(404, "Model asset not found")
        if not view["can_download_model"]: raise HTTPException(403, {"code": "model_download_not_shared"})
        if not asset.artifact_id: raise HTTPException(404, "Model binary not found")
        from solution_advisor.artifacts.domain import Artifact
        artifact = session.get(Artifact, asset.artifact_id)
        if not artifact: raise HTTPException(404, "Model binary not found")
        filename = Path(asset.original_filename).name.replace('"', "") or "model.onnx"
        with request.app.state.artifact_storage.open(artifact.uri) as stream: payload = stream.read()
        return Response(payload, media_type="application/onnx", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    finally: session.close()


@router.get("/model-assets/{asset_id}/evaluation-tasks")
def list_model_tasks(asset_id: str, request: Request, authorization: str | None = Header(None)) -> list[dict]:
    principal = _principal(request, authorization); service = _service(request); session = service.session
    try:
        asset = service.get_asset(asset_id); view = _asset_view(service, principal, asset) if asset else None
        if asset is None or not view: raise HTTPException(404, "Model asset not found")
        query = select(EvaluationTask).join(ModelProfile, ModelProfile.id == EvaluationTask.model_profile_id).where(
            ModelProfile.model_asset_id == asset.id, EvaluationTask.source_task_id.is_(None),
            EvaluationTask.flow_id.is_(None)).order_by(EvaluationTask.created_at.desc())
        flow_query = select(EvaluationFlow).join(ModelProfile, ModelProfile.id == EvaluationFlow.model_profile_id).where(
            ModelProfile.model_asset_id == asset.id).order_by(EvaluationFlow.created_at.desc())
        if principal.role in {ADMIN, SUPER_ADMIN}:
            rows = [_task_payload(session, principal, task, access="ADMIN") for task in session.scalars(query)]
            rows.extend(_flow_payload(session, principal, flow, access="ADMIN") for flow in session.scalars(flow_query))
            return sorted(rows, key=lambda item: item["created_at"] or "", reverse=True)
        own = list(session.scalars(query.where(EvaluationTask.owner_subject == principal.subject)))
        own_flows = list(session.scalars(flow_query.where(EvaluationFlow.owner_subject == principal.subject)))
        shared = session.execute(
            select(EvaluationTask, EvaluationTaskShare, UserAccount.display_name)
            .join(EvaluationTaskShare, EvaluationTaskShare.task_id == EvaluationTask.id)
            .outerjoin(UserAccount, UserAccount.id == EvaluationTaskShare.shared_by)
            .join(ModelProfile, ModelProfile.id == EvaluationTask.model_profile_id)
            .where(ModelProfile.model_asset_id == asset.id, EvaluationTaskShare.subject == principal.subject)
            .order_by(EvaluationTask.created_at.desc())
        ).all()
        rows = {task.id: _task_payload(session, principal, task, access="OWNER") for task in own}
        rows.update({flow.id: _flow_payload(session, principal, flow, access="OWNER") for flow in own_flows})
        for task, share, name in shared:
            rows.setdefault(task.id, _task_payload(session, principal, task, access="SHARED", shared_by=name or share.shared_by,
                                                    include_model=share.include_model))
        return sorted(rows.values(), key=lambda item: item["created_at"] or "", reverse=True)
    finally: session.close()
