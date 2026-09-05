"""User-visible regression for the latest published X5 + S100 flow report.

This is a controlled contract test, not board evidence: real board execution is
covered separately by HostAgent acceptance.  Its purpose is to make sure the
portal and PDF preserve each platform's frozen release and measured facts.
"""
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import select

from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationResult, EvaluationTask, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile, ResourceAccessAudit
from solution_advisor.artifacts.domain import Artifact, Evidence
from solution_advisor.reports.flow_delivery import _build_snapshot, _flow_status, _risk_flags, flow_report_pdf


def _pdf_has_embedded_font(payload: bytes) -> bool:
    """Customer PDF must carry an embeddable CJK font, not rely on host fonts."""
    reader = PdfReader(BytesIO(payload))
    for page in reader.pages:
        resources = page.get("/Resources", {})
        fonts = resources.get("/Font", {})
        for font in fonts.values():
            descriptor = font.get_object().get("/FontDescriptor")
            if descriptor and any(key in descriptor.get_object() for key in ("/FontFile", "/FontFile2", "/FontFile3")):
                return True
    return False


def _stage(session, profile, flow, platform, kind, governance, result, source_task_id=None):
    snapshot = TaskSnapshot(
        model_asset_id=profile.model_asset_id, model_profile_id=profile.id,
        evaluation_template_version="controlled-flow-test-1.0",
        report_template_version="flow-real-1.0", platform_governance=governance,
        platform_package_versions={platform: governance},
    )
    session.add(snapshot); session.flush()
    task = EvaluationTask(
        model_profile_id=profile.id, mode="REAL", platforms=[platform], flow_id=flow.id,
        snapshot_id=snapshot.id, task_kind=kind, source_task_id=source_task_id,
        owner_subject="dev-user", status="SUCCEEDED",
    )
    session.add(task); session.flush(); snapshot.task_id = task.id
    session.add(EvaluationResult(
        task_id=task.id, platform=platform, source="REAL", fixture_version="controlled-flow-test-1.0",
        payload={"status": "SUCCEEDED"}, platform_result=result,
    ))
    return task


