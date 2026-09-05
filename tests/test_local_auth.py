from fastapi.testclient import TestClient

from solution_advisor.api.app import create_app
from solution_advisor.common_analyzer.queue import RedisAnalysisQueue
import fakeredis


def test_local_superadmin_bootstrap_and_login(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLUTION_ADVISOR_LOCAL_AUTH_HMAC_KEY", "local-test-signing-key-which-is-not-production")
    monkeypatch.setenv("SOLUTION_ADVISOR_SUPERADMIN_PASSWORD", "superadmin")
    monkeypatch.setenv("SOLUTION_ADVISOR_LOCAL_BOOTSTRAP_ENABLED", "true")
    monkeypatch.setenv("SOLUTION_ADVISOR_LOCAL_BOOTSTRAP_LOGIN", "superadmin")
    monkeypatch.setenv("SOLUTION_ADVISOR_ENTERPRISE_SSO_ENABLED", "false")
    monkeypatch.delenv("SOLUTION_ADVISOR_IDENTITY_BOOTSTRAP_SUPER_SUBJECT", raising=False)
    app = create_app(database_url=f"sqlite:///{tmp_path / 'local.sqlite3'}", storage_root=tmp_path / "uploads",
        queue=RedisAnalysisQueue(fakeredis.FakeRedis()), test_identities=False)
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/options").json() == {
            "local_login_enabled": True, "enterprise_sso_enabled": False,
        }
        assert client.post("/api/v1/auth/local/login", json={"username": "superadmin", "password": "wrong-password"}).status_code == 401
        response = client.post("/api/v1/auth/local/login", json={"username": "superadmin", "password": "superadmin"})
        assert response.status_code == 200
        assert response.json()["token_type"] == "Cookie"
        assert "solution_advisor_session" in response.headers["set-cookie"]
        session = client.get("/api/v1/auth/session", headers={"Authorization": ""})
        assert session.status_code == 200
        assert session.json()["role"] == "SUPER_ADMIN"
        users = client.get("/api/admin/users", headers={"Authorization": ""}).json()
        local = next(item for item in users if item["subject"] == "local:superadmin")
        assert local == {"subject": "local:superadmin", "display_name": "超级管理员", "role": "SUPER_ADMIN", "active": True,
                         "username": "superadmin", "auth_source": "LOCAL"}
        created = client.post("/api/admin/people", headers={"Authorization": ""}, json={
            "login_name": "short-password-user", "display_name": "短密码用户", "role": "USER",
            "initial_password": "1",
        })
        assert created.status_code == 201
        login = client.post("/api/v1/auth/local/login", json={
            "username": "short-password-user", "password": "1",
        })
        assert login.status_code == 200 and login.json()["password_change_required"] is False
        assert client.get("/api/v1/model-assets", headers={"Authorization": ""}).status_code == 200
        assert client.post("/api/v1/auth/local/password/change", headers={"Authorization": ""}, json={"current_password":"1", "new_password":"2"}).status_code == 204
        # Password change revokes even the current session; the user must
        # explicitly establish a new session with the new password.
        assert client.get("/api/v1/model-assets", headers={"Authorization": ""}).status_code in {401, 403}
        assert client.post("/api/v1/auth/local/login", json={"username": "short-password-user", "password": "2"}).status_code == 200
        assert client.get("/api/v1/model-assets", headers={"Authorization": ""}).status_code == 200
        # Notifications are an authenticated, redacted projection of existing
        # account/flow/platform facts.  They never return password material.
        notifications = client.get("/api/v1/auth/notifications", headers={"Authorization": ""})
        assert notifications.status_code == 200
        assert any(item["kind"] == "account" and "密码已修改" in item["summary"] for item in notifications.json())
        assert all("short-password-user" not in str(item) and "password" not in str(item).lower()
                   for item in notifications.json())
        first_notification = notifications.json()[0]
        assert first_notification["id"] and first_notification["read"] is False
        assert client.post(f"/api/v1/auth/notifications/{first_notification['id']}/read",
                           headers={"Authorization": ""}).status_code == 204
        after_one_read = client.get("/api/v1/auth/notifications", headers={"Authorization": ""}).json()
        assert next(item for item in after_one_read if item["id"] == first_notification["id"])["read"] is True
        assert client.post("/api/v1/auth/notifications/read-all", headers={"Authorization": ""}).status_code == 204
        assert all(item["read"] for item in client.get("/api/v1/auth/notifications", headers={"Authorization": ""}).json())
        assert client.delete(f"/api/v1/auth/notifications/{first_notification['id']}",
                             headers={"Authorization": ""}).status_code == 204
        assert all(item["id"] != first_notification["id"]
                   for item in client.get("/api/v1/auth/notifications", headers={"Authorization": ""}).json())
        assert client.delete("/api/v1/auth/notifications", headers={"Authorization": ""}).status_code == 204
        assert client.get("/api/v1/auth/notifications", headers={"Authorization": ""}).json() == []
        assert client.post("/api/v1/auth/local/login", json={"username": "superadmin", "password": "superadmin"}).status_code == 200
        defaulted = client.post("/api/admin/people", headers={"Authorization": ""}, json={
            "login_name": "default-password-user", "display_name": "默认密码用户", "role": "USER",
        })
        assert defaulted.status_code == 201 and defaulted.json()["status"] == "ACTIVE"
        assert client.post("/api/v1/auth/local/login", json={"username": "default-password-user", "password": "Realthon_1"}).status_code == 200
