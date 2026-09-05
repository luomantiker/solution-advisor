from solution_advisor.common_analyzer.service import AnalysisService
from solution_advisor.api.app import create_app
from solution_advisor.common_analyzer.queue import RedisAnalysisQueue
import fakeredis
from fastapi.testclient import TestClient
from solution_advisor.artifacts.domain import Artifact, Evidence
from sqlalchemy import select
from zipfile import ZipFile
from datetime import timedelta
from solution_advisor.platforms.domain import CandidateHistory, HostAgent, HostImage, PlatformAudit, PlatformBinding, PlatformCandidate, PlatformCatalog, PlatformType, PlatformWorker
from solution_advisor.platforms.service import utcnow

ADMIN = {"Authorization": "Bearer development-admin-token"}
ADMIN_2 = {"Authorization": "Bearer development-admin-2-token"}
SUPER = {"Authorization": "Bearer development-super-admin-token"}
WORKER = {"Authorization": "Bearer development-worker-token"}


def registration(max_concurrency: int = 1):
    return {"instance_id":"x5-a", "worker_type":"host-agent", "image_ref":"x5:test", "image_id":"sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593",
            "toolchain_version":"1.24.3", "platform_package_version":"1.0.0", "capabilities":["static_check", "compile"],
            "max_concurrency":max_concurrency, "candidates":[{"image_ref":"x5:test", "image_id":"sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593", "toolchain_version":"1.24.3"}]}


def profile_id(client, model_bytes):
    upload = client.post("/api/v1/model-assets", headers=ADMIN, files={"file": ("minimal.onnx", model_bytes)}).json()
    session = client.app.state.session_factory()
    try: AnalysisService(session, client.app.state.artifact_storage, client.app.state.analysis_queue).run(upload["analysis_task"]["id"])
    finally: session.close()
    return client.get(f"/api/v1/analysis-tasks/{upload['analysis_task']['id']}", headers=ADMIN).json()["profile_id"]


def x5_catalog(client):
    return next(item for item in client.get("/api/admin/platform-catalogs", headers=ADMIN).json() if item["platform_id"] == "X5")


def bind_x5(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    catalog = x5_catalog(client)
    binding = client.post("/api/admin/platform-bindings", headers=ADMIN, json={"agent_id":"x5-a", "catalog_id":catalog["id"], "capabilities":["static_check","compile"], "max_concurrency":1})
    assert binding.status_code == 201
    return catalog, binding.json()


def test_host_agent_board_preflight_and_board_binding(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    agents = client.get("/api/admin/host-agents", headers=ADMIN)
    assert agents.status_code == 200
    assert agents.json()[0]["id"] == "x5-a" and agents.json()[0]["host_state"] == "ONLINE"
    created = client.post("/api/admin/boards", headers=ADMIN, json={
        "agent_id": "x5-a", "name": "x5-board-01", "board_type": "X5", "connection_ref": "secret-ref:x5-board-01"})
    assert created.status_code == 201 and created.json()["status"] == "UNVERIFIED"
    board = client.post(f"/api/admin/boards/{created.json()['id']}/test", headers=ADMIN)
    assert board.status_code == 200 and board.json()["status"] == "READY"
    catalog = x5_catalog(client)
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    binding = client.post("/api/admin/platform-bindings", headers=ADMIN, json={
        "agent_id": "x5-a", "catalog_id": catalog["id"], "host_image_id": image["id"],
        "board_id": board.json()["id"], "capabilities": ["static_check", "compile", "board_smoke"], "max_concurrency": 1})
    assert binding.status_code == 201 and binding.json()["board_id"] == board.json()["id"]


def test_candidate_cannot_auto_admit_or_supply_platform_id(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    assert client.get("/api/admin/platform-candidates", headers=ADMIN).json() == []
    images = client.get("/api/admin/host-images", headers=ADMIN).json()
    assert images[0]["state"] == "MANAGED"
    created = client.post(f"/api/admin/host-images/{images[0]['id']}/platform-candidates", headers=ADMIN, json={"package_id":"x5-candidate"})
    assert created.status_code == 201 and created.json()["state"] == "PENDING_INTEGRATION"
    assert client.get("/api/admin/platform-bindings", headers=ADMIN).json() == []
    # PlatformCandidate API has no platform_id field: a free image/HostAgent string cannot become a platform.
    response = client.post("/api/admin/platform-catalogs", headers=ADMIN, json={"platform_id":"x5:test", "version":"1", "display_name":"bad", "package_manifest":{}, "image_lock":{}, "runner":{}, "checks":{}, "review":{}})
    assert response.status_code == 400


def test_candidate_package_id_is_generated_for_a_selected_platform_type(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    platform_type = client.get("/api/admin/platform-types", headers=ADMIN).json()[0]
    created = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                          json={"platform_type_id": platform_type["id"], "target_version": "3.7.0"})
    assert created.status_code == 201
    package_id = created.json()["package"]["id"]
    assert package_id.startswith("x5-3-7-0-")
    assert len(package_id) <= 63


def test_catalog_review_reuses_candidate_platform_type_and_target_version(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    platform_type = next(item for item in client.get("/api/admin/platform-types", headers=ADMIN).json()
                         if item["name"] == "X5")
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"platform_type_id": platform_type["id"], "target_version": "3.7.0"}).json()
    candidate = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN).json()
    tested = client.post(f"/api/admin/platform-candidates/{candidate['id']}/integration-runs",
                         headers=ADMIN | {"If-Match": str(candidate["revision"])}).json()
    # A production Runner is outside this API test; seed its persisted, current
    # Evidence result to verify that review cannot alter the Candidate identity.
    session = client.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate["id"])
        item.evidence = {**item.evidence, "real_validation": {"status": "SUCCEEDED",
                         "candidate_revision": item.revision, "evidence_id": "evidence_real_test"}}
        session.commit()
    finally:
        session.close()
    created = client.post(f"/api/admin/platform-candidates/{candidate['id']}/catalogs",
                          headers=ADMIN | {"If-Match": str(tested["revision"])},
                          json={"display_name": "X5 工具链 3.7.0"})
    assert created.status_code == 201
    assert created.json()["platform_id"] == "X5"
    assert created.json()["version"] == "3.7.0"
    view = client.get("/api/admin/platform-workbench", headers=ADMIN).json()
    pending = next(item for item in view["items"] if item["candidate"] and item["candidate"]["id"] == candidate["id"])
    assert pending["state"] == "MANAGED"
    # A caller cannot submit a different platform identifier during review.
    rejected = client.post(f"/api/admin/platform-candidates/{candidate['id']}/catalogs",
                           headers=ADMIN | {"If-Match": str(tested["revision"])},
                           json={"display_name": "ignored", "platform_id": "S100"})
    assert rejected.status_code == 400


