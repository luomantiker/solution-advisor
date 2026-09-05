"""Verified identity boundary: three persisted roles only."""
from __future__ import annotations

import base64, hashlib, hmac, json, secrets, time
from datetime import timedelta
from dataclasses import dataclass
from typing import Protocol
from fastapi import HTTPException, Request
from sqlalchemy import select, update

USER, ADMIN, SUPER_ADMIN = "USER", "ADMIN", "SUPER_ADMIN"
ROLES = {USER, ADMIN, SUPER_ADMIN}

@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    role: str


@dataclass(frozen=True)
class VerifiedIdentity:
    """An authenticated subject.  A token never authorizes a role by itself."""
    subject: str
    display_name: str
    test_role: str | None = None
    provider_type: str = "EXTERNAL"


# A local password is only one AuthenticationProvider.  Business routers use
# Principal resolved from the Account table and therefore do not branch on it.
AuthenticatedPrincipal = VerifiedIdentity


class AuthenticationProvider(Protocol):
    provider_type: str

    def authenticate(self, username: str, password: str): ...

class IdentityVerifier:
    def __init__(self, settings): self.settings = settings

    def verify(self, request: Request, authorization: str | None) -> VerifiedIdentity:
        if not authorization and request.cookies.get("solution_advisor_session"):
            return self._verify_session(request.cookies["solution_advisor_session"], request)
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, {"code": "identity_required"})
        token = authorization[7:]
        if self.settings.enable_test_identities:
            values = {
                "development-user-token": VerifiedIdentity("dev-user", "普通用户", USER, "TEST"),
                "development-user-2-token": VerifiedIdentity("dev-user-2", "普通用户 U2", USER, "TEST"),
                "development-admin-token": VerifiedIdentity("dev-admin-1", "管理员 U1", ADMIN, "TEST"),
                "development-admin-2-token": VerifiedIdentity("dev-admin-2", "管理员 U2", ADMIN, "TEST"),
                "development-super-admin-token": VerifiedIdentity("dev-super-admin", "超级管理员", SUPER_ADMIN, "TEST"),
            }
            if token in values: return values[token]
        try:
            header, claims, signature = token.split(".")
            signed = f"{header}.{claims}".encode()
            payload = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
            if payload.get("iss") == self.settings.local_auth_issuer:
                key, audience = self.settings.local_auth_hmac_key, self.settings.local_auth_audience
            else:
                if not self.settings.enterprise_sso_enabled:
                    raise HTTPException(403, {"code": "identity_provider_not_configured"})
                key, audience = self.settings.identity_hmac_key, self.settings.identity_audience
            if not key or not audience: raise HTTPException(403, {"code": "identity_provider_not_configured"})
            expected = base64.urlsafe_b64encode(hmac.new(key.encode(), signed, hashlib.sha256).digest()).rstrip(b"=").decode()
            if not hmac.compare_digest(signature, expected): raise ValueError()
            if payload.get("aud") != audience: raise ValueError()
            if payload.get("iss") != self.settings.local_auth_issuer and payload.get("iss") != self.settings.identity_issuer: raise ValueError()
            if not isinstance(payload.get("exp"), (int, float)) or payload["exp"] <= time.time(): raise ValueError()
            subject = payload.get("sub")
            if not isinstance(subject, str) or not subject: raise ValueError()
            # Deliberately ignore any JWT role claim.  Authorization is resolved from users.
            return VerifiedIdentity(subject, str(payload.get("name") or subject), provider_type="LOCAL" if payload.get("iss") == self.settings.local_auth_issuer else "OIDC")
        except (ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(403, {"code": "identity_verification_failed"})

    def _verify_session(self, session_id: str, request: Request) -> VerifiedIdentity:
        from solution_advisor.platforms.domain import AuthenticationSession, UserAccount
        from solution_advisor.platforms.service import utcnow
        session = request.app.state.session_factory()
        try:
            item = session.get(AuthenticationSession, session_id)
            if not item or item.revoked_at or item.expires_at <= utcnow():
                raise HTTPException(401, {"code": "session_invalid"})
            account = session.get(UserAccount, item.account_id)
            if not account:
                raise HTTPException(401, {"code": "session_invalid"})
            item.last_seen_at = utcnow(); session.commit()
            return VerifiedIdentity(account.id, account.display_name, provider_type=account.auth_provider_type)
        finally:
            session.close()


def password_hash(password: str) -> str:
    if not password: raise ValueError("password_required")
    salt = secrets.token_bytes(16); params = (16384, 8, 1)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=params[0], r=params[1], p=params[2])
    return "scrypt$%s$%s$%s$%s$%s" % (*params, base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())


def password_matches(password: str, stored: str | None) -> bool:
    try:
        method, n, r, p, salt, digest = (stored or "").split("$")
        if method != "scrypt": return False
        candidate = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(candidate, base64.urlsafe_b64decode(digest))
    except (ValueError, TypeError): return False


def issue_local_token(settings, subject: str, display_name: str, *, ttl_seconds: int = 8 * 3600) -> str:
    if not settings.local_auth_hmac_key: raise ValueError("local_auth_not_configured")
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    header = encode(b'{"alg":"HS256","typ":"JWT"}')
    claims = encode(json.dumps({"iss": settings.local_auth_issuer, "aud": settings.local_auth_audience,
        "sub": subject, "name": display_name, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode())
    signature = encode(hmac.new(settings.local_auth_hmac_key.encode(), f"{header}.{claims}".encode(), hashlib.sha256).digest())
    return f"{header}.{claims}.{signature}"


def new_session_id() -> str:
    return secrets.token_urlsafe(48)


def resolve_principal(request: Request, authorization: str | None, *roles: str) -> Principal:
    """Resolve a verified identity against the persisted three-role account table."""
    identity = request.app.state.identity_verifier.verify(request, authorization)
    from solution_advisor.platforms.domain import UserAccount
    session = request.app.state.session_factory()
    try:
        account = session.get(UserAccount, identity.subject)
        # Explicit test mode can seed only its fixed fixtures.  Production never auto-provisions.
        if account is None and identity.test_role:
            if identity.test_role == SUPER_ADMIN and session.scalar(select(UserAccount).where(UserAccount.role == SUPER_ADMIN)):
                raise HTTPException(409, {"code": "super_admin_already_exists"})
            account = UserAccount(id=identity.subject, display_name=identity.display_name, role=identity.test_role)
            session.add(account); session.commit()
        if account is None or not account.active or account.status == "SUSPENDED":
            raise HTTPException(403, {"code": "identity_not_provisioned"})
        if account.status == "PENDING_ACTIVATION":
            raise HTTPException(403, {"code": "password_change_required"})
        principal = Principal(account.id, account.display_name, account.role)
        if roles and principal.role not in roles:
            raise HTTPException(403, {"code": "role_forbidden"})
        return principal
    finally:
        session.close()
