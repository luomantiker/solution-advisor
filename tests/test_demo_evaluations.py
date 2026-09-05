from fastapi.testclient import TestClient
from solution_advisor.common_analyzer.service import AnalysisService
from pypdf import PdfReader
from io import BytesIO


def make_profile(client: TestClient, model_bytes: bytes) -> str:
    response = client.post("/api/v1/model-assets", files={"file": ("minimal.onnx", model_bytes)})
    session = client.app.state.session_factory()
    try:
        task_id = response.json()["analysis_task"]["id"]
        AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(task_id)
    finally:
        session.close()
    return client.get(f"/api/v1/analysis-tasks/{task_id}").json()["profile_id"]


def test_portal_and_demo_report_cycle(client: TestClient, model_bytes: bytes):
    profile_id = make_profile(client, model_bytes)
    assets = client.get("/api/v1/model-assets")
    assert assets.status_code == 200
    asset_id = assets.json()[0]["id"]
    create = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["X5", "Intel"]})
    assert create.status_code == 201
    task = create.json()
    assert task["mode"] == "DEMO"
    details = client.get(f"/api/v1/evaluation-tasks/{task['id']}")
    assert details.json()["status"] == "SUCCEEDED"
    assert details.json()["task_kind"] == "DEMO"
    assert [item["source"] for item in details.json()["results"]] == ["DEMO", "DEMO"]
    assert details.json()["snapshot_id"].startswith("snapshot_")
    report = client.get(f"/api/v1/reports/{task['id']}")
    assert report.status_code == 200
    assert report.json()["mock_notice"] == "Mock / 不可用于交付结论"
    assert len(report.json()["sections"]["platform_results"]) == 2
    pdf = client.get(f"/api/v1/reports/{task['id']}/download")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    extracted = PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert "Mock / 不可用于交付结论" in extracted
    assert "多平台评估结论摘要" in extracted
    assert "ONNX 模型检测概要" in extracted
    assert "各平台适配与板端测试结果" in extracted
    assert "后续优化建议" in extracted
    assert "版本与证据附录" in extracted
    assert "推荐部署" not in extracted
    assert "已实测" not in extracted


def test_demo_task_validation_and_missing_resources(client: TestClient, model_bytes: bytes):
    profile_id = make_profile(client, model_bytes)
    real = client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "REAL", "platforms": ["X5"]})
    assert real.status_code == 422
    assert real.json()["detail"]["code"] == "real_mode_not_enabled"
    assert client.post("/api/v1/evaluation-tasks", json={"model_profile_id": profile_id, "mode": "DEMO", "platforms": ["Unknown"]}).status_code == 422
    assert client.post("/api/v1/evaluation-tasks", json={"model_profile_id": "profile_missing", "mode": "DEMO", "platforms": ["X5"]}).status_code == 404
    assert client.get("/api/v1/evaluation-tasks/task_missing").status_code == 404
    assert client.get("/api/v1/reports/task_missing").status_code == 404