def test_catalog_publish_requirements_binding_readiness_and_suspend(client, model_bytes):
    profile = profile_id(client, model_bytes)
    # X5 is reviewed in migration but unavailable without the administrator-created Binding + Worker.
    catalog = x5_catalog(client)
    assert catalog["state"] == "AVAILABLE" and catalog["schedulable"] is False
    assert client.post("/api/admin/x5-real-tasks", headers=ADMIN, json={"model_profile_id":profile}).status_code == 422
    catalog, binding = bind_x5(client)
    assert x5_catalog(client)["schedulable"] is True
    created = client.post("/api/admin/x5-real-tasks", headers=ADMIN, json={"model_profile_id":profile})
    assert created.status_code == 201
    detail = client.get(f"/api/admin/x5-real-tasks/{created.json()['id']}", headers=ADMIN).json()
    assert detail["platform_governance"]["catalog_id"] == catalog["id"]
    assert detail["platform_governance"]["binding_id"] == binding["id"]
    assert detail["platform_governance"]["profile_parser_version"] == "x5-hrt-profile-1.0"
    assert client.post(f"/api/admin/platform-catalogs/{catalog['id']}/suspend", headers=ADMIN, json={"state":"SUSPENDED", "reason":"验收暂停"}).status_code == 200
    assert client.post("/api/admin/x5-real-tasks", headers=ADMIN, json={"model_profile_id":profile}).status_code == 422
    # Suspending only blocks new work; the already-created task and its snapshot stay readable.
    assert client.get(f"/api/admin/x5-real-tasks/{created.json()['id']}", headers=ADMIN).status_code == 200


def test_pending_catalog_needs_reviewed_material_before_publish(client):
    body = {"platform_id":"J6M", "version":"1.0.0", "display_name":"J6M", "package_manifest":{}, "image_lock":{}, "runner":{}, "checks":{}, "review":{}}
    created = client.post("/api/admin/platform-catalogs", headers=ADMIN, json=body)
    assert created.status_code == 201 and created.json()["state"] == "PENDING_INTEGRATION"
    assert client.post(f"/api/admin/platform-catalogs/{created.json()['id']}/publish", headers=ADMIN).status_code == 422


