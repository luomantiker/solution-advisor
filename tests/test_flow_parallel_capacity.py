"""Controlled scheduling regression for concurrent multi-platform flows.

This test deliberately uses only the pytest temporary SQLite database and
temporary object store.  It does not contact a HostAgent, Docker, MinIO or a
physical board.  Real-board acceptance remains a separate deployment check;
here we protect the control-plane contract that lets compile containers use
three slots per platform while one Binding serializes its board measurements.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import select

from solution_advisor.artifacts.domain import Evidence, EvidencePhase, EvidenceType
from solution_advisor.artifacts.service import ArtifactService
from solution_advisor.common_analyzer.domain import WorkerCapacityLease
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationTask, TaskSnapshot
from solution_advisor.evaluations.s100_service import S100FlowExecutor
from solution_advisor.evaluations.x5_service import X5RealService
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.platforms.domain import HostAgent, PlatformBinding, PlatformCatalog, PlatformWorker


X5_AGENT = "parallel-x5-agent"
S100_AGENT = "parallel-s100-agent"
CAPACITY = 3


def _evidence(session, storage, task_id: str, platform: str, evidence_type: str,
              phase: str, payload: bytes) -> Evidence:
    artifact = ArtifactService(session, storage).put(payload, content_type="application/octet-stream")
    row = Evidence(
        evidence_type=evidence_type,
        phase=phase,
        task_id=task_id,
        platform=platform,
        artifact_id=artifact.id,
        toolchain_version="controlled-test",
        rule_package_version="controlled-test",
    )
    session.add(row)
    session.flush()
    return row


def _s100_compile(session, profile: ModelProfile, flow: EvaluationFlow, worker: PlatformWorker,
                  binding: PlatformBinding) -> EvaluationTask:
    frozen = {
        "platform_id": "S100", "agent_id": S100_AGENT, "worker_id": worker.id,
        "binding_id": binding.id, "runner_release": "s100-runner-1.0.0",
        "artifact_format": "s100_hbm", "parser": "s100-hrt-profile-1.0",
        "catalog_version": "3.7.0-r1",
    }
    snapshot = TaskSnapshot(
        model_asset_id=profile.model_asset_id, model_profile_id=profile.id,
        evaluation_template_version="parallel-capacity-test", report_template_version="flow-real-1.0",
        platform_package_versions={"S100": frozen}, platform_governance=frozen,
    )
    session.add(snapshot)
    session.flush()
    task = EvaluationTask(
        model_profile_id=profile.id, mode="REAL", platforms=["S100"], snapshot_id=snapshot.id,
        task_kind="S100_COMPILE", status="QUEUED", owner_subject="dev-user", flow_id=flow.id,
    )
    session.add(task)
    session.flush()
    snapshot.task_id = task.id
    return task


def _finish_x5_compile(session, storage, task: EvaluationTask) -> None:
    compiled = _evidence(
        session, storage, task.id, "X5", EvidenceType.X5_COMPILED_MODEL.value,
        EvidencePhase.COMPILATION.value, f"x5-bin-{task.id}".encode(),
    )
    X5RealService(session).finish(task.id, {
        "status": "SUCCEEDED", "runner_version": "1.0.0",
        "artifacts": [{"type": "compiled_model_artifact", "format": "x5_bin",
                       "filename": "model.bin", "sha256": compiled.artifact_id}],
    }, [compiled.id])


def _finish_s100_compile(session, storage, task: EvaluationTask) -> None:
    hbm = f"s100-hbm-{task.id}".encode()
    evidence = [
        _evidence(session, storage, task.id, "S100", kind, EvidencePhase.COMPILATION.value,
                  hbm if kind == EvidenceType.S100_COMPILED_MODEL.value else kind.encode())
        for kind in (
            EvidenceType.S100_STATIC_CHECK.value, EvidenceType.S100_COMPILE_LOG.value,
            EvidenceType.S100_COMPILE_SUMMARY.value, EvidenceType.S100_RUNNER_RESULT.value,
            EvidenceType.S100_COMPILED_MODEL.value,
        )
    ]
    compiled = evidence[-1]
    # The immutable result declaration must agree with the stored compiled
    # artifact.  Read it via the evidence relationship's explicit artifact id.
    from solution_advisor.artifacts.domain import Artifact
    stored = session.get(Artifact, compiled.artifact_id)
    S100FlowExecutor(session).complete(task.id, S100_AGENT, {
        "status": "SUCCEEDED",
        "artifacts": [{"type": "compiled_model_artifact", "format": "s100_hbm",
                       "filename": "nested/model.hbm", "sha256": stored.sha256,
                       "size_bytes": stored.size_bytes}],
    }, [item.id for item in evidence])


def _finish_x5_board(session, storage, task: EvaluationTask, index: int) -> None:
    evidence = _evidence(session, storage, task.id, "X5", EvidenceType.X5_BOARD_RESULT.value,
                         EvidencePhase.BOARD_TEST.value, b"x5-board-result")
    X5RealService(session).finish(task.id, {
        "status": "SUCCEEDED",
        "performance": {"status": "MEASURED", "metrics": {
            "fps": 100.0 + index, "average_latency_ms": 10.0 + index,
        }},
        "boundaries": {"accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED",
                       "power": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED"},
    }, [evidence.id])


def _finish_s100_board(session, storage, task: EvaluationTask, index: int) -> None:
    evidence = [
        _evidence(session, storage, task.id, "S100", kind, EvidencePhase.BOARD_TEST.value,
                  kind.encode())
        for kind in (
            EvidenceType.S100_BOARD_PREFLIGHT.value, EvidenceType.S100_BOARD_LOAD_LOG.value,
            EvidenceType.S100_BOARD_INFERENCE_LOG.value, EvidenceType.S100_BOARD_PROFILE_LOG.value,
            EvidenceType.S100_BOARD_PROFILE_CSV.value, EvidenceType.S100_BOARD_RESULT.value,
        )
    ]
    S100FlowExecutor(session).complete(task.id, S100_AGENT, {
        "status": "SUCCEEDED",
        "performance": {"status": "MEASURED", "metrics": {
            "fps": 200.0 + index, "average_latency_ms": 5.0 + index,
        }},
        "boundaries": {"accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED",
                       "power": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED"},
    }, [item.id for item in evidence])


def test_capacity_three_compiles_parallel_and_board_stages_serialize_per_binding_with_flow_pdfs(client, app, tmp_path):
    """Four X5+S100 flows: three parallel compiles, one board run per Binding."""
    assert str(app.state.artifact_storage.root).startswith(str(tmp_path))
    session = app.state.session_factory()
    try:
        asset = ModelAsset(
            sha256="a" * 64, original_filename="controlled.onnx", size_bytes=16,
            owner_subject="dev-user",
        )
        profile = ModelProfile(
            model_asset_id="pending", onnx_sha256=asset.sha256, analyzer_version="test",
            analysis={"summary": {"node_count": 1, "operator_counts": {"Conv": 1}}},
        )
        session.add(asset)
        session.flush()
        profile.model_asset_id = asset.id
        session.add(profile)
        session.flush()

        x5_catalog = PlatformCatalog(
            platform_id="X5", version="1.2.8", display_name="X5 / 1.2.8", state="AVAILABLE",
            image_lock={"digest": "sha256:x5-parallel"}, runner={"version": "1.0.0"},
        )
        s100_catalog = PlatformCatalog(
            platform_id="S100", version="3.7.0-r1", display_name="S100 / 3.7.0-r1", state="AVAILABLE",
            image_lock={"digest": "sha256:s100-parallel"},
            runner={"version": "s100-runner-1.0.0", "content_sha256": "b" * 64},
        )
        session.add_all([x5_catalog, s100_catalog, HostAgent(id=X5_AGENT, host_state="ONLINE"),
                         HostAgent(id=S100_AGENT, host_state="ONLINE")])
        session.flush()
        x5_binding = PlatformBinding(
            agent_id=X5_AGENT, catalog_id=x5_catalog.id, platform_id="X5", state="HEALTHY",
            capabilities=["static_check", "compile", "board_smoke"], max_concurrency=CAPACITY,
            image_lock_version="sha256:x5-parallel", runner_version="1.0.0",
        )
        s100_binding = PlatformBinding(
            agent_id=S100_AGENT, catalog_id=s100_catalog.id, platform_id="S100", state="HEALTHY",
            capabilities=["static_check", "compile", "board_smoke"], max_concurrency=CAPACITY,
            image_lock_version="sha256:s100-parallel", runner_version="s100-runner-1.0.0",
        )
        session.add_all([x5_binding, s100_binding])
        session.flush()
        x5_worker = PlatformWorker(
            binding_id=x5_binding.id, agent_id=X5_AGENT, platform_id="X5", state="READY",
            max_concurrency=CAPACITY, runner={"version": "1.0.0"},
        )
        s100_worker = PlatformWorker(
            binding_id=s100_binding.id, agent_id=S100_AGENT, platform_id="S100", state="READY",
            max_concurrency=CAPACITY, runner={"version": "s100-runner-1.0.0"},
        )
        session.add_all([x5_worker, s100_worker])
        session.commit()

        flows = []
        x5_compiles = []
        s100_compiles = []
        for _ in range(4):
            flow = EvaluationFlow(model_profile_id=profile.id, owner_subject="dev-user", preset="standard-performance-1.0")
            session.add(flow)
            session.flush()
            flows.append(flow)
            x5_compiles.append(X5RealService(session).create(profile.id, "dev-user", x5_catalog.id, flow.id))
            s100_compiles.append(_s100_compile(session, profile, flow, s100_worker, s100_binding))
        session.commit()

        x5 = X5RealService(session)
        s100 = S100FlowExecutor(session)
        claimed_x5 = [x5.claim(X5_AGENT) for _ in range(CAPACITY)]
        claimed_s100 = [s100.claim(S100_AGENT) for _ in range(CAPACITY)]
        assert [item.id for item in claimed_x5] == [item.id for item in x5_compiles[:CAPACITY]]
        assert [item.id for item in claimed_s100] == [item.id for item in s100_compiles[:CAPACITY]]
        assert x5.claim(X5_AGENT) is None
        assert s100.claim(S100_AGENT) is None
        active = list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.status == "ACTIVE")))
        assert sorted((item.worker_instance_id, item.slot_index) for item in active) == sorted(
            [(x5_worker.id, slot) for slot in range(CAPACITY)] + [(s100_worker.id, slot) for slot in range(CAPACITY)]
        )

        for task in claimed_x5:
            x5.start(task.id, X5_AGENT)
            _finish_x5_compile(session, app.state.artifact_storage, task)
        for task in claimed_s100:
            s100.start(task.id, S100_AGENT)
            _finish_s100_compile(session, app.state.artifact_storage, task)

        # The fourth compile is released from its queue only after a slot is
        # free.  Board work cannot leapfrog a queued compile in this fixed
        # scheduler policy.
        fourth_x5 = x5.claim(X5_AGENT)
        fourth_s100 = s100.claim(S100_AGENT)
        assert fourth_x5.id == x5_compiles[3].id
        assert fourth_s100.id == s100_compiles[3].id
        x5.start(fourth_x5.id, X5_AGENT)
        s100.start(fourth_s100.id, S100_AGENT)
        _finish_x5_compile(session, app.state.artifact_storage, fourth_x5)
        _finish_s100_compile(session, app.state.artifact_storage, fourth_s100)

        x5_boards = list(session.scalars(select(EvaluationTask).where(
            EvaluationTask.task_kind == "REAL_BOARD_SMOKE").order_by(EvaluationTask.created_at)))
        s100_boards = list(session.scalars(select(EvaluationTask).where(
            EvaluationTask.task_kind == "S100_BOARD_PERF").order_by(EvaluationTask.created_at)))
        assert len(x5_boards) == len(s100_boards) == 4

        # Different Bindings may use their physical boards concurrently, but
        # each Binding has exactly one active board phase despite capacity=3.
        for index in range(4):
            x5_board = x5.claim(X5_AGENT)
            s100_board = s100.claim(S100_AGENT)
            assert x5_board.id == x5_boards[index].id
            assert s100_board.id == s100_boards[index].id
            assert x5_board.task_kind == "REAL_BOARD_SMOKE"
            assert s100_board.task_kind == "S100_BOARD_PERF"
            x5.start(x5_board.id, X5_AGENT)
            s100.start(s100_board.id, S100_AGENT)
            assert x5.claim(X5_AGENT) is None
            assert s100.claim(S100_AGENT) is None
            _finish_x5_board(session, app.state.artifact_storage, x5_board, index)
            _finish_s100_board(session, app.state.artifact_storage, s100_board, index)

        assert not list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.status == "ACTIVE")))
        session.commit()
        flow_ids = [flow.id for flow in flows]
    finally:
        session.close()

    for flow_id in flow_ids:
        report = client.get(f"/api/v1/evaluation-flows/{flow_id}/report")
        assert report.status_code == 200 and report.json()["status"] == "SUCCEEDED"
        pdf = client.get(f"/api/v1/evaluation-flows/{flow_id}/report/download")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf.content)).pages)
        assert "X5" in text and "S100" in text
        assert len(PdfReader(BytesIO(pdf.content)).pages) >= 2