def test_latest_x5_and_s100_flow_report_and_pdf_preserve_platform_facts(client, app):
    session = app.state.session_factory()
    try:
        asset = ModelAsset(sha256="1" * 64, original_filename="controlled.onnx", size_bytes=16, owner_subject="dev-user")
        session.add(asset); session.flush()
        session.add(ModelAssetAccess(model_asset_id=asset.id, subject="dev-user", access_kind="OWNER", granted_by="dev-user"))
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test",
                               analysis={"summary": {"node_count": 1, "operator_counts": {"Conv": 1}}})
        session.add(profile); session.flush()
        flow = EvaluationFlow(
            model_profile_id=profile.id, owner_subject="dev-user", preset="standard-performance-1.0",
            platform_snapshots={
                "catalog_x5_1_2_8": {"platform_id": "X5", "catalog_version": "1.2.8", "runner_release": "1.0.0"},
                "catalog_s100_3_7_0_r1": {"platform_id": "S100", "catalog_version": "3.7.0-r1", "runner_release": "s100-runner-1.0.0"},
            },
        )
        session.add(flow); session.flush()
        x5_rules = {"platform_id": "X5", "catalog_version": "1.2.8", "artifact_format": "x5_bin",
                    "runner": {"version": "1.0.0"}, "profile_parser_version": "x5-hrt-profile-1.0"}
        s100_rules = {"platform_id": "S100", "catalog_version": "3.7.0-r1", "artifact_format": "s100_hbm",
                      "runner_release": "s100-runner-1.0.0", "parser": "s100-hrt-profile-1.0"}
        x5_compile = _stage(session, profile, flow, "X5", "X5_COMPILE", x5_rules, {"status": "SUCCEEDED"})
        s100_compile = _stage(session, profile, flow, "S100", "S100_COMPILE", s100_rules, {"status": "SUCCEEDED"})
        _stage(session, profile, flow, "X5", "REAL_BOARD_SMOKE", x5_rules, {
            "performance": {"status": "MEASURED", "metrics": {"fps": 392.85, "average_latency_ms": 2.525}},
        }, x5_compile.id)
        _stage(session, profile, flow, "S100", "S100_BOARD_PERF", s100_rules, {
            "performance": {"status": "MEASURED", "fps": 1488.89, "average_latency_ms": 0.643},
        }, s100_compile.id)
        session.commit(); flow_id = flow.id
    finally:
        session.close()

    report_response = client.get(f"/api/v1/evaluation-flows/{flow_id}/report")
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["status"] == "SUCCEEDED"
    assert report["revision"]["version"] == 1
    platforms = {item["platform"]: item for item in report["sections"]["platforms"]}
    assert {key: platforms["X5"][key] for key in ("stage_kind", "artifact_format", "runner_release", "parser", "metrics")} == {
        "stage_kind": "REAL_BOARD_SMOKE", "artifact_format": "x5_bin", "runner_release": "1.0.0",
        "parser": "x5-hrt-profile-1.0", "metrics": {"fps": 392.85, "average_latency_ms": 2.525},
    }
    assert {key: platforms["S100"][key] for key in ("stage_kind", "artifact_format", "runner_release", "parser", "metrics")} == {
        "stage_kind": "S100_BOARD_PERF", "artifact_format": "s100_hbm", "runner_release": "s100-runner-1.0.0",
        "parser": "s100-hrt-profile-1.0", "metrics": {"fps": 1488.89, "average_latency_ms": 0.643},
    }
    # The delivery snapshot distinguishes compilation from the final board
    # phase.  It must never infer a latency from compilation alone.
    assert platforms["X5"]["compile_status"] == "SUCCEEDED"
    assert platforms["S100"]["compile_status"] == "SUCCEEDED"
    assert platforms["X5"]["toolchain_version"] == "未记录"

    pdf_response = client.get(f"/api/v1/evaluation-flows/{flow_id}/report/download")
    assert pdf_response.status_code == 200 and pdf_response.content.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_response.content)).pages)
    # CJK and ASCII traceability facts must both survive a standard text
    # extraction, in addition to visual rendering with embedded fonts.
    assert "多芯片 AI 方案评测报告" in text
    assert "controlled.onnx" in text
    assert "X5" in text and "S100" in text
    assert "工具链版本" in text and "编译结果" in text and "推理时延" in text
    assert "模型格式" in text and "测试执行器" in text and "结果解析器" in text
    assert {item["artifact_format"] for item in report["sections"]["platforms"]} == {"x5_bin", "s100_hbm"}
    assert _pdf_has_embedded_font(pdf_response.content)
    assert len(PdfReader(BytesIO(pdf_response.content)).pages) >= 2
    revisions = client.get(f"/api/v1/evaluation-flows/{flow_id}/report/revisions")
    assert revisions.status_code == 200 and len(revisions.json()) == 1
    assert revisions.json()[0]["version"] == 1 and revisions.json()[0]["pdf_ready"] is True
    created = client.post(f"/api/v1/evaluation-flows/{flow_id}/report/revisions")
    assert created.status_code == 201 and created.json()["version"] == 2
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}/report?version=1").json()["revision"]["version"] == 1
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}/report/download?version=2").headers["content-disposition"].endswith("-report-v2.pdf\"")

    # A report version is independently removable by the owner or an
    # administrator. Its dedicated PDF is removed, while the Flow and V1
    # remain available and the destructive operation remains audited.
    forbidden = {"Authorization": "Bearer development-user-2-token"}
    assert client.delete(f"/api/v1/evaluation-flows/{flow_id}/report/revisions/2", headers=forbidden).status_code == 404
    assert client.delete(f"/api/v1/evaluation-flows/{flow_id}/report/revisions/2").status_code == 204
    assert [row["version"] for row in client.get(f"/api/v1/evaluation-flows/{flow_id}/report/revisions").json()] == [1]
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}/report?version=1").status_code == 200
    session = app.state.session_factory()
    try:
        audit = session.scalar(select(ResourceAccessAudit).where(
            ResourceAccessAudit.resource_type == "REPORT_REVISION",
            ResourceAccessAudit.action == "REPORT_REVISION_DELETED",
        ))
        assert audit and audit.actor_subject == "dev-user" and audit.recipient_subject == "dev-user"
    finally:
        session.close()


