from solution_advisor.common_analyzer.service import AnalysisService
from solution_advisor.evaluations.domain import EvaluationTask, EvaluationTaskShare
from solution_advisor.model_assets.domain import ResourceAccessAudit
from sqlalchemy import select


USER_A = "Bearer development-user-token"
USER_B = "Bearer development-user-2-token"


def _upload_and_profile(client, model_bytes):
    response = client.post("/api/v1/model-assets", files={"file": ("minimal.onnx", model_bytes)})
    assert response.status_code == 201
    task_id = response.json()["analysis_task"]["id"]
    session = client.app.state.session_factory()
    try:
        AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(task_id)
    finally:
        session.close()
    return response.json()["asset"]["id"], task_id, client.get(f"/api/v1/analysis-tasks/{task_id}").json()["profile_id"]


def test_shared_result_is_listed_under_model_without_exposing_model_file(client, model_bytes):
    client.headers["Authorization"] = USER_A
    asset_id, analysis_id, profile_id = _upload_and_profile(client, model_bytes)
    task_id = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]}).json()["id"]

    client.headers["Authorization"] = USER_B
    assert client.get("/api/v1/model-assets").json() == []
    assert client.get(f"/api/v1/model-assets/{asset_id}").status_code == 404
    assert client.get(f"/api/v1/model-profiles/{profile_id}").status_code == 404
    assert client.get(f"/api/v1/analysis-tasks/{analysis_id}").status_code == 404
    assert client.get(f"/api/v1/reports/{task_id}").status_code == 404

    client.headers["Authorization"] = USER_A
    shared = client.post(f"/api/v1/evaluation-tasks/{task_id}/shares", json={"recipient": "dev-user-2", "include_model": False})
    assert shared.status_code == 201 and shared.json()["include_model"] is False

    client.headers["Authorization"] = USER_B
    models = client.get("/api/v1/model-assets").json()
    assert len(models) == 1 and models[0]["id"] == asset_id and models[0]["access"] == "SHARED_RESULT_ONLY"
    detail = client.get(f"/api/v1/model-assets/{asset_id}")
    assert detail.status_code == 200 and detail.json()["can_download_model"] is False and detail.json()["profile"] is None
    reports = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()
    assert reports[0]["id"] == task_id and reports[0]["access"] == "SHARED" and reports[0]["include_model"] is False
    assert client.get(f"/api/v1/reports/{task_id}/download").status_code == 200
    assert client.get(f"/api/v1/model-assets/{asset_id}/download").status_code == 403
    assert client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["Intel"]}).status_code == 403

    client.headers["Authorization"] = USER_A
    assert client.delete(f"/api/v1/evaluation-tasks/{task_id}/shares/dev-user-2").status_code == 204
    client.headers["Authorization"] = USER_B
    assert client.get(f"/api/v1/model-assets/{asset_id}").status_code == 404
    assert client.get(f"/api/v1/reports/{task_id}").status_code == 404


def test_shared_result_can_optionally_include_model_and_create_own_history(client, model_bytes):
    client.headers["Authorization"] = USER_A
    asset_id, _, profile_id = _upload_and_profile(client, model_bytes)
    task_id = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]}).json()["id"]
    client.headers["Authorization"] = USER_B
    assert client.get("/api/v1/model-assets").status_code == 200
    client.headers["Authorization"] = USER_A
    assert client.post(f"/api/v1/evaluation-tasks/{task_id}/shares", json={"recipient": "dev-user-2", "include_model": True}).status_code == 201

    client.headers["Authorization"] = USER_B
    model = client.get(f"/api/v1/model-assets/{asset_id}").json()
    assert model["access"] == "SHARED_WITH_MODEL" and model["can_download_model"] is True and model["profile"]["id"] == profile_id
    assert client.get(f"/api/v1/model-assets/{asset_id}/download").content == model_bytes
    own_task = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["Intel"]})
    assert own_task.status_code == 201
    reports = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()
    assert {item["id"] for item in reports} == {task_id, own_task.json()["id"]}

    client.headers["Authorization"] = USER_A
    assert client.delete(f"/api/v1/evaluation-tasks/{task_id}/shares/dev-user-2").status_code == 204
    client.headers["Authorization"] = USER_B
    assert client.get(f"/api/v1/reports/{task_id}").status_code == 404
    detail_after_revoke = client.get(f"/api/v1/model-assets/{asset_id}").json()
    assert detail_after_revoke["access"] == "OWN_RESULT_ONLY"
    assert client.get(f"/api/v1/model-assets/{asset_id}/download").status_code == 403
    session = client.app.state.session_factory()
    try:
        assert [item.action for item in session.scalars(select(ResourceAccessAudit).order_by(ResourceAccessAudit.created_at))] == ["SHARED", "REVOKED"]
    finally:
        session.close()


