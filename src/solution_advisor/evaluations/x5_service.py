from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from solution_advisor.common_analyzer.service import (
    LEASE_SECONDS, acquire_worker_lease, now, release_worker_task_lease, renew_worker_lease,
)
from solution_advisor.common_analyzer.domain import WorkerCapacityLease
from solution_advisor.evaluations.domain import EvaluationResult, EvaluationTask, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.artifacts.domain import Artifact, Evidence, EvidenceType
from solution_advisor.platforms.domain import PlatformBinding, PlatformWorker
from solution_advisor.platforms.service import PlatformRegistry


class X5RealError(ValueError):
    pass


class X5RealService:
    """Control-plane state machine for the fixed X5 compile capability."""

    def __init__(self, session):
        self.session = session

    def _refresh_worker_capacity_state(self, worker: PlatformWorker) -> None:
        active = list(self.session.scalars(select(WorkerCapacityLease).where(
            WorkerCapacityLease.worker_instance_id == worker.id,
            WorkerCapacityLease.status == "ACTIVE",
        )))
        if worker.state not in {"DRAINING", "OFFLINE", "ERROR"}:
            worker.state = "BUSY" if len(active) >= worker.max_concurrency else "READY"
        worker.current_task_id = active[0].task_id if len(active) == 1 else None

    def create(self, profile_id: str, owner_subject: str, catalog_id: str | None = None, flow_id: str | None = None):
        profile = self.session.get(ModelProfile, profile_id)
        catalog, binding, worker, availability = PlatformRegistry(self.session).availability("X5", catalog_id)
        if not profile:
            raise X5RealError("profile_not_found")
        if availability != "READY" or not catalog or not binding or not worker or not {"static_check", "compile"}.issubset(binding.capabilities):
            raise X5RealError(f"x5_not_schedulable_{availability}")
        asset = self.session.get(ModelAsset, profile.model_asset_id)
        snapshot = TaskSnapshot(
            model_asset_id=asset.id, model_profile_id=profile.id,
            evaluation_template_version="x5-real-1.0.0",
            report_template_version="x5-real-1.0.0",
            platform_package_versions={"X5": {"package": catalog.version, "image_id": worker.runner.get("digest")}},
            platform_governance={"platform_id": catalog.platform_id, "catalog_id": catalog.id, "catalog_version": catalog.version,
                                 "binding_id": binding.id, "worker_id": worker.id, "runner": worker.runner,
                                 "image_lock_version": binding.image_lock_version,
                                 "actual_image_ref": binding.actual_image_ref,
                                 "actual_image_digest": binding.actual_image_digest or binding.image_lock_version,
                                 "image_match_status": binding.image_match_status, "rule_version": "1.0.0",
                                 "profile_parser_version": "x5-hrt-profile-1.0"},
        )
        self.session.add(snapshot)
        self.session.flush()
        task = EvaluationTask(model_profile_id=profile.id, mode="REAL", platforms=["X5"],
                              snapshot_id=snapshot.id, status="QUEUED", task_kind="X5_COMPILE", owner_subject=asset.owner_subject, flow_id=flow_id)
        self.session.add(task)
        self.session.flush()
        snapshot.task_id = task.id
        self.session.commit()
        return task

    def create_board_smoke(self, compile_task_id: str, owner_subject: str):
        source = self.session.get(EvaluationTask, compile_task_id)
        if not source or source.mode != "REAL" or source.task_kind != "X5_COMPILE" or source.status != "SUCCEEDED":
            raise X5RealError("compiled_task_not_available")
        source_snapshot = self.session.get(TaskSnapshot, source.snapshot_id)
        frozen = source_snapshot.platform_governance if source_snapshot else {}
        # An automatic board phase belongs to the same immutable Flow
        # snapshot as its compilation phase.  It must never switch to a newer
        # X5 Catalog merely because one was published while compilation ran.
        catalog, binding, worker, availability = PlatformRegistry(self.session).availability(
            "X5", frozen.get("catalog_id")
        )
        existing = self.session.scalar(select(EvaluationTask).where(
            EvaluationTask.source_task_id == source.id,
            EvaluationTask.task_kind == "REAL_BOARD_SMOKE",
        ))
        if existing:
            return existing
        if availability != "READY" or not catalog or not binding or not worker or "board_smoke" not in binding.capabilities:
            raise X5RealError(f"x5_board_not_schedulable_{availability}")
        evidence = self.session.scalar(select(Evidence).where(
            Evidence.task_id == source.id, Evidence.evidence_type == EvidenceType.X5_COMPILED_MODEL.value
        ).order_by(Evidence.produced_at.asc()))
        if not evidence or not self.session.get(Artifact, evidence.artifact_id):
            raise X5RealError("compiled_model_artifact_not_found")
        snapshot = TaskSnapshot(
            model_asset_id=source_snapshot.model_asset_id, model_profile_id=source.model_profile_id,
            evaluation_template_version="x5-board-smoke-r0", report_template_version="x5-board-smoke-r0",
            platform_package_versions={"X5": {"compiled_task_id": source.id,
                "compiled_model_artifact_id": evidence.artifact_id, "compiled_model_sha256": self.session.get(Artifact, evidence.artifact_id).sha256,
                "package": catalog.version, "image_id": worker.runner.get("digest")}},
            platform_governance={"platform_id": catalog.platform_id, "catalog_id": catalog.id, "catalog_version": catalog.version,
                                 "binding_id": binding.id, "worker_id": worker.id, "runner": worker.runner,
                                 "image_lock_version": binding.image_lock_version,
                                 "actual_image_ref": binding.actual_image_ref,
                                 "actual_image_digest": binding.actual_image_digest or binding.image_lock_version,
                                 "image_match_status": binding.image_match_status, "rule_version": "1.0.0",
                                 "profile_parser_version": "x5-hrt-profile-1.0"},
        )
        self.session.add(snapshot); self.session.flush()
        task = EvaluationTask(model_profile_id=source.model_profile_id, mode="REAL", platforms=["X5"],
                              snapshot_id=snapshot.id, status="QUEUED", task_kind="REAL_BOARD_SMOKE",
                              source_task_id=source.id, owner_subject=source.owner_subject, flow_id=source.flow_id)
        self.session.add(task); self.session.flush(); snapshot.task_id = task.id
        self.session.commit()
        return task

    def claim(self, agent_id: str):
        candidates = self.session.scalars(select(EvaluationTask).where(
            EvaluationTask.mode == "REAL", EvaluationTask.status == "QUEUED"
        ).order_by(EvaluationTask.created_at).with_for_update()).all()
        for task in candidates:
            snapshot = self.session.get(TaskSnapshot, task.snapshot_id) if task.snapshot_id else None
            frozen = snapshot.platform_governance if snapshot else {}
            if frozen.get("platform_id") not in {None, "X5"}:
                continue
            worker = self.session.get(PlatformWorker, frozen.get("worker_id")) if frozen.get("worker_id") else None
            # Compatibility for pre-Flow historical X5 tasks: they retain the
            # old worker lookup, while new Flow work is always snapshot-bound.
            if worker is None and not frozen.get("worker_id"):
                worker = self.session.scalar(select(PlatformWorker).where(
                    PlatformWorker.agent_id == agent_id, PlatformWorker.platform_id == "X5",
                    PlatformWorker.state.in_(["READY", "BUSY"]),
                ).with_for_update())
            binding = self.session.get(PlatformBinding, worker.binding_id) if worker else None
            catalog_id = frozen.get("catalog_id") if frozen else None
            catalog, selected_binding, _, availability = PlatformRegistry(self.session).availability("X5", catalog_id)
            expected_runner = frozen.get("runner_release") or (
                frozen.get("runner", {}).get("version") if isinstance(frozen.get("runner"), dict) else None
            )
            if (not worker or worker.agent_id != agent_id or worker.platform_id != "X5"
                    or worker.state not in {"READY", "BUSY"} or not binding
                    or availability != "READY" or binding.id != (selected_binding.id if selected_binding else None)
                    or (expected_runner and (binding.runner_version != expected_runner
                                             or worker.runner.get("version") != expected_runner))):
                continue
            capabilities = set(binding.capabilities)
            board_active = bool(self.session.scalar(select(EvaluationTask.id).where(
                EvaluationTask.worker_instance_id == worker.id,
                EvaluationTask.task_kind == "REAL_BOARD_SMOKE",
                EvaluationTask.status.in_(["CLAIMED", "RUNNING"]),
            )))
            supported = (
                task.task_kind == "X5_COMPILE" and {"static_check", "compile"}.issubset(capabilities)
            ) or (
                task.task_kind == "REAL_BOARD_SMOKE" and "board_smoke" in capabilities and not board_active
            )
            if not supported:
                continue
            attempt_id = f"attempt_{uuid4().hex}"
            lease = acquire_worker_lease(self.session, worker.id, task.id, attempt_id)
            if lease is None:
                continue
            task.status = "CLAIMED"
            task.worker_instance_id = worker.id
            task.attempt_id = attempt_id
            task.attempts += 1
            task.lease_expires_at = lease.expires_at
            self._refresh_worker_capacity_state(worker)
            self.session.commit()
            return task
        self.session.commit()
        return None

    def start(self, task_id: str, agent_id: str) -> EvaluationTask:
        task = self.session.get(EvaluationTask, task_id)
        worker = self.session.get(PlatformWorker, task.worker_instance_id) if task else None
        if not task or not worker or worker.agent_id != agent_id or task.mode != "REAL" or task.status != "CLAIMED":
            raise X5RealError("task_not_claimed")
        task.status = "RUNNING"
        self.session.commit()
        return task

    def heartbeat(self, task_id: str, agent_id: str) -> bool:
        task = self.session.get(EvaluationTask, task_id)
        worker = self.session.get(PlatformWorker, task.worker_instance_id) if task else None
        if not task or not worker or worker.agent_id != agent_id or task.status not in {"CLAIMED", "RUNNING"}:
            return False
        if not renew_worker_lease(self.session, worker.id, task.id, task.attempt_id or ""):
            return False
        task.lease_expires_at = now() + timedelta(seconds=LEASE_SECONDS)
        worker.last_heartbeat_at = now()
        self.session.commit()
        return True

    def finish(self, task_id: str, result: dict, evidence_ids: list[str]):
        task = self.session.get(EvaluationTask, task_id)
        if not task:
            raise X5RealError("task_not_found")
        task.status = "SUCCEEDED" if result.get("status") == "SUCCEEDED" else "FAILED"
        task.error_code = None if task.status == "SUCCEEDED" else result.get("reason_code", "compile_failed")
        if task.task_kind == "REAL_BOARD_SMOKE":
            self._attach_compile_cpu_allocation(task, result)
        release_worker_task_lease(self.session, task.worker_instance_id or "", task.id, task.attempt_id or "",
                                  "RELEASED" if task.status == "SUCCEEDED" else "FAILED")
        self.session.add(EvaluationResult(task_id=task.id, platform="X5", source="REAL",
                         fixture_version="x5-board-smoke-r0" if task.task_kind == "REAL_BOARD_SMOKE" else "x5-real-1.0.0", payload=result, schema_version="1.0",
                         common_result={"mode": "REAL"}, platform_result=result,
                         evidence_ids=evidence_ids))
        worker = self.session.get(PlatformWorker, task.worker_instance_id) if task.worker_instance_id else None
        if worker:
            self._refresh_worker_capacity_state(worker)
        self.session.commit()
        # A REAL evaluation is one user-visible workflow. Compilation and the
        # fixed board preset remain separate controlled executions, but the
        # board stage is enqueued automatically after a successful compile.
        if task.task_kind == "X5_COMPILE" and task.status == "SUCCEEDED":
            try:
                self.create_board_smoke(task.id, task.owner_subject)
            except X5RealError as exc:
                # Keep the immutable compilation fact, but retain why the
                # automatic board stage was not queued instead of silently
                # leaving users with an unexplained NOT_EXECUTED boundary.
                compile_result = self.session.scalar(select(EvaluationResult).where(
                    EvaluationResult.task_id == task.id, EvaluationResult.source == "REAL"
                ))
                if compile_result:
                    payload = dict(compile_result.platform_result)
                    payload["board_stage"] = {"status": "NOT_EXECUTED", "reason_code": str(exc)}
                    compile_result.platform_result = payload
                    compile_result.payload = payload
                    self.session.commit()

    def _attach_compile_cpu_allocation(self, task: EvaluationTask, result: dict) -> None:
        """Keep compile allocation and board CPU timing as separate facts."""
        source = self.session.query(EvaluationResult).filter_by(task_id=task.source_task_id, source="REAL").first()
        allocation = []
        if source:
            for evidence in source.platform_result.get("evidence", []):
                if evidence.get("type") == "x5_compile_log":
                    allocation = evidence.get("summary", {}).get("allocation", {}).get("CPU", [])
                    break
        performance = result.get("performance")
        if isinstance(performance, dict):
            assessment = performance.setdefault("model_cpu_operator_assessment", {})
            assessment.update({"status": "NOT_DETECTED_IN_COMPILE_ALLOCATION" if not allocation else "DETECTED_IN_COMPILE_ALLOCATION",
                               "compile_allocation_cpu_operators": allocation,
                               "explanation": "编译分配日志的 CPU 列表用于模型 CPU 算子判断；profile 的 CPU 耗时单独表示 Runtime CPU 执行段。"})

    def fail(self, task_id: str, reason_code: str):
        task = self.session.get(EvaluationTask, task_id)
        if not task:
            return
        # Completion is idempotent: a late transport error after a successful
        # control-plane completion must never rewrite the audited success.
        if task.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}:
            return
        task.status, task.error_code = "FAILED", reason_code
        release_worker_task_lease(self.session, task.worker_instance_id or "", task.id,
                                  task.attempt_id or "", "FAILED")
        worker = self.session.get(PlatformWorker, task.worker_instance_id) if task.worker_instance_id else None
        if worker: self._refresh_worker_capacity_state(worker)
        self.session.commit()

    def cancel(self, task_id: str):
        task = self.session.get(EvaluationTask, task_id)
        if not task or task.mode != "REAL":
            raise X5RealError("real_task_not_found")
        if task.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}:
            raise X5RealError("task_not_cancellable")
        task.status, task.error_code = "CANCELLED", "cancelled_by_admin"
        release_worker_task_lease(self.session, task.worker_instance_id or "", task.id,
                                  task.attempt_id or "", "CANCELLED")
        worker = self.session.get(PlatformWorker, task.worker_instance_id) if task.worker_instance_id else None
        if worker: self._refresh_worker_capacity_state(worker)
        self.session.commit()
        return task

    def timeout(self, task_id: str):
        """Recovery path used when a claimed/running attempt exceeds its deadline."""
        task = self.session.get(EvaluationTask, task_id)
        if not task or task.mode != "REAL":
            raise X5RealError("real_task_not_found")
        if task.status not in {"CLAIMED", "RUNNING"}:
            raise X5RealError("task_not_timeoutable")
        task.status, task.error_code = "TIMEOUT", "execution_timeout"
        release_worker_task_lease(self.session, task.worker_instance_id or "", task.id,
                                  task.attempt_id or "", "EXPIRED")
        worker = self.session.get(PlatformWorker, task.worker_instance_id)
        if worker: self._refresh_worker_capacity_state(worker)
        self.session.commit()
        return task

    def retry(self, task_id: str):
        task = self.session.get(EvaluationTask, task_id)
        if not task or task.mode != "REAL":
            raise X5RealError("real_task_not_found")
        if task.status not in {"FAILED", "CANCELLED", "TIMEOUT"} or task.attempts >= task.max_attempts:
            raise X5RealError("task_not_retryable")
        task.status, task.error_code, task.worker_instance_id, task.attempt_id, task.lease_expires_at = "QUEUED", None, None, None, None
        self.session.commit()
        return task
