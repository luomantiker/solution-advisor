"""Control-plane registration tests; no Docker, board or external network."""

from datetime import timedelta

from solution_advisor.common_analyzer.domain import WorkerInstance
from solution_advisor.common_analyzer.service import now

ADMIN = {"Authorization": "Bearer development-admin-token"}
WORKER = {"Authorization": "Bearer development-worker-token"}


def registration_body(**overrides):
    payload = {
        "instance_id": "x5-a",
        "worker_type": "x5",
        "image_ref": "openexplorer/ai_toolchain_ubuntu_20_x5_gpu:v1.2.8-py310",
        "image_id": "sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593",
        "toolchain_version": "1.24.3",
        "platform_package_version": "1.0",
        "capabilities": ["static_check", "compile"],
        "max_concurrency": 1,
    }
    payload.update(overrides)
    return payload


def test_worker_register_heartbeat_and_admin_views(client, app):
    body = registration_body()
    assert client.post("/api/internal/workers/register", json=body).status_code == 403
    assert client.post("/api/internal/workers/register", json=body, headers={"Authorization": "Bearer bad"}).status_code == 403

    registered = client.post("/api/internal/workers/register", json=body, headers=WORKER)
    assert registered.status_code == 200
    assert registered.json() == {
        "instance_id": "x5-a", "health": "READY",
        "capabilities": ["static_check", "compile"], "max_concurrency": 1,
    }
    heartbeat = client.post("/api/internal/workers/x5-a/heartbeat", headers=WORKER)
    assert heartbeat.status_code == 200 and heartbeat.json()["health"] == "READY"

    assert client.get("/api/admin/worker-instances", headers={"Authorization": ""}).status_code == 401
    detail = client.get("/api/admin/worker-instances/x5-a/capacity", headers=ADMIN)
    assert detail.status_code == 200
    assert detail.json()["free_slots"] == 1
    assert detail.json()["image_id"].startswith("sha256:")
    assert client.get("/api/admin/worker-instances/x5-a/leases", headers=ADMIN).json() == []

    # A stale persistent row must not be presented as READY merely because its
    # last stored health was READY.
    session = app.state.session_factory()
    try:
        session.get(WorkerInstance, "x5-a").last_heartbeat_at = now() - timedelta(seconds=61)
        session.commit()
    finally:
        session.close()
    stale = client.get("/api/admin/worker-instances/x5-a/health", headers=ADMIN)
    assert stale.json()["health"] == "OFFLINE"
    assert stale.json()["health_reason"] == "心跳已超时"


def test_worker_registration_rejects_unapproved_capability(client):
    response = client.post(
        "/api/internal/workers/register",
        json=registration_body(capabilities=["static_check", "compile", "shell"]),
        headers=WORKER,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_worker_capabilities"
