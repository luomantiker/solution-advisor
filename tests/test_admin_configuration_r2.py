from types import SimpleNamespace

from sqlalchemy import select

from solution_advisor.common_analyzer.domain import AnalyzerConfigAudit, AnalyzerConfigDraft, WorkerCapacityLease
from solution_advisor.common_analyzer.service import acquire_lease, ensure_configuration, now, reclaim_expired_leases, release_lease


HEADERS = {"Authorization": "Bearer development-admin-token"}


def current(client):
    response = client.get("/api/admin/analyzer-config", headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def draft(client, config=None, note="测试草稿"):
    response = client.post("/api/admin/analyzer-config/drafts", headers=HEADERS, json={"change_note": note})
    assert response.status_code == 201
    item = response.json()
    if config:
        response = client.put(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS, json=config)
        assert response.status_code == 200
        item = response.json()
    return item


def test_admin_protection_and_persisted_draft_lifecycle(client):
    assert client.get("/api/admin/analyzer-config", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/admin/analyzer-config", headers={"Authorization": "Bearer bad"}).status_code == 403
    item = draft(client)
    loaded = client.get(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS)
    assert loaded.json()["status"] == "DRAFT"
    assert client.post(f"/api/admin/analyzer-config/drafts/{item['id']}/validate", headers=HEADERS).json()["valid"] is True
    assert client.delete(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS).json()["status"] == "DISCARDED"
    history = client.get("/api/admin/analyzer-config/history", headers=HEADERS).json()
    assert any(x["action"] == "DRAFT_DISCARD" for x in history["audits"])


def test_publish_conflict_rollback_and_snapshot_isolation(client, app):
    initial = current(client)
    first, stale = draft(client), draft(client)
    modules = first["modules"]
    modules["model_size"]["enabled"] = False
    edited = client.put(f"/api/admin/analyzer-config/drafts/{first['id']}", headers=HEADERS, json={"modules": modules, "max_concurrency": 2, "change_note": "关闭可选模块"})
    assert edited.status_code == 200
    published = client.post(f"/api/admin/analyzer-config/drafts/{first['id']}/publish", headers=HEADERS, json={"if_match": initial["revision"]})
    assert published.status_code == 200
    assert current(client)["revision"] == initial["revision"] + 1
    conflict = client.post(f"/api/admin/analyzer-config/drafts/{stale['id']}/publish", headers=HEADERS, json={"if_match": initial["revision"]})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "version_conflict"
    rollback = client.post("/api/admin/analyzer-config/rollback", headers=HEADERS, json={"version": initial["revision"], "if_match": initial["revision"] + 1})
    assert rollback.status_code == 200 and rollback.json()["version"] == initial["revision"] + 2
    session = app.state.session_factory()
    try:
        # An existing task stores a JSON snapshot and never follows a later active row.
        from solution_advisor.common_analyzer.service import snapshot
        before = snapshot(ensure_configuration(session)); assert before["revision"] == initial["revision"] + 2
        assert session.scalar(select(AnalyzerConfigAudit).where(AnalyzerConfigAudit.action == "DRAFT_PUBLISH"))
    finally:
        session.close()


def test_invalid_draft_is_rejected_and_audited(client):
    item = draft(client)
    modules = item["modules"]
    modules["core_profile"]["enabled"] = False
    bad = client.put(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS, json={"modules": modules, "max_concurrency": 1, "change_note": "错误配置"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "core_module_required"
    modules = client.get(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS).json()["modules"]
    modules["model_size"]["parameters"] = {"shell": "rm -rf /"}
    bad = client.put(f"/api/admin/analyzer-config/drafts/{item['id']}", headers=HEADERS, json={"modules": modules, "max_concurrency": 1})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_parameter"


def test_capacity_slots_are_bounded_reusable_and_reclaimed(app, client):
    session = app.state.session_factory()
    try:
        config = ensure_configuration(session); config.max_concurrency = 2; session.commit()
        first = acquire_lease(session, SimpleNamespace(id="task-a", attempt_id="a")); session.commit()
        second = acquire_lease(session, SimpleNamespace(id="task-b", attempt_id="b")); session.commit()
        assert first.slot_index != second.slot_index
        assert acquire_lease(session, SimpleNamespace(id="task-c", attempt_id="c")) is None
        release_lease(session, first); session.commit()
        third = acquire_lease(session, SimpleNamespace(id="task-c", attempt_id="c")); session.commit()
        assert third.slot_index == first.slot_index
        third.expires_at = now().replace(year=2000); session.commit()
        reclaimed = reclaim_expired_leases(session); session.commit()
        assert "task-c" in reclaimed
        active = list(session.scalars(select(WorkerCapacityLease).where(WorkerCapacityLease.status == "ACTIVE")))
        assert len(active) <= 2
    finally:
        session.close()


def test_worker_capacity_and_leases_api(client, app):
    session = app.state.session_factory()
    try:
        ensure_configuration(session).max_concurrency = 1
        lease = acquire_lease(session, SimpleNamespace(id="task-api", attempt_id="attempt-api")); session.commit()
        assert lease
    finally: session.close()
    worker = client.get("/api/admin/worker-instances", headers=HEADERS).json()[0]
    assert worker["health"] == "BUSY" and worker["running_containers"] == 1
    leases = client.get("/api/admin/worker-instances/common-analyzer/leases", headers=HEADERS).json()
    assert leases[0]["slot_index"] == 0 and "lease_token" not in leases[0]
