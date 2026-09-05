from io import BytesIO
from pathlib import Path
import tempfile
import json

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from solution_advisor.evaluations.x5_service import X5RealError, X5RealService
from solution_advisor.evaluations.domain import EvaluationTask, EvaluationResult, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.artifacts.domain import Artifact, EvidencePhase, EvidenceType
from solution_advisor.artifacts.service import ArtifactService, EvidenceService
from sqlalchemy import select
from solution_advisor.artifacts.domain import Evidence
from solution_advisor.api.routers.workers import worker_auth
from solution_advisor.api.routers.analysis import admin
from solution_advisor.workers.x5_profile_parser import parse_x5_perf_profile
from solution_advisor.evaluations.x5_performance_advice import build_x5_performance_advice
from solution_advisor.platforms.domain import PlatformWorker

router=APIRouter(tags=["x5-real"])
class Create(BaseModel):
    model_profile_id: str
    catalog_id: str | None = None
class CreateBoardSmoke(BaseModel): compiled_task_id: str
@router.post("/api/admin/x5-real-tasks",status_code=201)
def create(body:Create,request:Request,authorization:str|None=Header(None)):
    principal=admin(request,authorization);s=request.app.state.session_factory()
    try:
        try:t=X5RealService(s).create(body.model_profile_id, principal.subject, body.catalog_id)
        except X5RealError as e:raise HTTPException(422,{"code":str(e)})
        return {"id":t.id,"mode":"REAL","status":t.status,"platform":"X5","notice":"编译事实不等于板端验证；性能、精度、稳定性和推荐部署未验证。"}
    finally:s.close()


@router.post("/api/admin/x5-board-smoke-tasks", status_code=201)
def create_board_smoke(body: CreateBoardSmoke, request: Request, authorization: str | None = Header(None)):
    principal=admin(request, authorization); session = request.app.state.session_factory()
    try:
        try:
            task = X5RealService(session).create_board_smoke(body.compiled_task_id, principal.subject)
        except X5RealError as exc:
            raise HTTPException(422, {"code": str(exc)})
        return {"id": task.id, "mode": "REAL", "task_kind": "REAL_BOARD_SMOKE", "status": task.status,
                "source_task_id": task.source_task_id,
                "notice": "仅板端加载与一次受控 Runtime 调用；性能、精度、稳定性、功耗和推荐部署未验证。"}
    finally:
        session.close()
@router.get("/api/admin/x5-real-tasks/{task_id}")
def detail(task_id:str,request:Request,authorization:str|None=Header(None)):
    admin(request,authorization);s=request.app.state.session_factory()
    try:
        t=s.get(EvaluationTask,task_id)
        if not t or t.mode!="REAL":raise HTTPException(404,{"code":"real_task_not_found"})
        r=s.query(EvaluationResult).filter_by(task_id=t.id,source="REAL").first()
        snapshot=s.get(TaskSnapshot,t.snapshot_id) if t.snapshot_id else None
        return {"id":t.id,"status":t.status,"task_kind":t.task_kind,"source_task_id":t.source_task_id,"attempts":t.attempts,"error_code":t.error_code,"worker_instance_id":t.worker_instance_id,"platform_governance":snapshot.platform_governance if snapshot else {},"result":r.platform_result if r else None,"notice":"性能仅在存在原始 profile 时以板端测得值展示；精度、稳定性、功耗和推荐部署：NOT_VERIFIED"}
    finally:s.close()


