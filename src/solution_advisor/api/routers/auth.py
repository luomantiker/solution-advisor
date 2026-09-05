"""Authentication adapters and local-password session lifecycle."""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from solution_advisor.platforms.domain import AccountAudit, AuthenticationSession, PlatformAudit, UserAccount, UserNotificationState
from solution_advisor.evaluations.domain import EvaluationFlow
from solution_advisor.security import ADMIN, SUPER_ADMIN
from solution_advisor.platforms.service import utcnow
from solution_advisor.security import new_session_id, password_hash, password_matches

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SESSION_COOKIE = "solution_advisor_session"
SESSION_TTL_SECONDS = 8 * 3600
LOCK_AFTER_FAILURES = 5
LOCK_SECONDS = 5 * 60


class LocalLogin(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,63}$")
    password: str = Field(min_length=1, max_length=256)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def normalized_login(value: str) -> str:
    return value.strip().lower()


def audit(session, actor: str, account: UserAccount, action: str, old: int | None, summary: str, reason: str | None = None) -> None:
    session.add(AccountAudit(actor=actor, account_id=account.id, action=action, old_revision=old,
                             new_revision=account.revision, summary=summary, reason=reason))


def revoke_sessions(session, account_id: str, *, except_id: str | None = None) -> int:
    query = update(AuthenticationSession).where(AuthenticationSession.account_id == account_id,
                                                 AuthenticationSession.revoked_at.is_(None))
    if except_id:
        query = query.where(AuthenticationSession.id != except_id)
    return int(session.execute(query.values(revoked_at=utcnow())).rowcount or 0)


