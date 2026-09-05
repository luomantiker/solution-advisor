"""Platform-neutral user evaluation flow admission and aggregation."""
from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select

from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationTask, TaskSnapshot
from solution_advisor.evaluations.x5_service import X5RealService
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.platforms.domain import PlatformCatalog
from solution_advisor.platforms.service import PlatformRegistry


class FlowError(ValueError):
    def __init__(self, code: str, reasons: dict[str, str] | None = None):
        self.code, self.reasons = code, reasons or {}; super().__init__(code)


class EvaluationFlowService:
    def __init__(self, session): self.session = session

    def _admit(self, catalog_ids: list[str]) -> list[tuple]:
        if not catalog_ids or len(set(catalog_ids)) != len(catalog_ids): raise FlowError("catalog_selection_invalid")
        selected, reasons = [], {}
        for catalog_id in catalog_ids:
            catalog = self.session.get(PlatformCatalog, catalog_id)
            if not catalog: reasons[catalog_id] = "平台目录不存在"
            else:
                value = PlatformRegistry(self.session).availability(catalog.platform_id, catalog.id)
                binding, worker, reason = value[1:]
                if reason != "READY": reasons[catalog.display_name] = "当前不可调度：" + {"catalog_available":"目录尚未发布","healthy_binding_required":"缺少健康绑定","agent_offline":"HostAgent 离线","ready_worker_required":"没有就绪执行器"}.get(reason, reason)
                elif not {"static_check", "compile", "board_smoke"}.issubset(set(binding.capabilities)): reasons[catalog.display_name] = "执行器能力不完整"
                elif not catalog.runner.get("version") or (catalog.platform_id == "S100" and not catalog.runner.get("content_sha256")):
                    reasons[catalog.display_name] = "固定 Runner 发布物或内容哈希不完整"
                elif catalog.runner.get("version") != binding.runner_version or worker.runner.get("version") != catalog.runner.get("version"):
                    reasons[catalog.display_name] = "固定 Runner Release 与 Binding 或 Worker 不一致"
                else: selected.append((catalog, binding, worker))
        if reasons: raise FlowError("platforms_not_schedulable", reasons)
        return selected

    def create(self, profile_id: str, owner_subject: str, catalog_ids: list[str], preset: str = "standard-performance-1.0") -> EvaluationFlow:
        profile = self.session.get(ModelProfile, profile_id); asset = self.session.get(ModelAsset, profile.model_asset_id) if profile else None
        if not profile or not asset: raise FlowError("profile_not_found")
        selected = self._admit(catalog_ids)
        snapshots = {catalog.id: {"platform_id": catalog.platform_id, "catalog_id": catalog.id, "catalog_version": catalog.version,
            "binding_id": binding.id, "worker_id": worker.id, "agent_id": binding.agent_id, "runner": worker.runner, "runner_release": catalog.runner.get("version"),
            "image_lock": catalog.image_lock, "artifact_format": "x5_bin" if catalog.platform_id == "X5" else "s100_hbm",
            "evidence_family": "X5" if catalog.platform_id == "X5" else "S100", "parser": "x5-hrt-profile-1.0" if catalog.platform_id == "X5" else "s100-hrt-profile-1.0",
            "rules": catalog.runner.get("integration_rules", {})} for catalog, binding, worker in selected}
        model_snapshot = {
            "source": "FLOW_CREATE_PROFILE_SNAPSHOT",
            "model_asset_id": asset.id,
            "model_profile_id": profile.id,
            "filename": asset.original_filename,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
            "analyzer_version": profile.analyzer_version,
            "analysis": deepcopy(profile.analysis or {}),
        }
        flow = EvaluationFlow(model_profile_id=profile.id, owner_subject=owner_subject, preset=preset,
                              platform_snapshots=snapshots, model_snapshot=model_snapshot)
        self.session.add(flow); self.session.flush()
        for catalog, binding, worker in selected:
            if catalog.platform_id == "X5": X5RealService(self.session).create(profile.id, owner_subject, catalog.id, flow.id)
            elif catalog.platform_id == "S100":
                snapshot = TaskSnapshot(model_asset_id=asset.id, model_profile_id=profile.id, evaluation_template_version="s100-real-1.0.0", report_template_version="flow-real-1.0.0", platform_package_versions={"S100": snapshots[catalog.id]}, platform_governance=snapshots[catalog.id])
                self.session.add(snapshot); self.session.flush()
                task = EvaluationTask(model_profile_id=profile.id, mode="REAL", platforms=["S100"], snapshot_id=snapshot.id, status="QUEUED", task_kind="S100_COMPILE", owner_subject=owner_subject, flow_id=flow.id)
                self.session.add(task); self.session.flush(); snapshot.task_id = task.id
            else: raise FlowError("platform_adapter_not_installed", {catalog.display_name: "尚未安装平台执行适配器"})
        self.session.commit(); return flow

    def payload(self, flow: EvaluationFlow) -> dict:
        tasks = list(self.session.scalars(select(EvaluationTask).where(EvaluationTask.flow_id == flow.id).order_by(EvaluationTask.created_at)))
        # A platform is represented by its last reachable phase: a successful
        # compile followed by queued board measurement is waiting, not success.
        per_platform: dict[str, str] = {}
        for task in tasks:
            platform = task.platforms[0]
            previous = per_platform.get(platform)
            if previous not in {"FAILED", "CANCELLED", "TIMEOUT"} or task.task_kind.endswith("BOARD_PERF"):
                per_platform[platform] = task.status
        values = list(per_platform.values())
        terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
        if values and all(value == "SUCCEEDED" for value in values): status = "SUCCEEDED"
        elif "SUCCEEDED" in values and any(value in terminal - {"SUCCEEDED"} for value in values): status = "PARTIALLY_SUCCEEDED"
        elif values and all(value in terminal for value in values): status = "FAILED"
        elif any(value in {"CLAIMED", "RUNNING"} for value in values): status = "RUNNING"
        else: status = "QUEUED"
        return {"id": flow.id, "model_profile_id": flow.model_profile_id, "owner_subject": flow.owner_subject, "preset": flow.preset, "status": status, "platform_snapshots": flow.platform_snapshots,
                "stages": [{"id": task.id, "platform": task.platforms[0], "kind": task.task_kind, "status": task.status, "source_task_id": task.source_task_id, "error_code": task.error_code} for task in tasks]}
