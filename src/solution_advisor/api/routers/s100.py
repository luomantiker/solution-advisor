"""Internal S100 Worker API.  It has no public task-creation surface."""
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from solution_advisor.api.routers.workers import worker_auth
from solution_advisor.artifacts.domain import Artifact, Evidence, EvidencePhase, EvidenceType
from solution_advisor.artifacts.service import ArtifactService, EvidenceService
from solution_advisor.evaluations.domain import EvaluationTask, TaskSnapshot
from solution_advisor.evaluations.s100_service import S100FlowExecutor, S100TaskError
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile

router=APIRouter(tags=["s100-internal"])
ALLOWED_COMPILE={"s100_static_check","s100_compile_log","s100_compile_summary","s100_runner_result","s100_compiled_model"}
ALLOWED_BOARD={"s100_board_preflight","s100_board_load_log","s100_board_inference_log","s100_board_profile_log","s100_board_profile_csv","s100_board_result"}
class Complete(BaseModel): result:dict; evidence_ids:list[str]
class Fail(BaseModel): reason_code:str

def checked(session, worker_id, task_id):
    task=session.get(EvaluationTask,task_id); snapshot=session.get(TaskSnapshot,task.snapshot_id) if task else None; frozen=snapshot.platform_governance if snapshot else {}
    if not task or task.task_kind not in {"S100_COMPILE","S100_BOARD_PERF"} or frozen.get("platform_id")!="S100" or frozen.get("agent_id")!=worker_id: raise HTTPException(403,{"code":"s100_worker_snapshot_forbidden"})
    return task,frozen

@router.post("/api/internal/workers/{worker_id}/s100-tasks/claim")
def claim(worker_id:str,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization); s=request.app.state.session_factory()
    try:
        task=S100FlowExecutor(s).claim(worker_id)
        if not task:return Response(status_code=204)
        profile=s.get(ModelProfile,task.model_profile_id); asset=s.get(ModelAsset,profile.model_asset_id); _,frozen=checked(s,worker_id,task.id)
        return {"id":task.id,"task_kind":task.task_kind,"attempt_id":task.attempt_id,"model":{"sha256":asset.sha256},"snapshot":frozen}
    finally:s.close()