def test_user_workbench_and_flow_evidence_are_owner_scoped(client, app):
    session = app.state.session_factory()
    try:
        asset = ModelAsset(sha256="2" * 64, original_filename="owner-only.onnx", size_bytes=16, owner_subject="dev-user")
        session.add(asset); session.flush()
        session.add(ModelAssetAccess(model_asset_id=asset.id, subject="dev-user", access_kind="OWNER", granted_by="dev-user"))
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test",
                               analysis={"summary": {"node_count": 1, "operator_counts": {}}})
        session.add(profile); session.flush()
        flow = EvaluationFlow(model_profile_id=profile.id, owner_subject="dev-user", preset="standard-performance-1.0")
        session.add(flow); session.flush()
        task = _stage(session, profile, flow, "S100", "S100_BOARD_PERF",
                      {"artifact_format": "s100_hbm", "parser": "s100-hrt-profile-1.0"}, {"status": "SUCCEEDED"})
        artifact = Artifact(uri="tests/owner-evidence.log", sha256="3" * 64, size_bytes=9,
                            content_type="text/plain", storage_backend="test")
        session.add(artifact); session.flush()
        session.add(Evidence(evidence_type="s100_board_profile_log", phase="BOARD_TEST", task_id=task.id,
                             platform="S100", artifact_id=artifact.id))
        session.commit(); flow_id = flow.id
    finally:
        session.close()

    workbench = client.get("/api/v1/evaluation-workbench")
    assert workbench.status_code == 200
    assert workbench.json()["metrics"]["models"] == 1
    assert [item["id"] for item in workbench.json()["recent_flows"]] == [flow_id]
    evidence = client.get(f"/api/v1/evaluation-flows/{flow_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json()[0]["platform"] == "S100"
    forbidden = {"Authorization": "Bearer development-user-2-token"}
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}", headers=forbidden).status_code == 404
    assert client.get(f"/api/v1/evaluation-flows/{flow_id}/evidence", headers=forbidden).status_code == 404


def test_delivery_report_keeps_unknown_history_unknown_and_covers_terminal_summaries(client, app):
    """A missing historic Profile must be disclosed, never re-analysed or guessed."""
    session = app.state.session_factory()
    try:
        flow = EvaluationFlow(model_profile_id="missing-historic-profile", owner_subject="dev-user",
                              preset="standard-performance-1.0")
        session.add(flow); session.flush()
        snapshot = _build_snapshot(session, flow)
        assert snapshot["model"]["source"] == "HISTORICAL_PROFILE_SNAPSHOT_UNAVAILABLE"
        assert snapshot["status"] == "QUEUED"
        assert _flow_status([{"status": "SUCCEEDED"}, {"status": "FAILED"}]) == "PARTIALLY_SUCCEEDED"
        assert _flow_status([{"status": "CANCELLED"}]) == "FAILED"
        assert _flow_status([{"status": "RUNNING"}]) == "RUNNING"
        assert _risk_flags({"structure_flags": {"has_dynamic_shape": True}})[0]["label"] == "动态 Shape"
        snapshot["revision"] = {"version": 1, "template_version": "test", "created_at": "now"}
        pdf = flow_report_pdf(snapshot)
        assert pdf.startswith(b"%PDF") and len(PdfReader(BytesIO(pdf)).pages) >= 2
    finally:
        session.close()


def test_delivery_pdf_keeps_profile_io_failure_reason_and_empty_performance_explicit():
    """The four delivery chapters must remain useful for a failed real Flow too."""
    report = {
        "flow_id": "flow-customer-failed-001",
        "revision": {"version": 8, "template_version": "customer-delivery-2.0.0", "created_at": "2026-09-02 08:30 UTC"},
        "model": {
            "source": "FLOW_CREATE_PROFILE_SNAPSHOT", "filename": "customer_model.onnx",
            "sha256": "4" * 64, "size_bytes": 1024, "model_profile_id": "profile_customer",
            "analyzer_version": "common-analyzer-2.0", "analysis": {},
        },
        "sections": {
            "executive_summary": {
                "conclusion": "S100 板端阶段失败，不能形成成功结论。",
                "comparability": "未对齐条件不作排名。", "next_step": "处理失败后重新发起 Flow。",
            },
            "onnx_model_profile": {
                "ir_version": 9, "opset_imports": [{"version": 18}], "node_count": 2,
                "operator_type_count": 1, "operator_counts": {"Conv": 2},
                "inputs": [{"name": "images", "shape": [1, 3, 16, 16], "element_type": "float32", "dynamic_dimensions": [False]}],
                "outputs": [{"name": "scores", "shape": [1, 1000], "element_type": "float32", "dynamic_dimensions": []}],
            },
            "onnx_risks": [{"label": "动态 Shape", "meaning": "需在受控样本上验证。"}],
            "platforms": [{
                "platform": "S100", "status": "FAILED", "stage_kind": "S100_BOARD_PERF",
                "artifact_format": "s100_hbm", "runner_release": "s100-runner-1.0.0",
                "parser": "s100-hrt-profile-1.0", "reason_code": "BOARD_RUNTIME_UNAVAILABLE",
                "metrics": {}, "measurement_conditions": {},
            }],
            "evidence": [],
            "boundaries": {"output_consistency": "未执行", "task_accuracy": "未验证", "stability": "未验证", "power": "未验证", "deployment_recommendation": "未验证"},
        },
    }
    payload = flow_report_pdf(report)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(payload)).pages)
    assert "customer_model.onnx" in text
    assert "BOARD_RUNTIME_UNAVAILABLE" in text
    assert "s100_hbm" in text
