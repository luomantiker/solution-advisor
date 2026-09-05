from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import select

from solution_advisor.common_analyzer.domain import WorkerCapacityLease
from solution_advisor.common_analyzer.service import AnalysisService
from solution_advisor.evaluations.domain import EvaluationResult
from solution_advisor.evaluations.x5_service import X5RealService
from solution_advisor.model_assets.domain import ModelProfile

ADMIN = {"Authorization": "Bearer development-admin-token"}
WORKER = {"Authorization": "Bearer development-worker-token"}


def registration_body(max_concurrency: int = 1):
    return {"instance_id": "x5-a", "worker_type": "x5", "image_ref": "x5:test",
            "image_id": "sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593", "toolchain_version": "1.24.3",
            "platform_package_version": "1.0.0", "capabilities": ["static_check", "compile"],
            "max_concurrency": max_concurrency}


def board_registration_body(max_concurrency: int = 1):
    body = registration_body(max_concurrency)
    body["capabilities"] = ["static_check", "compile", "board_smoke"]
    return body


def make_profile(client, model_bytes):
    response = client.post("/api/v1/model-assets", files={"file": ("minimal.onnx", model_bytes)})
    session = client.app.state.session_factory()
    try:
        AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(
            response.json()["analysis_task"]["id"])
    finally:
        session.close()

    return client.get(f"/api/v1/analysis-tasks/{response.json()['analysis_task']['id']}").json()["profile_id"]


def register_x5(client, max_concurrency: int = 1):
    assert client.post("/api/internal/workers/register", headers=WORKER,
                       json=board_registration_body(max_concurrency)).status_code == 200
    catalog = next(item for item in client.get("/api/admin/platform-catalogs", headers=ADMIN).json()
                   if item["platform_id"] == "X5" and item["state"] == "AVAILABLE")
    created = client.post("/api/admin/platform-bindings", headers=ADMIN, json={
        "agent_id": "x5-a", "catalog_id": catalog["id"], "capabilities": ["static_check", "compile", "board_smoke"], "max_concurrency": max_concurrency,
    })
    assert created.status_code == 201


def test_real_task_is_admin_only_and_releases_persisted_lease(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    register_x5(client)
    platforms = client.get("/api/v1/evaluation-platforms").json()
    assert next(item for item in platforms if item["platform_id"] == "X5")["available"] is True
    assert next(item for item in platforms if item["platform_id"] == "S100")["available"] is False
    assert client.post("/api/v1/evaluation-tasks", json={
        "model_profile_id": profile_id, "mode": "REAL", "platforms": ["X5"],
    }).status_code == 422
    assert client.post("/api/admin/x5-real-tasks", headers={"Authorization": ""}, json={"model_profile_id": profile_id}).status_code == 401
    created = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                          json={"model_profile_id": profile_id})
    assert created.status_code == 201
    task_id = created.json()["id"]

    # The user-facing task endpoint exposes the persisted asynchronous state;
    # a newly created REAL task must not be mistaken for a completed DEMO task.
    public_detail = client.get(f"/api/v1/evaluation-tasks/{task_id}")
    assert public_detail.status_code == 200
    assert public_detail.json()["mode"] == "REAL"
    assert public_detail.json()["task_kind"] == "X5_COMPILE"
    assert public_detail.json()["status"] == "QUEUED"

    session = client.app.state.session_factory()
    try:
        service = X5RealService(session)
        task = service.claim("x5-a")
        assert task.id == task_id and task.status == "CLAIMED"
        lease = session.scalar(select(WorkerCapacityLease).where(
            WorkerCapacityLease.task_id == task_id, WorkerCapacityLease.status == "ACTIVE"))
        assert lease is not None and lease.slot_index == 0
        assert service.start(task_id, "x5-a").status == "RUNNING"
        service.finish(task_id, {
            "status": "SUCCEEDED", "toolchain": {"hb_mapper": "1.24.3"},
            "platform_package": {"id": "x5", "version": "1.0.0"},
            "runner_version": "1.0.0", "rule_version": "1.0.0",
            "artifacts": [{"type": "compiled_model_artifact", "format": "x5_bin",
                           "filename": "model.bin", "sha256": "a" * 64}],
            "board_validation": "NOT_EXECUTED", "performance": "NOT_VERIFIED",
            "accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED",
            "deployment_recommendation": "NOT_VERIFIED",
        }, [])
        assert session.scalar(select(EvaluationResult).where(EvaluationResult.task_id == task_id)).platform_result["board_stage"]["reason_code"] == "compiled_model_artifact_not_found"
        assert lease.status == "RELEASED"
    finally:
        session.close()

    detail = client.get(f"/api/admin/x5-real-tasks/{task_id}", headers=ADMIN)
    assert detail.json()["status"] == "SUCCEEDED"
    report = client.get(f"/api/v1/reports/{task_id}").json()
    assert report["mode"] == "REAL"
    pdf = client.get(f"/api/v1/reports/{task_id}/download")
    text = PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert "X5 REAL 编译记录" in text and "未执行" in text
    assert "推荐部署建议" not in text and "已实测" not in text


