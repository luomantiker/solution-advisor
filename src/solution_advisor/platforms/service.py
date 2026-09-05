"""Catalog, Binding and dynamic Worker governance.

No method accepts an image or arbitrary text as a platform identifier.  Images
are only reviewed facts stored in a catalog version and Runner metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from solution_advisor.common_analyzer.domain import WorkerCapacityLease, WorkerInstance
from solution_advisor.platforms.domain import Board, HostAgent, HostImage, PlatformAudit, PlatformBinding, PlatformCandidate, PlatformCatalog, PlatformWorker

ALLOWED_CAPABILITIES = {"static_check", "compile", "board_smoke"}
CATALOG_STATES = {"CANDIDATE_IMAGE", "PENDING_INTEGRATION", "AVAILABLE", "REJECTED", "SUSPENDED"}
WORKER_STATES = {"READY", "BUSY", "DRAINING", "ERROR", "OFFLINE"}


def is_governance_service_image(image_ref: str) -> bool:
    """Exclude this project and its Compose/build dependencies from discovery."""
    normalized = image_ref.lower()
    repository = normalized.split("@", 1)[0].rsplit(":", 1)[0].rsplit("/", 1)[-1]
    return ("playwright" in normalized or "docker:27-cli" in normalized
            or repository.startswith(("solution-advisor", "solution_advisor")) or repository in {
        "postgres", "redis", "minio", "nginx", "node", "python", "uv", "alpine",
    })


class PlatformError(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def audit(session, action: str, *, catalog_id: str | None = None, binding_id: str | None = None,
          worker_id: str | None = None, result: str = "SUCCEEDED", summary: str = "", actor: str = "admin"):
    session.add(PlatformAudit(action=action, actor=actor, catalog_id=catalog_id, binding_id=binding_id,
                              worker_id=worker_id, result=result, summary=summary))


def catalog_payload(item: PlatformCatalog, *, schedulable: bool = False, reason: str | None = None) -> dict:
    return {"id": item.id, "platform_id": item.platform_id, "platform_type_id": item.platform_type_id,
            "version": item.version, "display_name": item.display_name,
            "state": item.state, "package_manifest": item.package_manifest, "image_lock": item.image_lock,
            "runner": item.runner, "checks": item.checks, "review": item.review, "reason": item.reason,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "schedulable": schedulable, "schedule_reason": reason}


def ensure_ready_worker(session, binding: PlatformBinding) -> PlatformWorker:
    worker = session.scalar(select(PlatformWorker).where(
        PlatformWorker.binding_id == binding.id, PlatformWorker.state.in_(["READY", "BUSY"])
    ).order_by(PlatformWorker.created_at))
    if worker:
        worker.max_concurrency = binding.max_concurrency
        worker.last_heartbeat_at = utcnow()
        return worker
    catalog = session.get(PlatformCatalog, binding.catalog_id)
    worker = PlatformWorker(binding_id=binding.id, agent_id=binding.agent_id, platform_id=binding.platform_id,
                            state="READY", max_concurrency=binding.max_concurrency,
                            runner={"version": binding.runner_version, "image_lock_version": binding.image_lock_version,
                                    "image": binding.actual_image_ref or catalog.image_lock.get("image"),
                                    "digest": binding.actual_image_digest or binding.image_lock_version,
                                    "image_match_status": binding.image_match_status},
                            last_heartbeat_at=utcnow())
    session.add(worker); session.flush()
    audit(session, "WORKER_CREATED", binding_id=binding.id, worker_id=worker.id, summary="为健康 Binding 创建受控动态 Worker")
    return worker


def binding_payload(session, item: PlatformBinding) -> dict:
    workers = list(session.scalars(select(PlatformWorker).where(PlatformWorker.binding_id == item.id)))
    ready = [worker for worker in workers if worker.state == "READY"]
    return {"id": item.id, "agent_id": item.agent_id, "catalog_id": item.catalog_id, "platform_id": item.platform_id,
            "state": item.state, "capabilities": item.capabilities, "max_concurrency": item.max_concurrency,
            "image_lock_version": item.image_lock_version,
            "actual_image_ref": item.actual_image_ref, "board_id": item.board_id,
            "actual_image_digest": item.actual_image_digest or item.image_lock_version,
            "image_match_status": item.image_match_status,
            "runner_version": item.runner_version,
            "last_heartbeat": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
            "last_error": item.last_error, "workers": len(workers), "ready_workers": len(ready)}


def worker_payload(session, item: PlatformWorker) -> dict:
    active = list(session.scalars(select(WorkerCapacityLease).where(
        WorkerCapacityLease.worker_instance_id == item.id, WorkerCapacityLease.status == "ACTIVE")))
    state = "BUSY" if len(active) >= item.max_concurrency and item.state == "READY" else item.state
    return {"id": item.id, "binding_id": item.binding_id, "agent_id": item.agent_id, "platform_id": item.platform_id,
            "state": state, "running": len(active), "max_concurrency": item.max_concurrency,
            "free_slots": max(0, item.max_concurrency - len(active)), "current_task_id": item.current_task_id,
            "runner": item.runner, "last_heartbeat": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
            "last_error": item.last_error}


class PlatformRegistry:
    def __init__(self, session): self.session = session

    def availability(self, platform_id: str, catalog_id: str | None = None) -> tuple[PlatformCatalog | None, PlatformBinding | None, PlatformWorker | None, str]:
        catalog = self.session.get(PlatformCatalog, catalog_id) if catalog_id else self.session.scalar(select(PlatformCatalog).where(
            PlatformCatalog.platform_id == platform_id).order_by(PlatformCatalog.created_at.desc()))
        if catalog and catalog.platform_id != platform_id:
            return None, None, None, "catalog_platform_mismatch"
        if not catalog: return None, None, None, "catalog_not_found"
        if catalog.state != "AVAILABLE": return catalog, None, None, f"catalog_{catalog.state.lower()}"
        binding = self.session.scalar(select(PlatformBinding).where(
            PlatformBinding.catalog_id == catalog.id, PlatformBinding.state == "HEALTHY"))
        if not binding: return catalog, None, None, "healthy_binding_required"
        agent = self.session.get(HostAgent, binding.agent_id)
        if not agent or agent.host_state != "ONLINE": return catalog, binding, None, "agent_offline"
        worker = self.session.scalar(select(PlatformWorker).where(
            PlatformWorker.binding_id == binding.id, PlatformWorker.state == "READY").order_by(PlatformWorker.created_at))
        if not worker: return catalog, binding, None, "ready_worker_required"
        return catalog, binding, worker, "READY"

    def create_catalog(self, *, platform_id: str, version: str, display_name: str, package_manifest: dict,
                       image_lock: dict, runner: dict, checks: dict, review: dict, platform_type_id: str | None = None, state: str = "PENDING_INTEGRATION"):
        if not platform_id or not platform_id.replace("-", "").replace("_", "").isalnum():
            raise PlatformError("invalid_platform_id")
        if state not in {"PENDING_INTEGRATION", "REJECTED"}: raise PlatformError("invalid_catalog_initial_state")
        value = PlatformCatalog(platform_id=platform_id, platform_type_id=platform_type_id, version=version, display_name=display_name, state=state,
                                package_manifest=package_manifest, image_lock=image_lock, runner=runner,
                                checks=checks, review=review)
        self.session.add(value); self.session.flush(); audit(self.session, "CATALOG_CREATED", catalog_id=value.id, summary="创建待接入平台目录")
        self.session.commit(); return value

    def publish(self, catalog_id: str):
        item = self.session.get(PlatformCatalog, catalog_id)
        if not item: raise PlatformError("catalog_not_found")
        required = {"package", "image_lock", "runner", "self_check", "offline_test"}
        complete = {"package": bool(item.package_manifest), "image_lock": bool(item.image_lock.get("digest")),
                    "runner": bool(item.runner.get("module") and item.runner.get("version")),
                    "self_check": bool(item.checks.get("self_check")), "offline_test": bool(item.checks.get("offline_test"))}
        if not item.review.get("approved") or not all(complete[key] for key in required):
            audit(self.session, "CATALOG_PUBLISH", catalog_id=item.id, result="REJECTED", summary="发布前置资料不完整")
            self.session.commit(); raise PlatformError("catalog_publish_requirements_missing")
        item.state, item.published_at, item.reason = "AVAILABLE", utcnow(), None
        audit(self.session, "CATALOG_PUBLISHED", catalog_id=item.id, summary="审核发布为可用平台")
        self.session.commit(); return item

    def review_catalog(self, catalog_id: str, *, approved: bool, note: str = ""):
        item = self.session.get(PlatformCatalog, catalog_id)
        if not item: raise PlatformError("catalog_not_found")
        if item.state != "PENDING_INTEGRATION": raise PlatformError("catalog_not_pending_integration")
        item.review = {**item.review, "approved": approved, "note": note}
        audit(self.session, "CATALOG_REVIEWED", catalog_id=item.id,
              result="SUCCEEDED" if approved else "REJECTED", summary="管理员完成 Catalog 审核")
        self.session.commit(); return item

    def suspend(self, catalog_id: str, reason: str):
        item = self.session.get(PlatformCatalog, catalog_id)
        if not item: raise PlatformError("catalog_not_found")
        item.state, item.reason = "SUSPENDED", reason or "管理员暂停"
        audit(self.session, "CATALOG_SUSPENDED", catalog_id=item.id, summary=item.reason)
        self.session.commit(); return item

    def set_catalog_state(self, catalog_id: str, state: str, reason: str = ""):
        if state == "SUSPENDED": return self.suspend(catalog_id, reason)
        if state == "AVAILABLE": return self.publish(catalog_id)
        raise PlatformError("invalid_catalog_state")

    def create_binding(self, *, agent_id: str, catalog_id: str, host_image_id: str | None = None, board_id: str | None = None,
                       capabilities: list[str], max_concurrency: int):
        catalog = self.session.get(PlatformCatalog, catalog_id); agent = self.session.get(HostAgent, agent_id)
        if not catalog or catalog.state != "AVAILABLE": raise PlatformError("available_catalog_required")
        if not agent: raise PlatformError("agent_not_found")
        if board_id:
            board = self.session.get(Board, board_id)
            if not board: raise PlatformError("board_not_found")
            if board.agent_id != agent_id: raise PlatformError("binding_board_agent_mismatch")
            if board.status != "READY": raise PlatformError("ready_board_required")
        baseline_digest = str(catalog.image_lock.get("digest", ""))
        images = list(self.session.scalars(select(HostImage).where(HostImage.agent_id == agent_id)))
        if host_image_id:
            image = self.session.get(HostImage, host_image_id)
            if not image: raise PlatformError("host_image_not_found")
            if image.agent_id != agent_id: raise PlatformError("binding_image_agent_mismatch")
        else:
            image = next((value for value in images if value.image_id == baseline_digest), None)
            if image is None and len(images) == 1:
                image = images[0]
            if image is None:
                raise PlatformError("host_image_not_discovered_on_agent" if not images else "host_image_selection_required")
        if set(capabilities) - ALLOWED_CAPABILITIES: raise PlatformError("invalid_binding_capabilities")
        if self.session.scalar(select(PlatformBinding).where(PlatformBinding.agent_id == agent_id,
                                                              PlatformBinding.catalog_id == catalog.id)):
            raise PlatformError("binding_already_exists")
        binding = PlatformBinding(agent_id=agent_id, catalog_id=catalog.id, platform_id=catalog.platform_id,
                                  capabilities=capabilities, max_concurrency=max_concurrency,
                                  image_lock_version=baseline_digest,
                                  actual_image_ref=image.image_ref, actual_image_digest=image.image_id,
                                  board_id=board_id,
                                  image_match_status="MATCH" if image.image_id == baseline_digest else "VERSION_MATCH_DIGEST_DIFFERENT",
                                  runner_version=str(catalog.runner.get("version")),
                                  state="HEALTHY" if agent.host_state == "ONLINE" else "OFFLINE",
                                  last_heartbeat_at=agent.last_heartbeat_at)
        self.session.add(binding); self.session.flush()
        if binding.state == "HEALTHY": ensure_ready_worker(self.session, binding)
        match_note = "镜像 digest 一致" if binding.image_match_status == "MATCH" else "镜像 digest 不同，已按平台类型、版本和 Runner 规则建立受控复用"
        audit(self.session, "BINDING_CREATED", catalog_id=catalog.id, binding_id=binding.id, summary=f"管理员授权 HostAgent 平台 Binding；{match_note}")
        self.session.commit(); return binding

    def set_binding_state(self, binding_id: str, state: str, reason: str = ""):
        if state not in {"HEALTHY", "SUSPENDED", "OFFLINE"}: raise PlatformError("invalid_binding_state")
        item = self.session.get(PlatformBinding, binding_id)
        if not item: raise PlatformError("binding_not_found")
        item.state, item.last_error = state, reason or None
        for worker in self.session.scalars(select(PlatformWorker).where(PlatformWorker.binding_id == item.id)):
            if state == "SUSPENDED": worker.state = "DRAINING"
        audit(self.session, "BINDING_STATE_CHANGED", binding_id=item.id, catalog_id=item.catalog_id, summary=state)
        self.session.commit(); return item

    def set_binding_capacity(self, binding_id: str, max_concurrency: int):
        item = self.session.get(PlatformBinding, binding_id)
        if not item: raise PlatformError("binding_not_found")
        registered = self.session.get(WorkerInstance, item.agent_id)
        if not registered or max_concurrency > registered.max_concurrency:
            raise PlatformError("binding_capacity_exceeds_agent_capacity")
        workers = list(self.session.scalars(select(PlatformWorker).where(PlatformWorker.binding_id == item.id)))
        active_by_worker = {worker.id: len(list(self.session.scalars(select(WorkerCapacityLease).where(
            WorkerCapacityLease.worker_instance_id == worker.id,
            WorkerCapacityLease.status == "ACTIVE")))) for worker in workers}
        if any(max_concurrency < active for active in active_by_worker.values()):
            raise PlatformError("binding_capacity_below_active_load")
        old = item.max_concurrency
        item.max_concurrency = max_concurrency
        for worker in workers:
            worker.max_concurrency = max_concurrency
            if worker.state not in {"DRAINING", "OFFLINE", "ERROR"}:
                worker.state = "BUSY" if active_by_worker[worker.id] >= max_concurrency else "READY"
        audit(self.session, "BINDING_CAPACITY_UPDATED", catalog_id=item.catalog_id, binding_id=item.id,
              summary=f"最大并发 {old} → {max_concurrency}")
        self.session.commit(); return item

    def register_agent(self, *, agent_id: str, agent_version: str | None, candidates: list[dict]):
        agent = self.session.get(HostAgent, agent_id)
        if not agent:
            agent = HostAgent(id=agent_id); self.session.add(agent)
        agent.host_state, agent.agent_version, agent.last_heartbeat_at, agent.last_error = "ONLINE", agent_version, utcnow(), None
        # HostImage is an observed fact.  It never auto-creates a Candidate/Catalog/Binding.
        for candidate in candidates:
            if set(candidate) - {"image_ref", "image_id", "toolchain_version", "evidence"}: continue
            if not candidate.get("image_ref") or not candidate.get("image_id"): continue
            if is_governance_service_image(candidate["image_ref"]): continue
            existing = self.session.scalar(select(HostImage).where(HostImage.agent_id == agent_id,
                HostImage.image_id == candidate["image_id"]))
            if not existing:
                self.session.add(HostImage(agent_id=agent_id, image_ref=candidate["image_ref"], image_id=candidate["image_id"],
                    toolchain_version=candidate.get("toolchain_version"), evidence=candidate.get("evidence") or {}))
            else:
                existing.image_ref, existing.toolchain_version, existing.evidence = candidate["image_ref"], candidate.get("toolchain_version"), candidate.get("evidence") or {}
        for binding in self.session.scalars(select(PlatformBinding).where(PlatformBinding.agent_id == agent_id, PlatformBinding.state != "SUSPENDED")):
            binding.state, binding.last_heartbeat_at, binding.last_error = "HEALTHY", agent.last_heartbeat_at, None
            ensure_ready_worker(self.session, binding)
        self.session.commit(); return agent