def test_candidate_package_is_persistent_and_only_fixed_runner_can_prepare_review(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "x5-review", "note": "受控接入"})
    assert candidate.status_code == 201
    candidate = candidate.json()
    assert candidate["package"]["artifact_id"]
    assert candidate["package"]["sha256"]
    assert "path" not in candidate["package"]
    session = client.app.state.session_factory()
    try:
        artifact = session.scalar(select(Artifact).where(Artifact.id == candidate["package"]["artifact_id"]))
        assert artifact and artifact.content_type == "application/zip"
        with ZipFile(client.app.state.artifact_storage.open(artifact.uri)) as package:
            assert set(package.namelist()) == {"README.md", "image.lock.json", "manifest.json", "runner.json", "tests/offline-contract.json"}
            assert "docker run" not in package.read("README.md").decode().lower()
    finally:
        session.close()

    claimed = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN)
    assert claimed.status_code == 200
    candidate = claimed.json()

    # An offline contract check is necessary but never sufficient for review.
    review = {"display_name": "X5 Review", "approved": False}
    claim_headers = ADMIN | {"If-Match": str(candidate["revision"])}
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/catalogs", headers=claim_headers, json=review).status_code == 422
    tested = client.post(f"/api/admin/platform-candidates/{candidate['id']}/integration-runs", headers=claim_headers)
    assert tested.status_code == 200
    tested = tested.json()
    assert tested["integration_test"]["passed"] is True
    assert tested["integration_test"]["runner_id"] == "candidate-integration-runner-v1"
    assert tested["review_ready"] is False
    blocked = client.post(f"/api/admin/platform-candidates/{candidate['id']}/real-validation-runs",
                          headers=ADMIN | {"If-Match": str(tested["revision"])})
    assert blocked.status_code == 200
    assert blocked.json()["real_validation"]["status"] == "BLOCKED"
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/catalogs", headers=ADMIN | {"If-Match": str(tested["revision"])}, json=review).json()["detail"]["code"] == "candidate_real_validation_required"
    session = client.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate["id"])
        item.evidence = {**item.evidence, "real_validation": {"status": "SUCCEEDED",
                         "candidate_revision": item.revision, "evidence_id": "evidence_real_test"}}
        session.commit()
    finally:
        session.close()
    drafted = client.post(f"/api/admin/platform-candidates/{candidate['id']}/catalogs", headers=ADMIN | {"If-Match": str(tested["revision"])}, json=review)
    assert drafted.status_code == 201
    assert drafted.json()["state"] == "PENDING_INTEGRATION"
    # Evidence alone is insufficient: a reviewer must explicitly approve before publication.
    assert client.post(f"/api/admin/platform-catalogs/{drafted.json()['id']}/publish", headers=ADMIN).status_code == 422
    reviewed = client.post(f"/api/admin/platform-catalogs/{drafted.json()['id']}/review", headers=ADMIN,
                           json={"approved": True, "note": "材料齐全"})
    assert reviewed.status_code == 200 and reviewed.json()["review"]["approved"] is True
    assert client.post(f"/api/admin/platform-catalogs/{drafted.json()['id']}/publish", headers=ADMIN).status_code == 200
    published = next(x for x in client.get("/api/admin/platform-catalogs", headers=ADMIN).json()
                     if x["id"] == drafted.json()["id"])
    assert published["runner"]["module"] == "platform_runner"


def test_candidate_workspace_invalidates_old_real_validation_and_records_blocked_preflight(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "workspace-check"}).json()
    candidate = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN).json()
    workspace = client.get(f"/api/admin/platform-candidates/{candidate['id']}/workspace", headers=ADMIN)
    assert workspace.status_code == 200
    assert [x["path"] for x in workspace.json()["package_files"]] == ["manifest.json", "runner.json"]
    updated = client.put(f"/api/admin/platform-candidates/{candidate['id']}/workspace", headers=ADMIN | {"If-Match": str(candidate["revision"])},
                         json={"display_name": "S100 接入", "archive_note": "S100 工具链接入档案",
                               "compile_command_template": "hb_compile --fast-perf --march nash-e --model {model}",
                               "board_command_template": "hrt_model_exec perf --model_file {model} --profile_path {profile_dir}"})
    assert updated.status_code == 200
    run = client.post(f"/api/admin/platform-candidates/{candidate['id']}/real-validation-runs",
                      headers=ADMIN | {"If-Match": str(updated.json()["revision"])})
    assert run.status_code == 422
    assert run.json()["detail"]["code"] == "candidate_current_integration_required"
    checked = client.post(f"/api/admin/platform-candidates/{candidate['id']}/integration-runs",
                          headers=ADMIN | {"If-Match": str(updated.json()["revision"])})
    assert checked.status_code == 200
    assert checked.json()["integration_test"]["current"] is True
    run = client.post(f"/api/admin/platform-candidates/{candidate['id']}/real-validation-runs",
                      headers=ADMIN | {"If-Match": str(checked.json()["revision"])})
    assert run.status_code == 200
    assert run.json()["real_validation"]["status"] == "BLOCKED"
    assert run.json()["real_validation"]["reason_code"] == "real_validation_runner_not_installed"


