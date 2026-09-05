"""Contract tests for the S100-only internal Worker surface."""
from hashlib import sha256

from solution_advisor.artifacts.domain import Artifact
from solution_advisor.artifacts.service import ArtifactService
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationTask, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile
from solution_advisor.platforms.domain import HostAgent, PlatformBinding, PlatformWorker


WORKER = {"Authorization": "Bearer development-worker-token"}
AGENT = "s100-test-agent"


def seeded_s100_task(app):
    session = app.state.session_factory()
    try:
        model = b"minimal controlled onnx fixture"
        model_artifact = ArtifactService(session, app.state.artifact_storage).put(model, content_type="application/octet-stream")
        asset = ModelAsset(sha256=sha256(model).hexdigest(), original_filename="fixture.onnx", size_bytes=len(model), artifact_id=model_artifact.id, owner_subject="dev-user")
        session.add(asset); session.flush()
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test", analysis={})
        session.add(profile); session.flush()
        agent = HostAgent(id=AGENT, host_state="ONLINE")
        binding = PlatformBinding(agent_id=AGENT, catalog_id="catalog_s100_test", platform_id="S100", state="HEALTHY", capabilities=["static_check", "compile", "board_smoke"], max_concurrency=1, image_lock_version="3.7.0", runner_version="s100-runner-1.0")
        session.add_all([agent, binding]); session.flush()
        worker = PlatformWorker(binding_id=binding.id, agent_id=AGENT, platform_id="S100", state="READY", max_concurrency=1, runner={"version":"s100-runner-1.0"})
        session.add(worker); session.flush()
        frozen = {"platform_id":"S100", "agent_id":AGENT, "worker_id":worker.id, "binding_id":binding.id, "runner_release":"s100-runner-1.0", "artifact_format":"s100_hbm", "parser":"s100-hrt-profile-1.0"}
        flow = EvaluationFlow(model_profile_id=profile.id, owner_subject="dev-user", platform_snapshots={"catalog_s100_test": frozen})
        session.add(flow); session.flush()
        snapshot = TaskSnapshot(model_asset_id=asset.id, model_profile_id=profile.id, platform_package_versions={"S100":frozen}, platform_governance=frozen)
        session.add(snapshot); session.flush()
        task = EvaluationTask(model_profile_id=profile.id, mode="REAL", platforms=["S100"], snapshot_id=snapshot.id, task_kind="S100_COMPILE", flow_id=flow.id, owner_subject="dev-user")
        session.add(task); session.flush(); snapshot.task_id=task.id; session.commit()
        return task.id
    finally:
        session.close()


def upload(client, task_id, evidence_type, payload, phase="COMPILATION"):
    return client.post(f"/api/internal/workers/{AGENT}/s100-tasks/{task_id}/evidence", headers=WORKER,
        data={"evidence_type":evidence_type, "phase":phase}, files={"file":("evidence.bin",payload)})


def test_s100_compile_contract_creates_only_same_flow_board_stage(client, app):
    task_id = seeded_s100_task(app)
    claim = client.post(f"/api/internal/workers/{AGENT}/s100-tasks/claim", headers=WORKER)
    assert claim.status_code == 200 and claim.json()["id"] == task_id
    assert client.post(f"/api/internal/workers/{AGENT}/s100-tasks/{task_id}/start", headers=WORKER).status_code == 200
    hbm = b"realistic-hbm-bytes"
    uploads = [upload(client, task_id, kind, hbm if kind == "s100_compiled_model" else kind.encode()) for kind in [
        "s100_static_check", "s100_compile_log", "s100_compile_summary", "s100_runner_result", "s100_compiled_model"]]
    assert all(item.status_code == 201 for item in uploads)
    evidence_ids = [item.json()["id"] for item in uploads]
    result = {"status":"SUCCEEDED", "artifacts":[{"type":"compiled_model_artifact", "format":"s100_hbm", "filename":"nested/model.hbm", "sha256":sha256(hbm).hexdigest(), "size_bytes":len(hbm)}]}
    complete = client.post(f"/api/internal/workers/{AGENT}/s100-tasks/{task_id}/complete", headers=WORKER, json={"result":result,"evidence_ids":evidence_ids})
    assert complete.status_code == 200
    session = app.state.session_factory()
    try:
        board = session.query(EvaluationTask).filter_by(flow_id=session.get(EvaluationTask, task_id).flow_id, task_kind="S100_BOARD_PERF").one()
        assert board.source_task_id == task_id and board.status == "QUEUED"
    finally:
        session.close()


