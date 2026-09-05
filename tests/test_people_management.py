from sqlalchemy import select

from solution_advisor.platforms.domain import AccountAudit, AuthenticationSession, UserAccount

SUPER = {"Authorization": "Bearer development-super-admin-token"}
ADMIN = {"Authorization": "Bearer development-admin-token"}


def activate_local(client, login: str, initial: str, changed: str):
    response = client.post("/api/v1/auth/local/login", json={"username": login, "password": initial})
    assert response.status_code == 200 and response.json()["password_change_required"] is False
    assert client.post("/api/v1/auth/local/password/change", headers={"Authorization": ""},
                       json={"current_password": initial, "new_password": changed}).status_code == 204
    # A voluntary password change ends the old session; subsequent management
    # actions require an explicit login with the replacement password.
    assert client.post("/api/v1/auth/local/login", json={"username": login, "password": changed}).status_code == 200


def test_personnel_roles_password_lifecycle_sessions_and_audit(client):
    admin = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "accept-admin", "display_name": "验收管理员", "role": "ADMIN", "initial_password": "initial-admin",
    })
    user = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "accept-user", "display_name": "验收普通用户", "role": "USER", "initial_password": "initial-user",
        "quota": {"flows": 3}, "capability_scope": {"reports": "read"},
    })
    assert admin.status_code == user.status_code == 201
    assert admin.json()["status"] == "ACTIVE"
    assert "password" not in admin.json()
    activate_local(client, "accept-admin", "initial-admin", "changed-admin")
    # New password account is now active; use its cookie to prove admin cannot create an administrator.
    denied = client.post("/api/admin/people", headers={"Authorization": ""}, json={
        "login_name": "not-allowed", "display_name": "不允许", "role": "ADMIN", "initial_password": "x",
    })
    assert denied.status_code == 403
    created_by_admin = client.post("/api/admin/people", headers={"Authorization": ""}, json={
        "login_name": "managed-user", "display_name": "管理员创建用户", "role": "USER", "initial_password": "x",
    })
    assert created_by_admin.status_code == 201
    # Restore superadmin token to suspend the active admin and prove the cookie is invalid immediately.
    item = admin.json()
    suspended = client.post(f"/api/admin/people/{item['id']}/suspend", headers=SUPER | {"If-Match": str(item["revision"] + 1)}, json={"reason": "验收回收"})
    assert suspended.status_code == 200 and suspended.json()["status"] == "SUSPENDED"
    assert client.get("/api/v1/auth/session", headers={"Authorization": ""}).status_code in {401, 403}
    session = client.app.state.session_factory()
    try:
        account = session.get(UserAccount, admin.json()["id"])
        assert account.password_hash and "initial-admin" not in account.password_hash and account.must_change_password is False
        assert session.scalar(select(AuthenticationSession).where(AuthenticationSession.account_id == account.id,
                       AuthenticationSession.revoked_at.is_not(None)))
        summaries = [x.summary for x in session.scalars(select(AccountAudit).where(AccountAudit.account_id == account.id))]
        assert all("initial-admin" not in text and "changed-admin" not in text for text in summaries)
    finally:
        session.close()


def test_person_revision_conflict_and_failed_login_lock(client):
    person = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "revision-user", "display_name": "修订用户", "role": "USER", "initial_password": "one",
    }).json()
    updated = client.patch(f"/api/admin/people/{person['id']}", headers=SUPER | {"If-Match": str(person["revision"])},
                           json={"display_name": "修订用户新名"})
    assert updated.status_code == 200
    conflict = client.patch(f"/api/admin/people/{person['id']}", headers=SUPER | {"If-Match": str(person["revision"])},
                            json={"display_name": "过期写入"})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "person_revision_conflict"
    for _ in range(5):
        assert client.post("/api/v1/auth/local/login", json={"username": "revision-user", "password": "bad"}).status_code == 401
    assert client.post("/api/v1/auth/local/login", json={"username": "revision-user", "password": "one"}).status_code == 429


def test_admin_can_manage_only_users_and_direct_privileged_id_is_forbidden(client):
    administrator = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "protected-admin", "display_name": "受保护管理员", "role": "ADMIN", "initial_password": "x",
    }).json()
    user = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "visible-user", "display_name": "可管理普通用户", "role": "USER", "initial_password": "x",
    }).json()
    listed = client.get("/api/admin/people", headers=ADMIN)
    assert listed.status_code == 200
    assert {item["role"] for item in listed.json()} == {"USER"}
    assert any(item["id"] == user["id"] for item in listed.json())
    for method, path, payload in (
        ("patch", f"/api/admin/people/{administrator['id']}", {"display_name": "伪造修改"}),
        ("post", f"/api/admin/people/{administrator['id']}/suspend", {"reason": "伪造停用"}),
        ("post", f"/api/admin/people/{administrator['id']}/password-reset", {"initial_password": "x"}),
    ):
        response = getattr(client, method)(path, headers=ADMIN | {"If-Match": str(administrator["revision"])}, json=payload)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "admin_can_manage_users_only"
    assert client.get("/api/admin/people", headers={"Authorization": "Bearer development-user-token"}).status_code == 403


def test_people_list_supports_source_role_status_keyword_and_pagination(client):
    generated = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "generated-user", "display_name": "内部生成验收用户", "role": "USER", "initial_password": "x",
    })
    assert generated.status_code == 201
    assert generated.json()["person_source"] == "INTERNAL_GENERATED"

    first = client.get(
        "/api/admin/people?source=INTERNAL_GENERATED&role=USER&status=ACTIVE&keyword=%E5%86%85%E9%83%A8&page=1&page_size=10",
        headers=SUPER,
    )
    assert first.status_code == 200
    body = first.json()
    assert body["page"] == 1 and body["page_size"] == 10 and body["total"] >= 1
    assert any(item["id"] == generated.json()["id"] for item in body["items"])
    assert all(item["person_source"] == "INTERNAL_GENERATED" for item in body["items"])

    test_person = client.post("/api/admin/people", headers=SUPER, json={
        "login_name": "manual-test-user", "display_name": "人工测试账号", "role": "USER",
        "initial_password": "x", "test_only": True,
    })
    assert test_person.status_code == 201
    assert test_person.json()["person_source"] == "TEST_ONLY"
    test_only = client.get("/api/admin/people?source=TEST_ONLY&page=1&page_size=10", headers=SUPER)
    assert test_only.status_code == 200
    assert any(item["id"] == test_person.json()["id"] for item in test_only.json()["items"])

    for supported_size in (20, 50):
        response = client.get(f"/api/admin/people?page=1&page_size={supported_size}", headers=SUPER)
        assert response.status_code == 200
        assert response.json()["page_size"] == supported_size

    invalid_size = client.get("/api/admin/people?page=1&page_size=12", headers=SUPER)
    assert invalid_size.status_code == 422
    invalid_source = client.get("/api/admin/people?source=UNKNOWN&page=1&page_size=10", headers=SUPER)
    assert invalid_source.status_code == 422