def test_catalog_version_is_reusable_when_target_host_digest_differs(client):
    catalog, _ = bind_x5(client)
    second = registration() | {"instance_id": "x5-b", "candidates": [registration()["candidates"][0]]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=second).status_code == 200
    reusable = client.post("/api/admin/platform-bindings", headers=ADMIN,
                           json={"agent_id": "x5-b", "catalog_id": catalog["id"], "capabilities": ["compile"], "max_concurrency": 1})
    assert reusable.status_code == 201

    different = registration() | {"instance_id": "x5-c", "candidates": [{"image_ref": "x5:test", "image_id": "sha256:" + "a" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=different).status_code == 200
    reusable_with_warning = client.post("/api/admin/platform-bindings", headers=ADMIN,
                           json={"agent_id": "x5-c", "catalog_id": catalog["id"], "capabilities": ["compile"], "max_concurrency": 1})
    assert reusable_with_warning.status_code == 201
    assert reusable_with_warning.json()["actual_image_digest"] == "sha256:" + "a" * 64
    assert reusable_with_warning.json()["image_match_status"] == "VERSION_MATCH_DIGEST_DIFFERENT"


def test_s100_catalog_release_requires_current_hashed_validation_and_retires_old_binding(client, app):
    """A successor Runner is a new Catalog, never an in-place Catalog edit."""
    # Resolve/persist the administrator principal before creating its claim.
    assert client.get("/api/admin/platform-types", headers=ADMIN).status_code == 200
    session = app.state.session_factory()
    try:
        platform_type = session.scalar(select(PlatformType).where(PlatformType.name == "S100"))
        if platform_type is None:
            platform_type = PlatformType(name="S100", display_name="S100")
            session.add(platform_type); session.flush()
        digest = "sha256:" + "c" * 64
        agent = HostAgent(id="s100-release-host", host_state="ONLINE")
        image = HostImage(agent_id=agent.id, image_ref="s100:v3.7.0", image_id=digest)
        old_catalog = PlatformCatalog(platform_id="S100", platform_type_id=platform_type.id, version="3.7.0",
            display_name="S100 3.7.0", state="AVAILABLE", package_manifest={"id":"old"}, image_lock={"digest":digest},
            runner={"module":"platform_runner", "version":"0.1.0"}, checks={"self_check":True,"offline_test":True}, review={"approved":True})
        session.add_all([agent, image, old_catalog]); session.flush()
        old_binding = PlatformBinding(agent_id=agent.id, catalog_id=old_catalog.id, platform_id="S100", state="HEALTHY",
            capabilities=["static_check", "compile", "board_smoke"], max_concurrency=1, image_lock_version=digest,
            actual_image_digest=digest, runner_version="0.1.0")
        session.add(old_binding); session.flush()
        old_worker = PlatformWorker(binding_id=old_binding.id, agent_id=agent.id, platform_id="S100", state="READY", max_concurrency=1,
            runner={"version":"0.1.0"})
        candidate = PlatformCandidate(agent_id=agent.id, image_ref=image.image_ref, image_id=digest,
            platform_type_id=platform_type.id, target_version="3.7.0", catalog_id=old_catalog.id,
            revision=7, claimed_by="dev-admin-1", claimed_by_name="管理员 U1", lease_expires_at=utcnow() + timedelta(minutes=5),
            evidence={"package":{"id":"s100-release", "version":"1", "artifact_id":"artifact_release", "sha256":"a" * 64},
                      "integration_test":{"passed":True,"current":True,"candidate_revision":7,"evidence_id":"evidence_offline"},
                      "real_validation":{"status":"SUCCEEDED", "candidate_revision":7, "runner_release":"s100-runner-1.0.0",
                                         "runner_content_sha256":"332a1ed0d71f3a7d22914034d6d453e3ea259fbef3ebd5217a78541fff1a0e2d",
                                         "evidence_ids":["evidence_real"]}})
        session.add_all([old_worker, candidate]); session.commit()
        candidate_id, old_binding_id = candidate.id, old_binding.id
    finally:
        session.close()
    body = {"release_version":"3.7.0-r1", "display_name":"S100 3.7.0（Runner 1.0）", "review_note":"当前修订真实验证通过"}
    created = client.post(f"/api/admin/platform-candidates/{candidate_id}/catalog-releases",
                          headers=ADMIN | {"If-Match":"7"}, json=body)
    assert created.status_code == 201
    release = created.json()
    assert release["state"] == "AVAILABLE"
    assert release["runner"]["version"] == "s100-runner-1.0.0"
    assert release["runner"]["content_sha256"] == "332a1ed0d71f3a7d22914034d6d453e3ea259fbef3ebd5217a78541fff1a0e2d"
    # The old release is retained for audit but cannot accept new work.
    drained = client.post(f"/api/admin/platform-bindings/{old_binding_id}/state", headers=ADMIN,
                          json={"state":"SUSPENDED", "reason":"已由 Runner 1.0 Release 接替"})
    assert drained.status_code == 200
    session = app.state.session_factory()
    try:
        assert session.get(PlatformBinding, old_binding_id).state == "SUSPENDED"
        assert session.scalar(select(PlatformWorker).where(PlatformWorker.binding_id == old_binding_id)).state == "DRAINING"
        assert session.scalar(select(PlatformAudit).where(PlatformAudit.catalog_id == release["id"],
                                                           PlatformAudit.action == "CATALOG_RELEASE_PUBLISHED"))
    finally:
        session.close()


def test_s100_catalog_release_rejects_legacy_or_stale_validation(client, app):
    assert client.get("/api/admin/platform-types", headers=ADMIN).status_code == 200
    session = app.state.session_factory()
    try:
        platform_type = session.scalar(select(PlatformType).where(PlatformType.name == "S100"))
        if platform_type is None:
            platform_type = PlatformType(name="S100", display_name="S100")
            session.add(platform_type); session.flush()
        digest = "sha256:" + "d" * 64
        candidate = PlatformCandidate(agent_id="s100-stale-host", image_ref="s100:stale", image_id=digest,
            platform_type_id=platform_type.id, target_version="3.7.0", revision=3,
            claimed_by="dev-admin-1", claimed_by_name="管理员 U1", lease_expires_at=utcnow() + timedelta(minutes=5),
            evidence={"package":{"id":"s100-stale", "artifact_id":"artifact_stale", "sha256":"b" * 64},
                      "integration_test":{"passed":True,"candidate_revision":3},
                      "real_validation":{"status":"SUCCEEDED", "candidate_revision":2, "runner_release":"0.1.0"}})
        session.add(candidate); session.commit(); candidate_id = candidate.id
    finally:
        session.close()
    rejected = client.post(f"/api/admin/platform-candidates/{candidate_id}/catalog-releases", headers=ADMIN | {"If-Match":"3"},
                           json={"release_version":"3.7.0-stale", "display_name":"stale", "review_note":"不得使用旧验证"})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "current_runner_verified_validation_required"


def test_candidate_can_copy_reviewed_catalog_rules_then_edit_them(client):
    catalog, _ = bind_x5(client)
    session = client.app.state.session_factory()
    try:
        item = session.get(PlatformCatalog, catalog["id"])
        item.runner = {**item.runner, "integration_rules": {
            "compile_command_template": "hb_compile --fast-perf --march nash-e --model {model}",
            "board_command_template": "hrt_model_exec perf --model_file {model} --profile_path {profile_dir}"}}
        session.commit()
    finally:
        session.close()
    second = registration() | {"instance_id": "x5-b", "candidates": [{"image_ref": "x5:v2", "image_id": "sha256:" + "b" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=second).status_code == 200
    image = next(item for item in client.get("/api/admin/host-images", headers=ADMIN).json() if item["agent_id"] == "x5-b")
    created = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                          json={"platform_type_id": catalog["platform_type_id"], "target_version": "1.1.0",
                                "source_catalog_id": catalog["id"]})
    assert created.status_code == 201
    payload = created.json()
    payload = client.post(f"/api/admin/platform-candidates/{payload['id']}/claim", headers=ADMIN).json()
    assert payload["workspace"]["compile_command_template"].startswith("hb_compile")
    assert payload["workspace"]["board_command_template"].startswith("hrt_model_exec")
    assert payload["rule_copy"]["source_catalog_id"] == catalog["id"]
    updated = client.put(f"/api/admin/platform-candidates/{payload['id']}/workspace", headers=ADMIN | {"If-Match": str(payload["revision"])},
                         json={**payload["workspace"], "compile_command_template": "hb_compile --march nash-e --model {model}"})
    assert updated.status_code == 200
    assert updated.json()["workspace"]["compile_command_template"] == "hb_compile --march nash-e --model {model}"


def test_candidate_command_templates_reject_shell_docker_and_secret(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "template-safety"}).json()
    candidate = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN).json()
    response = client.put(f"/api/admin/platform-candidates/{candidate['id']}/workspace", headers=ADMIN | {"If-Match": str(candidate["revision"])},
                          json={"compile_command_template": "docker run --model {model}",
                                "board_command_template": "runtime --model {model}"})
    assert response.status_code == 400


def test_quick_validation_runs_offline_then_records_real_runner_blocker(client):
    assert client.post("/api/internal/workers/register", headers=WORKER, json=registration()).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "quick-validation"}).json()
    candidate = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN).json()
    result = client.post(f"/api/admin/platform-candidates/{candidate['id']}/quick-validation",
                         headers=ADMIN | {"If-Match": str(candidate["revision"])})
    assert result.status_code == 200
    assert result.json()["integration_test"]["passed"] is True
    assert result.json()["real_validation"]["status"] == "BLOCKED"
    assert result.json()["quick_validation"]["status"] == "BLOCKED"