def test_s100_rejects_wrong_artifact_contract_without_board_stage(client, app):
    task_id = seeded_s100_task(app)
    assert client.post(f"/api/internal/workers/{AGENT}/s100-tasks/claim", headers=WORKER).status_code == 200
    assert client.post(f"/api/internal/workers/{AGENT}/s100-tasks/{task_id}/start", headers=WORKER).status_code == 200
    evidence_ids = [upload(client, task_id, kind, kind.encode()).json()["id"] for kind in [
        "s100_static_check", "s100_compile_log", "s100_compile_summary", "s100_runner_result", "s100_compiled_model"]]
    bad = {"status":"SUCCEEDED", "artifacts":[{"type":"compiled_model_artifact", "format":"s100_hbm", "filename":"not-hbm.bin", "sha256":"0"*64, "size_bytes":1}]}
    response = client.post(f"/api/internal/workers/{AGENT}/s100-tasks/{task_id}/complete", headers=WORKER, json={"result":bad,"evidence_ids":evidence_ids})
    assert response.status_code == 422
    session = app.state.session_factory()
    try:
        assert session.query(EvaluationTask).filter_by(task_kind="S100_BOARD_PERF").count() == 0
        failed = session.get(EvaluationTask, task_id)
        assert failed.status == "FAILED" and failed.error_code == "s100_artifact_contract_invalid"
    finally:
        session.close()


def test_s100_worker_identity_is_frozen_to_agent_and_snapshot(client, app):
    task_id = seeded_s100_task(app)
    # A valid Worker Token cannot turn an X5/other Agent path into an S100 slot.
    assert client.post("/api/internal/workers/x5-test-agent/s100-tasks/claim", headers=WORKER).status_code == 204
    assert client.post(f"/api/internal/workers/x5-test-agent/s100-tasks/{task_id}/start", headers=WORKER).status_code == 403
    assert client.post(f"/api/internal/workers/{AGENT}/s100-tasks/claim", headers=WORKER).status_code == 200


def test_flow_is_the_only_user_deletion_boundary_for_internal_s100_stages(client, app):
    task_id = seeded_s100_task(app)
    session = app.state.session_factory()
    try:
        compile_task = session.get(EvaluationTask, task_id)
        compile_task.status = "SUCCEEDED"
        board = EvaluationTask(
            model_profile_id=compile_task.model_profile_id, mode="REAL", platforms=["S100"],
            task_kind="S100_BOARD_PERF", source_task_id=compile_task.id, flow_id=compile_task.flow_id,
            owner_subject=compile_task.owner_subject, status="SUCCEEDED",
        )
        session.add(board); session.commit()
        flow_id = compile_task.flow_id
    finally:
        session.close()

    # Internal compiler/board records cannot be removed independently.
    rejected = client.delete(f"/api/v1/evaluation-tasks/{task_id}")
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "evaluation_flow_delete_required"
    listed = client.get(f"/api/v1/evaluation-flows/{flow_id}")
    assert listed.status_code == 200 and {item["kind"] for item in listed.json()["stages"]} == {"S100_COMPILE", "S100_BOARD_PERF"}
    assert client.delete(f"/api/v1/evaluation-flows/{flow_id}").status_code == 204
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}").status_code == 404
    session = app.state.session_factory()
    try:
        assert session.get(EvaluationTask, task_id) is None
        assert not session.query(EvaluationTask).filter_by(flow_id=flow_id).count()
    finally:
        session.close()


def test_running_flow_cannot_be_deleted(client, app):
    task_id = seeded_s100_task(app)
    session = app.state.session_factory()
    try:
        flow_id = session.get(EvaluationTask, task_id).flow_id
    finally:
        session.close()
    response = client.delete(f"/api/v1/evaluation-flows/{flow_id}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "evaluation_flow_not_terminal"


def test_model_reports_list_one_flow_not_its_internal_s100_stages(client, app):
    task_id = seeded_s100_task(app)
    session = app.state.session_factory()
    try:
        compile_task = session.get(EvaluationTask, task_id)
        compile_task.status = "SUCCEEDED"
        session.add(EvaluationTask(
            model_profile_id=compile_task.model_profile_id, mode="REAL", platforms=["S100"],
            task_kind="S100_BOARD_PERF", source_task_id=compile_task.id, flow_id=compile_task.flow_id,
            owner_subject=compile_task.owner_subject, status="SUCCEEDED",
        ))
        profile = session.get(ModelProfile, compile_task.model_profile_id)
        flow_id, asset_id = compile_task.flow_id, profile.model_asset_id
        session.add(ModelAssetAccess(model_asset_id=asset_id, subject="dev-user", access_kind="OWNER", granted_by="dev-user"))
        session.commit()
    finally:
        session.close()

    reports = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks")
    assert reports.status_code == 200
    assert reports.json() and reports.json()[0]["id"] == flow_id
    assert reports.json()[0]["resource_kind"] == "FLOW"
    assert reports.json()[0]["platforms"] == ["S100"]
    assert task_id not in {item["id"] for item in reports.json()}
    assert client.delete(f"/api/v1/evaluation-flows/{flow_id}").status_code == 204
    assert client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json() == []