@router.post("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/start")
def start(worker_id:str,task_id:str,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        checked(s,worker_id,task_id); return {"id":S100FlowExecutor(s).start(task_id,worker_id).id,"status":"RUNNING"}
    except S100TaskError as e: raise HTTPException(409,{"code":str(e)})
    finally:s.close()
@router.post("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/heartbeat")
def heartbeat(worker_id:str,task_id:str,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        checked(s,worker_id,task_id)
        if not S100FlowExecutor(s).heartbeat(task_id,worker_id):raise HTTPException(409,{"code":"s100_lease_lost"})
        return {"id":task_id,"lease":"renewed"}
    finally:s.close()
@router.get("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/model")
def model(worker_id:str,task_id:str,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        task,_=checked(s,worker_id,task_id)
        if task.task_kind!="S100_COMPILE":raise HTTPException(409,{"code":"s100_model_only_for_compile"})
        profile=s.get(ModelProfile,task.model_profile_id);asset=s.get(ModelAsset,profile.model_asset_id);artifact=s.get(Artifact,asset.artifact_id)
        with request.app.state.artifact_storage.open(artifact.uri) as stream:payload=stream.read()
        return Response(payload,media_type="application/octet-stream",headers={"X-Content-SHA256":asset.sha256})
    finally:s.close()
@router.get("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/compiled-artifact")
def compiled_artifact(worker_id:str,task_id:str,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        task,frozen=checked(s,worker_id,task_id)
        if task.task_kind!="S100_BOARD_PERF" or not task.source_task_id:raise HTTPException(409,{"code":"s100_compiled_artifact_not_available"})
        source=s.get(EvaluationTask,task.source_task_id)
        if not source or source.flow_id!=task.flow_id or source.task_kind!="S100_COMPILE" or source.status!="SUCCEEDED":raise HTTPException(409,{"code":"s100_cross_flow_or_unfinished_artifact"})
        package=(s.get(TaskSnapshot, task.snapshot_id).platform_package_versions or {}).get("S100", {})
        if package.get("compiled_task_id") != source.id or package.get("artifact_format") != "s100_hbm":
            raise HTTPException(409,{"code":"s100_compiled_artifact_snapshot_mismatch"})
        row=s.scalar(select(Evidence).where(Evidence.task_id==source.id,Evidence.platform=="S100",Evidence.evidence_type=="s100_compiled_model"))
        artifact=s.get(Artifact,row.artifact_id) if row else None
        if not artifact or artifact.id != package.get("compiled_model_artifact_id") or artifact.sha256 != package.get("compiled_model_sha256"):
            raise HTTPException(409,{"code":"s100_compiled_artifact_integrity_mismatch"})
        with request.app.state.artifact_storage.open(artifact.uri) as stream:payload=stream.read()
        return Response(payload,media_type="application/octet-stream",headers={"X-Content-SHA256":artifact.sha256,"X-Artifact-Format":"s100_hbm"})
    finally:s.close()
@router.post("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/evidence",status_code=201)
def evidence(worker_id:str,task_id:str,request:Request,evidence_type:str=Form(...),phase:str=Form(...),file:UploadFile=File(...),authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        task,frozen=checked(s,worker_id,task_id); allowed=ALLOWED_COMPILE if task.task_kind=="S100_COMPILE" else ALLOWED_BOARD
        expected_phase="COMPILATION" if task.task_kind=="S100_COMPILE" else "BOARD_TEST"
        if evidence_type not in allowed or phase != expected_phase:raise HTTPException(422,{"code":"s100_evidence_not_allowed"})
        payload=file.file.read()
        if not payload or len(payload)>request.app.state.settings.upload_max_bytes:raise HTTPException(422,{"code":"s100_evidence_size_invalid"})
        artifact=ArtifactService(s,request.app.state.artifact_storage).put(payload,content_type="application/octet-stream")
        row=EvidenceService(s).record(evidence_type=evidence_type,phase=phase,artifact_id=artifact.id,task_id=task.id,platform="S100",toolchain_version="hb_compile 3.5.3",rule_package_version=frozen.get("runner_release"));s.flush();s.commit()
        return {"id":row.id,"artifact_id":artifact.id,"sha256":artifact.sha256,"size_bytes":artifact.size_bytes}
    finally:s.close()
@router.post("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/complete")
def complete(worker_id:str,task_id:str,body:Complete,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try:
        task,_=checked(s,worker_id,task_id); required=ALLOWED_COMPILE if task.task_kind=="S100_COMPILE" else ALLOWED_BOARD
        def reject(code: str):
            # Evidence was already stored under this task; retain it as real
            # diagnostics while making the stage terminal and releasing lease.
            S100FlowExecutor(s).fail(task_id, worker_id, code)
            raise HTTPException(422,{"code":code})
        if len(body.evidence_ids) != len(set(body.evidence_ids)): reject("s100_evidence_ids_duplicate")
        rows=list(s.scalars(select(Evidence).where(Evidence.id.in_(body.evidence_ids),Evidence.task_id==task_id, Evidence.platform=="S100")))
        if len(rows) != len(body.evidence_ids): reject("s100_evidence_cross_task_or_missing")
        types={x.evidence_type for x in rows}
        if body.result.get("status")=="SUCCEEDED" and not required.issubset(types): reject("s100_evidence_incomplete")
        if task.task_kind=="S100_COMPILE" and body.result.get("status")=="SUCCEEDED":
            artifacts=body.result.get("artifacts",[]) if isinstance(body.result.get("artifacts",[]),list) else []
            declared=[x for x in artifacts if isinstance(x,dict) and x.get("type")=="compiled_model_artifact"]
            if len(declared)!=1 or declared[0].get("format")!="s100_hbm" or not str(declared[0].get("filename","")).endswith(".hbm") or not isinstance(declared[0].get("sha256"),str) or len(declared[0]["sha256"])!=64 or not isinstance(declared[0].get("size_bytes"),int): reject("s100_artifact_contract_invalid")
            matches=[row for row in rows if row.evidence_type=="s100_compiled_model" and (artifact:=s.get(Artifact,row.artifact_id)) and artifact.sha256==declared[0]["sha256"] and artifact.size_bytes==declared[0]["size_bytes"]]
            if len(matches)!=1: reject("s100_artifact_evidence_mismatch")
        return {"id":S100FlowExecutor(s).complete(task_id,worker_id,body.result,body.evidence_ids).id,"status":"recorded"}
    except S100TaskError as e:raise HTTPException(409,{"code":str(e)})
    finally:s.close()
@router.post("/api/internal/workers/{worker_id}/s100-tasks/{task_id}/fail")
def fail(worker_id:str,task_id:str,body:Fail,request:Request,authorization:str|None=Header(None)):
    worker_auth(request,authorization);s=request.app.state.session_factory()
    try: checked(s,worker_id,task_id); return {"id":S100FlowExecutor(s).fail(task_id,worker_id,body.reason_code).id,"status":"FAILED"}
    except S100TaskError as e:raise HTTPException(409,{"code":str(e)})
    finally:s.close()