def session_id_from_request(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def cookie_secure(request: Request) -> bool:
    # Real HTTPS deployments always receive Secure cookies.  The explicit
    # local HTTP acceptance environment remains usable without weakening an
    # HTTPS deployment; reverse proxies may supply X-Forwarded-Proto.
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


def issue_session(response: Response, request: Request, session, account: UserAccount) -> int:
    item = AuthenticationSession(id=new_session_id(), account_id=account.id,
                                 expires_at=utcnow() + timedelta(seconds=SESSION_TTL_SECONDS),
                                 last_seen_at=utcnow())
    session.add(item)
    response.set_cookie(SESSION_COOKIE, item.id, httponly=True, secure=cookie_secure(request),
                        samesite="lax", max_age=SESSION_TTL_SECONDS, path="/")
    return SESSION_TTL_SECONDS


def current_account(request: Request, authorization: str | None, *, allow_pending: bool = False) -> UserAccount:
    identity = request.app.state.identity_verifier.verify(request, authorization)
    session = request.app.state.session_factory()
    try:
        account = session.get(UserAccount, identity.subject)
        if not account or not account.active or account.status == "SUSPENDED":
            raise HTTPException(403, {"code": "identity_not_provisioned"})
        if account.status == "PENDING_ACTIVATION" and not allow_pending:
            raise HTTPException(403, {"code": "password_change_required"})
        session.expunge(account)
        return account
    finally:
        session.close()


@router.get("/options")
def auth_options(request: Request):
    settings = request.app.state.settings
    return {
        "local_login_enabled": bool(settings.local_auth_hmac_key),
        "enterprise_sso_enabled": bool(settings.enterprise_sso_enabled and settings.identity_issuer
                                         and settings.identity_audience and settings.identity_hmac_key),
    }


@router.post("/local/login")
def local_login(body: LocalLogin, request: Request, response: Response):
    settings = request.app.state.settings
    if not settings.local_auth_hmac_key:
        raise HTTPException(403, {"code": "local_auth_not_configured"})
    session = request.app.state.session_factory()
    try:
        account = session.scalar(select(UserAccount).where(UserAccount.username == normalized_login(body.username)))
        now = utcnow()
        if account and account.locked_until and account.locked_until > now:
            raise HTTPException(429, {"code": "local_login_temporarily_locked"})
        valid = bool(account and account.active and account.status != "SUSPENDED" and account.auth_source == "LOCAL"
                     and password_matches(body.password, account.password_hash))
        if not valid:
            if account:
                account.failed_login_count += 1
                if account.failed_login_count >= LOCK_AFTER_FAILURES:
                    account.locked_until = now + timedelta(seconds=LOCK_SECONDS)
                    account.failed_login_count = 0
                session.commit()
            raise HTTPException(401, {"code": "invalid_local_credentials"})
        account.failed_login_count, account.locked_until, account.last_login_at = 0, None, now
        ttl = issue_session(response, request, session, account)
        audit(session, account.id, account, "LOCAL_LOGIN", account.revision, "本地账号创建受控会话")
        session.commit()
        return {"token_type": "Cookie", "expires_in": ttl, "password_change_required": account.must_change_password,
                "user": {"subject": account.id, "display_name": account.display_name, "role": account.role,
                         "status": account.status}}
    finally:
        session.close()


@router.post("/local/logout", status_code=204)
def local_logout(request: Request, response: Response):
    session = request.app.state.session_factory()
    try:
        value = session_id_from_request(request)
        if value:
            item = session.get(AuthenticationSession, value)
            if item and not item.revoked_at:
                item.revoked_at = utcnow(); session.commit()
        response.delete_cookie(SESSION_COOKIE, path="/")
    finally:
        session.close()


@router.post("/local/password/change", status_code=204)
def change_password(body: PasswordChange, request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization, allow_pending=True)
    session = request.app.state.session_factory()
    try:
        account = session.get(UserAccount, principal.id)
        if not password_matches(body.current_password, account.password_hash):
            raise HTTPException(401, {"code": "invalid_current_password"})
        old = account.revision
        account.password_hash = password_hash(body.new_password)
        account.password_updated_at, account.must_change_password = utcnow(), False
        account.status, account.active, account.revision = "ACTIVE", True, old + 1
        # Password changes are a deliberate re-authentication boundary.  The
        # current cookie is revoked too, so a pending account cannot keep a
        # stale session after changing its initial password.
        revoked = revoke_sessions(session, account.id)
        audit(session, account.id, account, "PASSWORD_CHANGED", old, f"密码已更新，已撤销会话 {revoked} 个；需重新登录")
        session.commit()
    finally:
        session.close()


def notification_key(*, kind: str, source_id: str, action: str, created_at: str | None) -> str:
    """Return a stable opaque key without exposing source identifiers to UI."""
    raw = f"{kind}:{source_id}:{action}:{created_at or ''}".encode("utf-8")
    return sha256(raw).hexdigest()


def notification_projection(session, principal: UserAccount) -> list[dict]:
    """Return a small, redacted view of already persisted business events.

    This is deliberately a pull-on-open endpoint, not a new global polling or
    push channel.  Event labels are generated server-side so audit summaries,
    internal URIs and deployment details never become a notification payload.
    """
    items: list[dict] = []
    own_labels = {
        "PASSWORD_CHANGED": "密码已修改，需要使用新密码重新登录。",
        "PERSON_SUSPENDED": "账号已被停用。",
        "PERSON_ACTIVATED": "账号已启用。",
        "PERSON_PASSWORD_RESET": "密码已由管理员重置。",
    }
    for audit_item in session.scalars(select(AccountAudit).where(AccountAudit.account_id == principal.id)
                                      .order_by(AccountAudit.created_at.desc()).limit(24)):
        label = own_labels.get(audit_item.action)
        if label:
            created_at = audit_item.created_at.isoformat() if audit_item.created_at else None
            items.append({"id": notification_key(kind="account", source_id=audit_item.id,
                                                    action=audit_item.action, created_at=created_at),
                          "kind": "account", "summary": label, "created_at": created_at})
    for flow in session.scalars(select(EvaluationFlow).where(EvaluationFlow.owner_subject == principal.id)
                                .order_by(EvaluationFlow.created_at.desc()).limit(24)):
        created_at = flow.created_at.isoformat() if flow.created_at else None
        items.append({"id": notification_key(kind="evaluation", source_id=flow.id, action=flow.status, created_at=created_at),
                      "kind": "evaluation", "summary": f"评估流程状态：{flow.status}", "created_at": created_at})
    if principal.role in {ADMIN, SUPER_ADMIN}:
        platform_labels = {
            "CANDIDATE_FORCE_RELEASED": "Candidate 已被强制释放并清理本次资料。",
            "CANDIDATE_FORCE_ASSIGNED": "Candidate 已清理后指定管理员。",
            "CANDIDATE_RELEASED": "Candidate 已由认领人释放并清理本次资料。",
            "CANDIDATE_CREATED_FROM_IMAGE": "发现镜像已创建 Candidate。",
            "CANDIDATE_REAL_VALIDATION_COMPLETED": "Candidate 真实验证状态已更新。",
        }
        for audit_item in session.scalars(select(PlatformAudit).order_by(PlatformAudit.created_at.desc()).limit(48)):
            label = platform_labels.get(audit_item.action)
            if label:
                created_at = audit_item.created_at.isoformat() if audit_item.created_at else None
                items.append({"id": notification_key(kind="platform", source_id=audit_item.id,
                                                        action=audit_item.action, created_at=created_at),
                              "kind": "platform", "summary": label, "created_at": created_at})
    items = sorted(items, key=lambda item: item["created_at"] or "", reverse=True)[:50]
    if not items:
        return []
    states = {state.notification_key: state for state in session.scalars(
        select(UserNotificationState).where(UserNotificationState.account_id == principal.id,
                                            UserNotificationState.notification_key.in_([item["id"] for item in items]))
    )}
    return [dict(item, read=bool(states.get(item["id"]) and states[item["id"]].read_at)) for item in items
            if not (states.get(item["id"]) and states[item["id"]].deleted_at)]


def notification_state(session, account_id: str, notification_id: str) -> UserNotificationState:
    item = session.scalar(select(UserNotificationState).where(UserNotificationState.account_id == account_id,
                                                               UserNotificationState.notification_key == notification_id))
    if not item:
        item = UserNotificationState(account_id=account_id, notification_key=notification_id)
        session.add(item)
    return item


def current_notification_ids(session, principal: UserAccount) -> set[str]:
    return {item["id"] for item in notification_projection(session, principal)}


@router.get("/notifications")
def notifications(request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization)
    session = request.app.state.session_factory()
    try:
        return notification_projection(session, principal)
    finally:
        session.close()


@router.post("/notifications/read-all", status_code=204)
def mark_all_notifications_read(request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization)
    session = request.app.state.session_factory()
    try:
        for notification_id in current_notification_ids(session, principal):
            notification_state(session, principal.id, notification_id).read_at = utcnow()
        session.commit()
    finally:
        session.close()


@router.delete("/notifications", status_code=204)
def clear_notifications(request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization)
    session = request.app.state.session_factory()
    try:
        for notification_id in current_notification_ids(session, principal):
            state = notification_state(session, principal.id, notification_id)
            state.deleted_at = utcnow()
        session.commit()
    finally:
        session.close()


@router.post("/notifications/{notification_id}/read", status_code=204)
def mark_notification_read(notification_id: str, request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization)
    session = request.app.state.session_factory()
    try:
        if notification_id not in current_notification_ids(session, principal):
            raise HTTPException(404, {"code": "notification_not_found"})
        notification_state(session, principal.id, notification_id).read_at = utcnow()
        session.commit()
    finally:
        session.close()


@router.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(notification_id: str, request: Request, authorization: str | None = Header(None)):
    principal = current_account(request, authorization)
    session = request.app.state.session_factory()
    try:
        if notification_id not in current_notification_ids(session, principal):
            raise HTTPException(404, {"code": "notification_not_found"})
        state = notification_state(session, principal.id, notification_id)
        state.deleted_at = utcnow()
        session.commit()
    finally:
        session.close()


@router.get("/session")
def session_info(request: Request, authorization: str | None = Header(None)):
    account = current_account(request, authorization, allow_pending=True)
    return {"subject": account.id, "display_name": account.display_name, "role": account.role,
            "status": account.status, "auth_source": account.auth_source,
            "password_change_required": account.must_change_password}