def test_duplicate_binding_is_a_business_conflict_not_a_server_error(client):
    catalog, _ = bind_x5(client)
    duplicate = client.post("/api/admin/platform-bindings", headers=ADMIN,
                            json={"agent_id": "x5-a", "catalog_id": catalog["id"],
                                  "capabilities": ["compile"], "max_concurrency": 1})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "binding_already_exists"


def test_binding_capacity_cannot_exceed_agent_and_can_be_raised_with_registered_capacity(client):
    catalog, binding = bind_x5(client)
    rejected = client.post(f"/api/admin/platform-bindings/{binding['id']}/capacity", headers=ADMIN,
                           json={"max_concurrency": 3})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "binding_capacity_exceeds_agent_capacity"

    # The HostAgent must declare its new upper bound first; a Binding only
    # grants a subset of that independently registered capacity.
    assert client.post("/api/internal/workers/register", headers=WORKER,
                       json=registration(max_concurrency=3)).status_code == 200
    updated = client.post(f"/api/admin/platform-bindings/{binding['id']}/capacity", headers=ADMIN,
                          json={"max_concurrency": 3})
    assert updated.status_code == 200
    assert updated.json()["max_concurrency"] == 3
    worker = next(item for item in client.get("/api/admin/platform-workers", headers=ADMIN).json()
                  if item["binding_id"] == binding["id"])
    assert worker["max_concurrency"] == 3 and worker["free_slots"] == 3


