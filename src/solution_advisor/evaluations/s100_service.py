"""S100-only internal evaluation scheduler; deliberately independent of X5."""
from __future__ import annotations
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from solution_advisor.common_analyzer.service import LEASE_SECONDS, acquire_worker_lease, now, release_worker_task_lease, renew_worker_lease
from solution_advisor.common_analyzer.domain import WorkerCapacityLease
from solution_advisor.artifacts.domain import Artifact, Evidence
from solution_advisor.evaluations.domain import EvaluationResult, EvaluationTask, TaskSnapshot
from solution_advisor.platforms.domain import PlatformBinding, PlatformWorker

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
class S100TaskError(ValueError): pass

class S100FlowExecutor:
    def __init__(self, session): self.session=session
    def _snapshot(self, task):
        value=self.session.get(TaskSnapshot, task.snapshot_id) if task.snapshot_id else None
        return (value.platform_governance if value else {})
    def claim(self, agent_id: str):
        tasks=list(self.session.scalars(select(EvaluationTask).where(EvaluationTask.task_kind.in_(["S100_COMPILE","S100_BOARD_PERF"]), EvaluationTask.status=="QUEUED").order_by(EvaluationTask.created_at).with_for_update()))
        for task in tasks:
            frozen=self._snapshot(task)
            if frozen.get("platform_id")!="S100" or frozen.get("agent_id") not in {None,agent_id}: continue
            worker=self.session.get(PlatformWorker, frozen.get("worker_id"))
            binding=self.session.get(PlatformBinding, frozen.get("binding_id"))
            if not worker or not binding or worker.agent_id!=agent_id or worker.state not in {"READY","BUSY"} or binding.state!="HEALTHY": continue
            if frozen.get("runner_release") != binding.runner_version: continue
            if task.task_kind=="S100_BOARD_PERF" and not task.source_task_id: continue
            # Compilation consumes the Worker capacity slots.  Board
            # performance additionally consumes the physical-board slot: one
            # Binding represents one board execution location, so a second
            # board task for the same Binding must remain queued.
            if task.task_kind == "S100_BOARD_PERF" and self.session.scalar(select(EvaluationTask.id).join(
                TaskSnapshot, TaskSnapshot.id == EvaluationTask.snapshot_id
            ).where(
                EvaluationTask.task_kind == "S100_BOARD_PERF",
                EvaluationTask.status.in_(["CLAIMED", "RUNNING"]),
                TaskSnapshot.platform_governance["binding_id"].as_string() == binding.id,
            )):
                continue
            attempt=f"attempt_{uuid4().hex}"; lease=acquire_worker_lease(self.session, worker.id, task.id, attempt)
            if not lease: continue
            task.status,task.worker_instance_id,task.attempt_id,task.attempts,task.lease_expires_at="CLAIMED",worker.id,attempt,task.attempts+1,lease.expires_at
            self.session.commit(); return task
        self.session.commit(); return None
    def start(self, task_id, agent_id):
        task=self.session.get(EvaluationTask,task_id); frozen=self._snapshot(task) if task else {}
        if not task or task.status!="CLAIMED" or frozen.get("agent_id") not in {None,agent_id}: raise S100TaskError("s100_task_not_claimed")
        task.status="RUNNING"; self.session.commit(); return task
    def heartbeat(self, task_id, agent_id):
        task=self.session.get(EvaluationTask,task_id); frozen=self._snapshot(task) if task else {}
        if not task or task.status not in {"CLAIMED","RUNNING"} or frozen.get("agent_id") not in {None,agent_id}: return False
        if not renew_worker_lease(self.session,task.worker_instance_id or "",task.id,task.attempt_id or ""): return False
        task.lease_expires_at=now()+timedelta(seconds=LEASE_SECONDS); self.session.commit(); return True
    def complete(self, task_id, agent_id, result, evidence_ids):
        task=self.session.get(EvaluationTask,task_id); frozen=self._snapshot(task) if task else {}
        if not task or frozen.get("agent_id") not in {None,agent_id}: raise S100TaskError("s100_task_forbidden")
        if task.status in TERMINAL: return task
        if task.status not in {"CLAIMED","RUNNING"}: raise S100TaskError("s100_task_not_active")
        success = result.get("status") == "SUCCEEDED"
        declared = None
        if success and task.task_kind == "S100_COMPILE":
            artifacts = result.get("artifacts", [])
            artifacts = artifacts if isinstance(artifacts, list) else []
            candidates = [item for item in artifacts if isinstance(item, dict) and item.get("type") == "compiled_model_artifact"]
            if len(candidates) != 1:
                success = False
            else:
                declared = candidates[0]
                valid_shape = (
                    declared.get("format") == "s100_hbm"
                    and str(declared.get("filename", "")).endswith(".hbm")
                    and isinstance(declared.get("sha256"), str)
                    and len(declared["sha256"]) == 64
                    and isinstance(declared.get("size_bytes"), int)
                    and declared["size_bytes"] > 0
                )
                proofs = list(self.session.scalars(select(Evidence).where(
                    Evidence.id.in_(evidence_ids), Evidence.task_id == task.id,
                    Evidence.platform == "S100", Evidence.evidence_type == "s100_compiled_model",
                )))
                if not valid_shape or len(proofs) != 1:
                    success = False
                else:
                    stored = self.session.get(Artifact, proofs[0].artifact_id)
                    if not stored or stored.sha256 != declared["sha256"] or stored.size_bytes != declared["size_bytes"]:
                        success = False
        task.status = "SUCCEEDED" if success else "FAILED"
        task.error_code = None if success else (
            "s100_compiled_artifact_contract_invalid" if task.task_kind == "S100_COMPILE" else result.get("reason_code", "s100_execution_failed")
        )
        release_worker_task_lease(self.session,task.worker_instance_id or "",task.id,task.attempt_id or "","RELEASED" if task.status=="SUCCEEDED" else "FAILED")
        self.session.add(EvaluationResult(task_id=task.id,platform="S100",source="REAL",fixture_version="s100-real-1.0.0",payload=result,schema_version="1.0",common_result={"flow_id":task.flow_id},platform_result=result,evidence_ids=evidence_ids))
        if task.task_kind == "S100_COMPILE" and task.status == "SUCCEEDED":
            compiled = self.session.scalar(select(Evidence).where(Evidence.id.in_(evidence_ids), Evidence.task_id == task.id, Evidence.evidence_type == "s100_compiled_model"))
            stored = self.session.get(Artifact, compiled.artifact_id)
            parent_snapshot = self.session.get(TaskSnapshot, task.snapshot_id)
            snapshot=TaskSnapshot(model_asset_id=parent_snapshot.model_asset_id,model_profile_id=task.model_profile_id,evaluation_template_version="s100-board-perf-1.0.0",report_template_version="flow-real-1.0.0",platform_package_versions={"S100":{**frozen,"compiled_task_id":task.id,"compiled_model_artifact_id":stored.id,"compiled_model_sha256":declared["sha256"],"artifact_format":"s100_hbm"}},platform_governance=frozen)
            self.session.add(snapshot); self.session.flush(); child=EvaluationTask(model_profile_id=task.model_profile_id,mode="REAL",platforms=["S100"],snapshot_id=snapshot.id,status="QUEUED",task_kind="S100_BOARD_PERF",source_task_id=task.id,owner_subject=task.owner_subject,flow_id=task.flow_id); self.session.add(child); self.session.flush(); snapshot.task_id=child.id
        self.session.commit(); return task
    def fail(self, task_id, agent_id, code, status="FAILED"):
        task=self.session.get(EvaluationTask,task_id); frozen=self._snapshot(task) if task else {}
        if not task or frozen.get("agent_id") not in {None,agent_id}: raise S100TaskError("s100_task_forbidden")
        if task.status in TERMINAL:return task
        task.status,task.error_code=status,code; release_worker_task_lease(self.session,task.worker_instance_id or "",task.id,task.attempt_id or "",status); self.session.commit(); return task