@router.post("/api/admin/x5-board-smoke-tasks/{task_id}/parse-performance")
def parse_board_performance(task_id: str, request: Request, authorization: str | None = Header(None)):
    """Derive a versioned performance ViewModel from retained raw Evidence.

    It does not invoke the board or alter the immutable raw artifacts.
    """
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        task = session.get(EvaluationTask, task_id)
        result = session.query(EvaluationResult).filter_by(task_id=task_id, source="REAL").first()
        if not task or task.task_kind != "REAL_BOARD_SMOKE" or not result:
            raise HTTPException(404, {"code": "board_smoke_result_not_found"})
        evidence_rows = session.scalars(select(Evidence).where(
            Evidence.task_id == task_id, Evidence.evidence_type == EvidenceType.BOARD_LOG.value)).all()
        if not evidence_rows:
            raise HTTPException(422, {"code": "board_profile_evidence_not_found"})
        preflight = {}
        with tempfile.TemporaryDirectory(prefix="x5-profile-") as directory:
            root = Path(directory)
            for index, evidence in enumerate(evidence_rows):
                artifact = session.get(Artifact, evidence.artifact_id)
                with request.app.state.artifact_storage.open(artifact.uri) as stream:
                    (root / f"profile-{index}.json").write_bytes(stream.read())
            performance = parse_x5_perf_profile(root)
            preflight_evidence = session.scalar(select(Evidence).where(
                Evidence.task_id == task_id, Evidence.evidence_type == EvidenceType.X5_BOARD_PREFLIGHT.value))
            if preflight_evidence:
                artifact = session.get(Artifact, preflight_evidence.artifact_id)
                with request.app.state.artifact_storage.open(artifact.uri) as stream:
                    try:
                        preflight = json.loads(stream.read())
                    except (TypeError, ValueError):
                        preflight = {}
        performance["environment"] = {"system": preflight.get("system", "NOT_COLLECTED"),
                                      "runtime_version": preflight.get("runtime", "NOT_COLLECTED"),
                                      "bpu_access": preflight.get("bpu_access", "NOT_COLLECTED"),
                                      **(result.platform_result.get("runtime") or {})}
        X5RealService(session)._attach_compile_cpu_allocation(task, {"performance": performance})
        performance["guidance"] = build_x5_performance_advice(performance)
        updated = dict(result.platform_result); updated["performance"] = performance
        updated.setdefault("extensions", {"accuracy": {"status": "NOT_VERIFIED", "extension_point": "versioned_inputs_and_output_comparison"},
                                            "power": {"status": "NOT_VERIFIED", "extension_point": "board_power_sampler"}})
        updated.setdefault("boundaries", {})["performance"] = performance["status"]
        result.platform_result = updated; result.payload = updated
        session.commit()
        return {"task_id": task_id, "performance": performance, "notice": "已从既有 profile Evidence 解析；未调用板端。"}
    finally:
        session.close()