def test_host_image_list_excludes_governance_images_and_unlinked_candidate_is_archivable(client):
    payload = registration() | {"candidates": [
        {"image_ref": "solution-advisor-api:latest", "image_id": "sha256:" + "b" * 64},
        {"image_ref": "postgres:16-alpine", "image_id": "sha256:" + "d" * 64},
        {"image_ref": "minio/minio:RELEASE.2025-04-22T22-12-26Z", "image_id": "sha256:" + "e" * 64},
        {"image_ref": "mcr.microsoft.com/playwright:v1.62.1", "image_id": "sha256:" + "f" * 64},
        {"image_ref": "docker:27-cli", "image_id": "sha256:" + "1" * 64},
        {"image_ref": "registry.internal/team/toolchain:v1", "image_id": "sha256:" + "c" * 64},
    ]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=payload).status_code == 200
    images = client.get("/api/admin/host-images", headers=ADMIN).json()
    assert [image["image_ref"] for image in images] == ["registry.internal/team/toolchain:v1"]
    assert client.post(f"/api/admin/host-images/{images[0]['id']}/visibility", headers=ADMIN,
                       json={"hidden": True}).json()["hidden"] is True
    assert client.get("/api/admin/host-images", headers=ADMIN).json() == []
    hidden = client.get("/api/admin/host-images?include_hidden=true", headers=ADMIN).json()
    assert hidden[0]["hidden"] is True and hidden[0]["hidden_by"] == "dev-admin-1"
    assert client.post(f"/api/admin/host-images/{images[0]['id']}/visibility", headers=ADMIN,
                       json={"hidden": False}).json()["hidden"] is False
    created = client.post(f"/api/admin/host-images/{images[0]['id']}/platform-candidates", headers=ADMIN,
                          json={"package_id": "toolchain-candidate"})
    assert created.status_code == 201 and created.json()["created_by"] == "dev-admin-1"
    claimed = client.post(f"/api/admin/platform-candidates/{created.json()['id']}/claim", headers=ADMIN).json()
    archived = client.post(f"/api/admin/platform-candidates/{created.json()['id']}/archive", headers=ADMIN | {"If-Match": str(claimed["revision"])}, json={})
    assert archived.status_code == 200 and archived.json()["archived_at"] and archived.json()["claimed_by"] is None
    assert client.get("/api/admin/platform-candidates", headers=ADMIN).json() == []


def test_candidate_archive_retains_audit_artifact_evidence_and_can_be_restored(client):
    body = registration() | {"candidates": [{"image_ref": "registry/archive:v1", "image_id": "sha256:" + "7" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=body).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "archive-candidate"}).json()
    candidate = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN).json()
    package_artifact = candidate["package"]["artifact_id"]
    archived = client.post(f"/api/admin/platform-candidates/{candidate['id']}/archive",
                           headers=ADMIN | {"If-Match": str(candidate["revision"])}, json={})
    assert archived.status_code == 200 and archived.json()["claimed_by"] is None
    default_items = client.get("/api/admin/platform-workbench", headers=ADMIN).json()["items"]
    assert [item["state"] for item in default_items] == ["DISCOVERED"]
    assert default_items[0]["candidate"] is None
    visible = client.get("/api/admin/platform-workbench?include_archived=true", headers=ADMIN).json()["items"]
    assert [item["state"] for item in visible] == ["DISCOVERED", "ARCHIVED"]
    session = client.app.state.session_factory()
    try:
        assert session.get(PlatformCandidate, candidate["id"]).archived_at is not None
        assert session.get(Artifact, package_artifact) is not None
        assert session.scalar(select(Evidence).where(Evidence.artifact_id == package_artifact)) is not None
        assert session.scalar(select(CandidateHistory).where(CandidateHistory.candidate_id == candidate["id"], CandidateHistory.action == "CANDIDATE_ARCHIVED"))
        assert session.scalar(select(PlatformAudit).where(PlatformAudit.action == "CANDIDATE_ARCHIVED"))
    finally:
        session.close()
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/restore",
                       headers=ADMIN | {"If-Match": str(archived.json()["revision"])}, json={"reason": "需要继续接入"}).status_code == 403
    restored = client.post(f"/api/admin/platform-candidates/{candidate['id']}/restore",
                           headers=SUPER | {"If-Match": str(archived.json()["revision"])}, json={"reason": "审核恢复"})
    assert restored.status_code == 200 and restored.json()["archived_at"] is None


