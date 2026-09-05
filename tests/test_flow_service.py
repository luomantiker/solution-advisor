"""Admission and aggregation coverage for the user-visible EvaluationFlow."""
import pytest
from solution_advisor.evaluations.flow_service import EvaluationFlowService, FlowError
from solution_advisor.evaluations.domain import EvaluationTask
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile
from solution_advisor.platforms.domain import HostAgent, PlatformBinding, PlatformCatalog, PlatformWorker


def _ready_platform(session, platform_id, version, runner_version, agent_id):
    catalog = PlatformCatalog(
        platform_id=platform_id, version=version, display_name=f"{platform_id}/{version}", state="AVAILABLE",
        image_lock={"digest": f"sha256:{platform_id.lower()}"},
        runner={"version": runner_version, "content_sha256": "c" * 64},
    )
    agent = HostAgent(id=agent_id, host_state="ONLINE")
    session.add_all([catalog, agent]); session.flush()
    binding = PlatformBinding(
        agent_id=agent.id, catalog_id=catalog.id, platform_id=platform_id, state="HEALTHY",
        capabilities=["static_check", "compile", "board_smoke"], max_concurrency=3,
        image_lock_version=catalog.image_lock["digest"], runner_version=runner_version,
    )
    session.add(binding); session.flush()
    worker = PlatformWorker(
        binding_id=binding.id, agent_id=agent.id, platform_id=platform_id, state="READY",
        max_concurrency=3, runner={"version": runner_version},
    )
    session.add(worker); session.flush()
    return catalog, binding, worker


def test_flow_admission_freezes_two_platforms_and_aggregates_partial_success(client, app):
    session = app.state.session_factory()
    try:
        asset = ModelAsset(sha256="f" * 64, original_filename="flow.onnx", size_bytes=16, owner_subject="dev-user")
        session.add(asset); session.flush()
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test", analysis={})
        session.add(profile); session.flush()
        x5, _, _ = _ready_platform(session, "X5", "1.2.8", "1.0.0", "flow-x5-agent")
        s100, _, _ = _ready_platform(session, "S100", "3.7.0-r1", "s100-runner-1.0.0", "flow-s100-agent")
        session.commit()

        flow = EvaluationFlowService(session).create(profile.id, "dev-user", [x5.id, s100.id])
        payload = EvaluationFlowService(session).payload(flow)
        assert payload["status"] == "QUEUED"
        assert {(row["platform"], row["kind"]) for row in payload["stages"]} == {
            ("X5", "X5_COMPILE"), ("S100", "S100_COMPILE"),
        }
        assert flow.platform_snapshots[x5.id]["catalog_version"] == "1.2.8"
        assert flow.platform_snapshots[s100.id]["artifact_format"] == "s100_hbm"
        assert flow.platform_snapshots[s100.id]["parser"] == "s100-hrt-profile-1.0"

        tasks = list(session.query(EvaluationTask).filter_by(flow_id=flow.id))
        next(task for task in tasks if task.platforms == ["X5"]).status = "SUCCEEDED"
        next(task for task in tasks if task.platforms == ["S100"]).status = "FAILED"
        assert EvaluationFlowService(session).payload(flow)["status"] == "PARTIALLY_SUCCEEDED"
    finally:
        session.close()


def test_flow_rejects_duplicate_selection_and_unschedulable_platform(client, app):
    session = app.state.session_factory()
    try:
        asset = ModelAsset(sha256="e" * 64, original_filename="flow.onnx", size_bytes=16, owner_subject="dev-user")
        session.add(asset); session.flush()
        profile = ModelProfile(model_asset_id=asset.id, onnx_sha256=asset.sha256, analyzer_version="test", analysis={})
        session.add(profile); session.flush()
        catalog, binding, _ = _ready_platform(session, "S100", "3.7.0-r1", "s100-runner-1.0.0", "flow-s100-agent")
        session.commit()

        with pytest.raises(FlowError, match="catalog_selection_invalid"):
            EvaluationFlowService(session).create(profile.id, "dev-user", [catalog.id, catalog.id])
        binding.state = "OFFLINE"
        with pytest.raises(FlowError) as error:
            EvaluationFlowService(session).create(profile.id, "dev-user", [catalog.id])
        assert error.value.code == "platforms_not_schedulable"
        assert "S100/3.7.0-r1" in error.value.reasons
    finally:
        session.close()