def test_real_task_cancel_and_retry(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    register_x5(client)
    task = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                       json={"model_profile_id": profile_id}).json()
    cancelled = client.post(f"/api/admin/x5-real-tasks/{task['id']}/cancel", headers=ADMIN)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    retried = client.post(f"/api/admin/x5-real-tasks/{task['id']}/retry", headers=ADMIN)
    assert retried.status_code == 200 and retried.json()["status"] == "QUEUED"


def test_real_capacity_timeout_and_retry(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    register_x5(client)
    first = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                        json={"model_profile_id": profile_id}).json()["id"]
    second = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                         json={"model_profile_id": profile_id}).json()["id"]
    session = client.app.state.session_factory()
    try:
        service = X5RealService(session)
        assert service.claim("x5-a").id == first
        # The second task remains QUEUED because the only persisted slot is active.
        assert service.claim("x5-a") is None
    finally:
        session.close()

    timed_out = client.post(f"/api/admin/x5-real-tasks/{first}/timeout", headers=ADMIN)
    assert timed_out.status_code == 200 and timed_out.json()["status"] == "TIMEOUT"
    assert client.post(f"/api/admin/x5-real-tasks/{first}/retry", headers=ADMIN).status_code == 200
    session = client.app.state.session_factory()
    try:
        task = X5RealService(session).claim("x5-a")
        assert task.id in {first, second}
        active = list(session.scalars(select(WorkerCapacityLease).where(
            WorkerCapacityLease.worker_instance_id == task.worker_instance_id,
            WorkerCapacityLease.status == "ACTIVE")))
        assert len(active) == 1
    finally:
        session.close()


def test_three_compile_slots_are_claimed_independently(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    register_x5(client, max_concurrency=3)
    task_ids = [client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                            json={"model_profile_id": profile_id}).json()["id"] for _ in range(4)]
    session = client.app.state.session_factory()
    try:
        service = X5RealService(session)
        claimed = [service.claim("x5-a") for _ in range(3)]
        assert [task.id for task in claimed] == task_ids[:3]
        leases = list(session.scalars(select(WorkerCapacityLease).where(
            WorkerCapacityLease.status == "ACTIVE").order_by(WorkerCapacityLease.slot_index)))
        assert [lease.slot_index for lease in leases] == [0, 1, 2]
        assert service.claim("x5-a") is None
    finally:
        session.close()
    # The generic HostAgent management view aggregates leases owned by the
    # dynamic PlatformWorker instead of falsely showing this Host as idle.
    capacity = client.get("/api/admin/worker-instances/x5-a/capacity", headers=ADMIN).json()
    assert capacity["running_containers"] == 3 and capacity["free_slots"] == 0
    listed_leases = client.get("/api/admin/worker-instances/x5-a/leases", headers=ADMIN).json()
    assert sorted(item["slot_index"] for item in listed_leases if item["status"] == "ACTIVE") == [0, 1, 2]