def test_archived_candidate_allows_new_active_candidate_and_catalog_link_is_rejected(client):
    body = registration() | {"candidates": [{"image_ref": "registry/archive-unique:v1", "image_id": "sha256:" + "6" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=body).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    first = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN, json={"package_id": "archive-one"}).json()
    first = client.post(f"/api/admin/platform-candidates/{first['id']}/claim", headers=ADMIN).json()
    assert client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN, json={"package_id": "duplicate-active"}).status_code == 409
    archived = client.post(f"/api/admin/platform-candidates/{first['id']}/archive", headers=ADMIN | {"If-Match": str(first["revision"])}, json={}).json()
    second = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN, json={"package_id": "archive-two"})
    assert second.status_code == 201
    assert client.post(f"/api/admin/platform-candidates/{first['id']}/restore", headers=SUPER | {"If-Match": str(archived["revision"])}, json={"reason": "会冲突"}).status_code == 409


def test_catalog_linked_candidate_cannot_be_archived(client):
    body = registration() | {"candidates": [{"image_ref": "registry/archive-catalog:v1", "image_id": "sha256:" + "5" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=body).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN, json={"package_id": "archive-catalog"}).json()
    session = client.app.state.session_factory()
    try:
        session.get(PlatformCandidate, candidate["id"]).catalog_id = "catalog_retention_test"; session.commit()
    finally:
        session.close()
    rejected = client.post(f"/api/admin/platform-candidates/{candidate['id']}/archive", headers=ADMIN | {"If-Match": str(candidate["revision"])}, json={})
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "candidate_catalog_linked"


def test_candidate_manual_claim_is_indefinite_and_super_force_release_clears_work(client):
    body = registration() | {"candidates": [{"image_ref": "registry/test-toolchain:v1", "image_id": "sha256:" + "9" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=body).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    candidate = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                            json={"package_id": "manual-candidate"}).json()
    package_evidence_id = candidate["package"]["evidence_id"]
    package_artifact_id = candidate["package"]["artifact_id"]
    assert candidate["claim_state"] == "UNCLAIMED" and candidate["claimed_by"] is None
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/force-assign", headers=SUPER | {"If-Match": str(candidate["revision"])},
                       json={"target_subject": "dev-admin-1", "reason": "未认领项不能被指定"}).status_code == 409
    claimed = client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN)
    assert claimed.status_code == 200 and claimed.json()["claimed_by"] == "dev-admin-1"
    assert claimed.json()["claim_state"] == "CLAIMED"
    assert "lease_expires_at" not in claimed.json() and "lease_remaining_seconds" not in claimed.json()
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/claim", headers=ADMIN_2).status_code == 423
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/integration-runs",
                       headers=ADMIN_2 | {"If-Match": str(claimed.json()["revision"])}).status_code == 423
    # A stale legacy deadline cannot release or clear the human claim.
    session = client.app.state.session_factory()
    try:
        item = session.get(PlatformCandidate, candidate["id"])
        item.lease_expires_at = utcnow() - timedelta(days=1); session.commit()
    finally:
        session.close()
    still_claimed = client.get("/api/admin/platform-workbench", headers=ADMIN).json()["items"][0]["candidate"]
    assert still_claimed["claimed_by"] == "dev-admin-1" and still_claimed["claim_state"] == "CLAIMED"
    assert client.post(f"/api/admin/platform-candidates/{candidate['id']}/renew", headers=ADMIN).status_code == 404
    # Super administrator can clear an abandoned attempt, but cannot inherit it.
    released = client.post(f"/api/admin/platform-candidates/{candidate['id']}/force-release", headers=SUPER | {"If-Match": str(claimed.json()["revision"])}, json={"reason": "管理员停止处理"})
    assert released.status_code == 200 and released.json()["claimed_by"] is None
    assert released.json()["package"] == {} and released.json()["workspace"]["compile_command_template"] == ""
    session = client.app.state.session_factory()
    try:
        assert session.get(Evidence, package_evidence_id) is None
        assert session.get(Artifact, package_artifact_id) is None
        assert session.scalar(select(PlatformAudit).where(PlatformAudit.action == "CANDIDATE_WORK_MATERIALS_CLEARED"))
    finally:
        session.close()
    workbench = client.get("/api/admin/platform-workbench", headers=ADMIN_2).json()
    assert workbench["principal"]["role"] == "ADMIN"
    assert [x["state"] for x in workbench["items"]] == ["INTEGRATING"]
    assert workbench["items"][0]["candidate"]["actions"] == ["claim"]