@router.post("/api/admin/x5-real-tasks/{task_id}/cancel")
def cancel(task_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try:
            task = X5RealService(session).cancel(task_id)
        except X5RealError as exc:
            raise HTTPException(409, {"code": str(exc)})
        return {"id": task.id, "status": task.status, "notice": "仅取消编译任务；未执行板端操作。"}
    finally:
        session.close()


@router.post("/api/admin/x5-real-tasks/{task_id}/retry")
def retry(task_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try:
            task = X5RealService(session).retry(task_id)
        except X5RealError as exc:
            raise HTTPException(409, {"code": str(exc)})
        return {"id": task.id, "status": task.status, "attempts": task.attempts}
    finally:
        session.close()


@router.post("/api/admin/x5-real-tasks/{task_id}/timeout")
def timeout(task_id: str, request: Request, authorization: str | None = Header(None)):
    admin(request, authorization); session = request.app.state.session_factory()
    try:
        try:
            task = X5RealService(session).timeout(task_id)
        except X5RealError as exc:
            raise HTTPException(409, {"code": str(exc)})
        return {"id": task.id, "status": task.status, "error_code": task.error_code}
    finally:
        session.close()


def _worker_task(session, agent_id: str, task_id: str) -> EvaluationTask:
    task = session.get(EvaluationTask, task_id)
    worker = session.get(PlatformWorker, task.worker_instance_id) if task else None
    if not task or not worker or task.mode != "REAL" or worker.agent_id != agent_id:
        raise HTTPException(404, {"code": "worker_task_not_found"})
    return task


@router.post("/api/internal/workers/{worker_id}/x5-tasks/claim", status_code=200)
def claim(worker_id: str, request: Request, authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        task = X5RealService(session).claim(worker_id)
        if task is None:
            return Response(status_code=204)
        profile = session.get(ModelProfile, task.model_profile_id)
        asset = session.get(ModelAsset, profile.model_asset_id)
        snapshot = session.get(TaskSnapshot, task.snapshot_id)
        platform = (snapshot.platform_governance if snapshot else {})
        return {"id": task.id, "attempt_id": task.attempt_id, "mode": "REAL", "task_kind": task.task_kind,
                "model_profile": {"id": profile.id, "analyzer_version": profile.analyzer_version},
                "model": {"sha256": asset.sha256},
                "platform": {"id": platform.get("platform_id"), "version": platform.get("catalog_version"), "image_lock_version": platform.get("image_lock_version")}}
    finally:
        session.close()


@router.post("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/start")
def start(worker_id: str, task_id: str, request: Request, authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        try:
            task = X5RealService(session).start(task_id, worker_id)
        except X5RealError as exc:
            raise HTTPException(409, {"code": str(exc)})
        return {"id": task.id, "status": task.status}
    finally:
        session.close()


@router.post("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/heartbeat")
def task_heartbeat(worker_id: str, task_id: str, request: Request, authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        if not X5RealService(session).heartbeat(task_id, worker_id):
            raise HTTPException(409, {"code": "task_lease_lost"})
        return {"id": task_id, "lease": "renewed"}
    finally:
        session.close()


@router.get("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/model")
def model_input(worker_id: str, task_id: str, request: Request, authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        task = _worker_task(session, worker_id, task_id)
        profile = session.get(ModelProfile, task.model_profile_id)
        asset = session.get(ModelAsset, profile.model_asset_id)
        artifact = session.get(Artifact, asset.artifact_id)
        with request.app.state.artifact_storage.open(artifact.uri) as stream:
            payload = stream.read()
        return Response(payload, media_type="application/octet-stream",
                        headers={"X-Content-SHA256": asset.sha256})
    finally:
        session.close()


@router.get("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/compiled-model")
def compiled_model_input(worker_id: str, task_id: str, request: Request, authorization: str | None = Header(None)):
    worker_auth(request, authorization); session = request.app.state.session_factory()
    try:
        task = _worker_task(session, worker_id, task_id)
        if task.task_kind != "REAL_BOARD_SMOKE" or not task.source_task_id:
            raise HTTPException(409, {"code": "compiled_model_not_available"})
        snapshot = session.get(TaskSnapshot, task.snapshot_id)
        artifact_id = (snapshot.platform_package_versions.get("X5", {}).get("compiled_model_artifact_id") if snapshot else None)
        if not artifact_id:
            raise HTTPException(404, {"code": "compiled_model_not_found"})
        artifact = session.get(Artifact, artifact_id)
        with request.app.state.artifact_storage.open(artifact.uri) as stream:
            payload = stream.read()
        return Response(payload, media_type="application/octet-stream", headers={"X-Content-SHA256": artifact.sha256})
    finally:
        session.close()


@router.post("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/evidence", status_code=201)
def upload_evidence(worker_id: str, task_id: str, request: Request,
                    evidence_type: str = Form(...), phase: str = Form(...),
                    file: UploadFile = File(...), authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        task = _worker_task(session, worker_id, task_id)
        if evidence_type not in {item.value for item in EvidenceType} or phase not in {item.value for item in EvidencePhase}:
            raise HTTPException(422, {"code": "invalid_evidence_type"})
        allowed = ({EvidenceType.X5_BOARD_PREFLIGHT.value, EvidenceType.X5_BOARD_LOAD_LOG.value,
                    EvidenceType.X5_BOARD_INFERENCE_LOG.value, EvidenceType.X5_BOARD_RESULT.value,
                    EvidenceType.BOARD_LOG.value} if task.task_kind == "REAL_BOARD_SMOKE" else
                   {EvidenceType.X5_COMPILED_MODEL.value, EvidenceType.X5_COMPILE_LOG.value,
                    EvidenceType.X5_COMPILE_SUMMARY.value, EvidenceType.X5_STATIC_CHECK.value,
                    EvidenceType.X5_RUNNER_RESULT.value})
        if evidence_type not in allowed:
            raise HTTPException(422, {"code": "evidence_not_allowed_for_task"})
        payload = file.file.read()
        if not payload:
            raise HTTPException(422, {"code": "empty_evidence"})
        content_type = "application/octet-stream" if file.filename and file.filename.endswith(".bin") else "application/json"
        artifact = ArtifactService(session, request.app.state.artifact_storage).put(payload, content_type=content_type)
        evidence = EvidenceService(session).record(evidence_type=evidence_type, phase=phase, artifact_id=artifact.id,
            task_id=task_id, platform="X5", toolchain_version="hb_mapper 1.24.3", rule_package_version="1.0.0")
        session.commit()
        return {"id": evidence.id, "artifact_id": artifact.id, "uri": artifact.uri,
                "sha256": artifact.sha256, "size_bytes": artifact.size_bytes, "evidence_type": evidence.evidence_type}
    finally:
        session.close()


class Completion(BaseModel):
    result: dict
    evidence_ids: list[str]


@router.post("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/complete")
def complete(worker_id: str, task_id: str, body: Completion, request: Request,
             authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        _worker_task(session, worker_id, task_id)
        X5RealService(session).finish(task_id, body.result, body.evidence_ids)
        return {"id": task_id, "status": "recorded"}
    finally:
        session.close()


class Failure(BaseModel):
    reason_code: str


@router.post("/api/internal/workers/{worker_id}/x5-tasks/{task_id}/fail")
def fail(worker_id: str, task_id: str, body: Failure, request: Request,
         authorization: str | None = Header(None)):
    worker_auth(request, authorization)
    session = request.app.state.session_factory()
    try:
        _worker_task(session, worker_id, task_id)
        X5RealService(session).fail(task_id, body.reason_code)
        return {"id": task_id, "status": "FAILED"}
    finally:
        session.close()