def test_completed_results_for_one_model_can_be_shared_in_one_batch(client, model_bytes):
    client.headers["Authorization"] = USER_A
    asset_id, _, profile_id = _upload_and_profile(client, model_bytes)
    first = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]}).json()["id"]
    second = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["Intel"]}).json()["id"]
    assert client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()[0]["progress"] == {"percent": 100, "label": "已完成", "completed": True}
    client.headers["Authorization"] = USER_B
    assert client.get("/api/v1/model-assets").status_code == 200
    client.headers["Authorization"] = USER_A
    response = client.post("/api/v1/evaluation-task-shares", json={"recipient": "dev-user-2", "task_ids": [first, second], "include_model": False})
    assert response.status_code == 201 and set(response.json()["task_ids"]) == {first, second}
    client.headers["Authorization"] = USER_B
    reports = client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json()
    assert {item["id"] for item in reports} == {first, second}
    assert all(item["progress"]["completed"] and item["source"] == "DEMO" for item in reports)


def test_same_content_uploaded_by_two_users_has_two_logical_owner_records(client, model_bytes):
    client.headers["Authorization"] = USER_A
    asset_id, _, _ = _upload_and_profile(client, model_bytes)
    client.headers["Authorization"] = USER_B
    duplicate = client.post("/api/v1/model-assets", files={"file": ("same.onnx", model_bytes)})
    assert duplicate.status_code == 201 and duplicate.json()["asset"]["id"] == asset_id
    listed = client.get("/api/v1/model-assets").json()
    assert len(listed) == 1 and listed[0]["id"] == asset_id and listed[0]["access"] == "OWNER"


def test_owner_can_physically_delete_completed_report_and_revoke_its_shares(client, model_bytes):
    client.headers["Authorization"] = USER_A
    asset_id, _, profile_id = _upload_and_profile(client, model_bytes)
    task_id = client.post("/api/v1/evaluation-tasks", json={
        "model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]
    }).json()["id"]
    session = client.app.state.session_factory()
    try:
        session.add(EvaluationTaskShare(task_id=task_id, subject="dev-user-2", shared_by="dev-user-1", include_model=True))
        session.commit()
    finally:
        session.close()

    assert client.delete(f"/api/v1/evaluation-tasks/{task_id}").status_code == 204
    assert client.get(f"/api/v1/evaluation-tasks/{task_id}").status_code == 404
    assert client.get(f"/api/v1/reports/{task_id}").status_code == 404
    assert client.get(f"/api/v1/model-assets/{asset_id}/evaluation-tasks").json() == []

    client.headers["Authorization"] = USER_B
    assert client.get(f"/api/v1/model-assets/{asset_id}").status_code == 404


def test_shared_recipient_cannot_delete_and_parent_report_waits_for_dependent_report(client, model_bytes):
    client.headers["Authorization"] = USER_A
    _, _, profile_id = _upload_and_profile(client, model_bytes)
    parent = client.post("/api/v1/evaluation-tasks", json={
        "model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]
    }).json()["id"]
    child = client.post("/api/v1/evaluation-tasks", json={
        "model_profile_id": profile_id, "mode": "DEMO", "platforms": ["Intel"]
    }).json()["id"]
    session = client.app.state.session_factory()
    try:
        session.get(EvaluationTask, child).source_task_id = parent
        session.add(EvaluationTaskShare(task_id=parent, subject="dev-user-2", shared_by="dev-user-1", include_model=False))
        session.commit()
    finally:
        session.close()
    client.headers["Authorization"] = USER_B
    assert client.delete(f"/api/v1/evaluation-tasks/{parent}").status_code == 404
    client.headers["Authorization"] = USER_A
    assert client.delete(f"/api/v1/evaluation-tasks/{parent}").status_code == 409
    assert client.delete(f"/api/v1/evaluation-tasks/{child}").status_code == 204
    assert client.delete(f"/api/v1/evaluation-tasks/{parent}").status_code == 204


def test_x5_parent_delete_cascades_completed_board_stage(client, model_bytes):
    client.headers["Authorization"] = USER_A
    _, _, profile_id = _upload_and_profile(client, model_bytes)
    parent = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]}).json()["id"]
    child = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5"]}).json()["id"]
    session = client.app.state.session_factory()
    try:
        source, board = session.get(EvaluationTask, parent), session.get(EvaluationTask, child)
        source.mode, source.task_kind = "REAL", "X5_COMPILE"
        board.mode, board.task_kind, board.source_task_id = "REAL", "REAL_BOARD_SMOKE", parent
        session.commit()
    finally:
        session.close()
    assert client.delete(f"/api/v1/evaluation-tasks/{parent}").status_code == 204
    assert client.get(f"/api/v1/evaluation-tasks/{parent}").status_code == 404
    assert client.get(f"/api/v1/evaluation-tasks/{child}").status_code == 404