def test_worker_control_plane_claim_input_evidence_and_completion(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    register_x5(client)
    task_id = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                          json={"model_profile_id": profile_id}).json()["id"]
    claim = client.post("/api/internal/workers/x5-a/x5-tasks/claim", headers=WORKER)
    assert claim.status_code == 200 and claim.json()["id"] == task_id
    model = client.get(f"/api/internal/workers/x5-a/x5-tasks/{task_id}/model", headers=WORKER)
    assert model.status_code == 200 and model.headers["x-content-sha256"] == claim.json()["model"]["sha256"]
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{task_id}/start", headers=WORKER).json()["status"] == "RUNNING"
    evidence = client.post(f"/api/internal/workers/x5-a/x5-tasks/{task_id}/evidence", headers=WORKER,
        data={"evidence_type": "x5_runner_result", "phase": "COMPILATION"},
        files={"file": ("result.json", b'{"status":"SUCCEEDED"}', "application/json")})
    assert evidence.status_code == 201 and evidence.json()["sha256"]
    complete = client.post(f"/api/internal/workers/x5-a/x5-tasks/{task_id}/complete", headers=WORKER,
        json={"result": {"status": "SUCCEEDED", "artifacts": [], "toolchain": {}, "platform_package": {}},
              "evidence_ids": [evidence.json()["id"]]})
    assert complete.status_code == 200
    # A duplicated/late HostAgent failure report cannot overwrite committed success.
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{task_id}/fail", headers=WORKER,
                       json={"reason_code": "late_transport_error"}).status_code == 200
    assert client.get(f"/api/admin/x5-real-tasks/{task_id}", headers=ADMIN).json()["status"] == "SUCCEEDED"