def test_candidate_release_and_force_assign_clean_material_before_new_owner_starts(client):
    body = registration() | {"candidates": [{"image_ref": "registry/test-manual:v1", "image_id": "sha256:" + "8" * 64}]}
    assert client.post("/api/internal/workers/register", headers=WORKER, json=body).status_code == 200
    image = client.get("/api/admin/host-images", headers=ADMIN).json()[0]
    created = client.post(f"/api/admin/host-images/{image['id']}/platform-candidates", headers=ADMIN,
                          json={"package_id": "manual-release-candidate"}).json()
    claimed = client.post(f"/api/admin/platform-candidates/{created['id']}/claim", headers=ADMIN).json()
    old_artifact = claimed["package"]["artifact_id"]
    released = client.post(f"/api/admin/platform-candidates/{created['id']}/release", headers=ADMIN | {"If-Match": str(claimed["revision"])}, json={"reason": "主动停止"})
    assert released.status_code == 200 and released.json()["package"] == {}
    reclaimed = client.post(f"/api/admin/platform-candidates/{created['id']}/claim", headers=ADMIN_2)
    assert reclaimed.status_code == 200 and reclaimed.json()["claimed_by"] == "dev-admin-2"
    assert reclaimed.json()["package"]["artifact_id"] != old_artifact
    # Seed the persistent U2 account so it is an eligible force-assignment target.
    assert client.get("/api/admin/platform-workbench", headers=ADMIN_2).status_code == 200
    assigned = client.post(f"/api/admin/platform-candidates/{created['id']}/force-assign", headers=SUPER | {"If-Match": str(reclaimed.json()["revision"])},
                           json={"target_subject": "dev-admin-1", "reason": "指定新的接入负责人"})
    assert assigned.status_code == 200 and assigned.json()["claimed_by"] == "dev-admin-1"
    assert assigned.json()["workspace"]["compile_command_template"] == ""
    assert client.post(f"/api/admin/platform-candidates/{created['id']}/force-assign", headers=SUPER | {"If-Match": str(assigned.json()["revision"])},
                       json={"target_subject": "dev-user", "reason": "错误目标"}).status_code == 422
    assert client.post(f"/api/admin/platform-candidates/{created['id']}/force-assign", headers=SUPER | {"If-Match": str(assigned.json()["revision"])},
                       json={"target_subject": "dev-super-admin", "reason": "错误目标"}).status_code == 422
    session = client.app.state.session_factory()
    try:
        actions = {x.action for x in session.scalars(select(CandidateHistory).where(CandidateHistory.candidate_id == created["id"]))}
        assert {"CANDIDATE_RELEASED", "CANDIDATE_FORCE_ASSIGNED_CLEARED", "CANDIDATE_FORCE_ASSIGNED"} <= actions
    finally:
        session.close()


def test_production_identity_is_fail_closed_and_regular_user_cannot_open_workbench(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'production.sqlite3'}", storage_root=tmp_path / "uploads",
                     queue=RedisAnalysisQueue(fakeredis.FakeRedis()))
    with TestClient(app) as production:
        assert production.get("/api/admin/platform-workbench", headers=ADMIN).status_code == 403


def test_regular_user_cannot_open_platform_workbench(client):
    assert client.get("/api/admin/platform-workbench", headers={"Authorization": "Bearer development-user-token"}).status_code == 403


def test_ordinary_user_resources_are_isolated(client, model_bytes):
    user_1 = {"Authorization": "Bearer development-user-token"}
    user_2 = {"Authorization": "Bearer development-user-2-token"}
    uploaded = client.post("/api/v1/model-assets", headers=user_1, files={"file": ("minimal.onnx", model_bytes)})
    assert uploaded.status_code == 201
    asset_id = uploaded.json()["asset"]["id"]
    assert client.get(f"/api/v1/model-assets/{asset_id}", headers=user_2).status_code == 404
    assert client.get("/api/v1/model-assets", headers=user_2).json() == []
    assert client.get("/api/v1/model-assets", headers={"Authorization": ""}).status_code == 401


def test_super_admin_handover_is_singleton_and_audited(client):
    assert client.get("/api/admin/users", headers=SUPER).status_code == 200
    created = client.post("/api/admin/people", headers=SUPER,
                          json={"login_name": "ops-admin", "display_name": "运维管理员", "role": "ADMIN", "initial_password": "initial"})
    assert created.status_code == 201
    assert client.post("/api/v1/auth/local/login", json={"username":"ops-admin", "password":"initial"}).status_code == 200
    assert client.post("/api/v1/auth/local/password/change", headers={"Authorization": ""}, json={"current_password":"initial", "new_password":"changed"}).status_code == 204
    handover = client.post("/api/admin/users/super-admin-handover", headers=SUPER,
                           json={"successor_subject": "local:ops-admin", "reason": "值班交接"})
    assert handover.status_code == 200
    # The former super administrator is demoted immediately, retaining an audit trail.
    assert client.get("/api/admin/users", headers=SUPER).status_code == 403