def test_board_smoke_uses_only_compiled_artifact_and_preserves_boundaries(client, model_bytes):
    profile_id = make_profile(client, model_bytes)
    assert client.post("/api/internal/workers/register", headers=WORKER, json=board_registration_body()).status_code == 200
    catalog = next(item for item in client.get("/api/admin/platform-catalogs", headers=ADMIN).json() if item["platform_id"] == "X5")
    assert client.post("/api/admin/platform-bindings", headers=ADMIN, json={"agent_id":"x5-a", "catalog_id":catalog["id"], "capabilities":["static_check","compile","board_smoke"], "max_concurrency":1}).status_code == 201
    compile_task = client.post("/api/admin/x5-real-tasks", headers=ADMIN,
                               json={"model_profile_id": profile_id}).json()["id"]
    assert client.post("/api/internal/workers/x5-a/x5-tasks/claim", headers=WORKER).status_code == 200
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{compile_task}/start", headers=WORKER).status_code == 200
    compiled = client.post(f"/api/internal/workers/x5-a/x5-tasks/{compile_task}/evidence", headers=WORKER,
        data={"evidence_type": "x5_compiled_model", "phase": "COMPILATION"},
        files={"file": ("model.bin", b"real-compiled-bin", "application/octet-stream")})
    assert compiled.status_code == 201
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{compile_task}/complete", headers=WORKER,
        json={"result": {"status": "SUCCEEDED"}, "evidence_ids": [compiled.json()["id"]]}).status_code == 200

    assert client.post("/api/admin/x5-board-smoke-tasks", headers={"Authorization": ""}, json={"compiled_task_id": compile_task}).status_code == 401
    board = client.post("/api/admin/x5-board-smoke-tasks", headers=ADMIN,
        json={"compiled_task_id": compile_task})
    assert board.status_code == 201 and board.json()["task_kind"] == "REAL_BOARD_SMOKE"
    # Compile completion has already enqueued this board stage. The endpoint is
    # idempotent and returns that same automatic child rather than duplicating it.
    assert board.json()["source_task_id"] == compile_task
    board_id = board.json()["id"]
    compile_report = client.get(f"/api/v1/reports/{compile_task}").json()
    assert compile_report["sections"]["x5_compile"]["board_stage"]["task_id"] == board_id
    assert compile_report["sections"]["x5_compile"]["board_stage"]["status"] == "QUEUED"
    session = client.app.state.session_factory()
    try: asset_id = session.get(ModelProfile, profile_id).model_asset_id
    finally: session.close()
    listed = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()
    assert [item["id"] for item in listed] == [compile_task]
    assert listed[0]["progress"]["label"] == "编译完成，等待板端性能评测"
    # Board tasks share the REAL state machine: an administrator can cancel
    # before execution and safely retry the same immutable source artifact.
    assert client.post(f"/api/admin/x5-real-tasks/{board_id}/cancel", headers=ADMIN).json()["status"] == "CANCELLED"
    assert client.post(f"/api/admin/x5-real-tasks/{board_id}/retry", headers=ADMIN).json()["status"] == "QUEUED"
    claim = client.post("/api/internal/workers/x5-a/x5-tasks/claim", headers=WORKER)
    assert claim.json()["task_kind"] == "REAL_BOARD_SMOKE"
    artifact = client.get(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/compiled-model", headers=WORKER)
    assert artifact.status_code == 200 and artifact.content == b"real-compiled-bin"
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/start", headers=WORKER).status_code == 200
    # A compile-only evidence type is rejected for board work.
    forbidden = client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/evidence", headers=WORKER,
        data={"evidence_type": "x5_compile_log", "phase": "BOARD_TEST"},
        files={"file": ("compile.log", b"not-board", "text/plain")})
    assert forbidden.status_code == 422
    board_evidence = client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/evidence", headers=WORKER,
        data={"evidence_type": "x5_board_result", "phase": "BOARD_TEST"},
        files={"file": ("result.json", b'{"status":"SUCCEEDED"}', "application/json")})
    assert board_evidence.status_code == 201 and len(board_evidence.json()["sha256"]) == 64
    raw_profile = client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/evidence", headers=WORKER,
        data={"evidence_type": "BOARD_LOG", "phase": "BOARD_TEST"},
        files={"file": ("profile.json", b'{"perf_result":{"FPS":12.5,"average_latency":8.0}}', "application/json")})
    assert raw_profile.status_code == 201
    preflight = client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/evidence", headers=WORKER,
        data={"evidence_type": "x5_board_preflight", "phase": "BOARD_TEST"},
        files={"file": ("board_preflight.json", b'{"system":"Linux test","runtime":"1.24.5","bpu_access":"ACCESSIBLE"}', "application/json")})
    assert preflight.status_code == 201
    result = {"status": "SUCCEEDED", "board_preflight": "SUCCEEDED", "model_transfer": "SUCCEEDED",
              "model_load": "NOT_SEPARABLE_BY_RUNTIME_COMMAND", "single_runtime_invocation": "SUCCEEDED",
              "model_bin_sha256": compiled.json()["sha256"], "input_sha256": "NOT_COLLECTED_RUNTIME_INTERNAL_INPUT",
              "output_sha256": "NOT_COLLECTED_RUNTIME_PROFILE_ONLY", "runtime": {"command": "hrt_model_exec perf", "version": "test"},
              "performance": {"status": "MEASURED", "evidence_level": "BOARD_MEASURED", "runner": "hrt_model_exec perf",
                              "parser_version": "test", "metrics": {"fps": 1.2, "average_latency_ms": 3.4},
                              "running_condition": {"thread_num": 1, "frame_count": 200, "run_time_ms": 10}, "segments": [],
                              "cpu_execution_segment_present": True},
              "boundaries": {"performance": "MEASURED", "accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED",
                             "power": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED"}}
    assert client.post(f"/api/internal/workers/x5-a/x5-tasks/{board_id}/complete", headers=WORKER,
        json={"result": result, "evidence_ids": [board_evidence.json()["id"]]}).status_code == 200
    completed_workflow = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()[0]
    assert completed_workflow["progress"]["label"] == "评估完成（编译与板端性能）"
    report = client.get(f"/api/v1/reports/{board_id}").json()
    assert report["task_kind"] == "REAL_BOARD_SMOKE"
    pdf = client.get(f"/api/v1/reports/{board_id}/download")
    text = PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert "X5 REAL 板端性能评测记录" in text
    assert "FPS" in text and "1.2" in text and "未验证" in text
    parsed = client.post(f"/api/admin/x5-board-smoke-tasks/{board_id}/parse-performance", headers=ADMIN)
    assert parsed.status_code == 200 and parsed.json()["performance"]["metrics"]["fps"] == 12.5
    assert parsed.json()["performance"]["environment"]["system"] == "Linux test"
    assert client.post(f"/api/admin/x5-board-smoke-tasks/{board_id}/parse-performance", headers={"Authorization": ""}).status_code == 401
