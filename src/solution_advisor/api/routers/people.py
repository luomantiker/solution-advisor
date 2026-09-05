"""Personnel and authorization lifecycle; authentication secrets never leave this module."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update

from solution_advisor.api.routers.auth import audit, normalized_login, revoke_sessions
from solution_advisor.artifacts.domain import Artifact
from solution_advisor.common_analyzer.domain import AnalysisEvent, AnalysisTask
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationTask, EvaluationTaskShare
from solution_advisor.model_assets.domain import ModelAsset, ModelAssetAccess, ModelProfile, ResourceAccessAudit
from solution_advisor.platforms.domain import (
    AccountAudit, AuthenticationSession, IdentityLink, PlatformAudit,
    PlatformCandidate, PlatformCatalog, PlatformType, UserAccount, UserNotificationState,
)
from solution_advisor.platforms.service import utcnow
from solution_advisor.security import ADMIN, SUPER_ADMIN, USER, password_hash, resolve_principal

router = APIRouter(prefix="/api/admin/people", tags=["people"])
DEFAULT_LOCAL_PASSWORD = "Realthon_1"


class PersonCreate(BaseModel):
    login_name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern=r"^(USER|ADMIN)$")
    initial_password: str = Field(default=DEFAULT_LOCAL_PASSWORD, min_length=1, max_length=256)
    quota: dict = Field(default_factory=dict)
    capability_scope: dict = Field(default_factory=dict)
    test_only: bool = False


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, pattern=r"^(USER|ADMIN)$")
    quota: dict | None = None
    capability_scope: dict | None = None
    reason: str = Field(default="", max_length=500)


class PasswordReset(BaseModel):
    initial_password: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=500)


class StateChange(BaseModel):
    reason: str = Field(default="", max_length=500)


def actor(request: Request, authorization: str | None):
    return resolve_principal(request, authorization, ADMIN, SUPER_ADMIN)


def visible(principal, account: UserAccount) -> bool:
    return principal.role == SUPER_ADMIN or account.role == USER


def payload(account: UserAccount) -> dict:
    return {"id": account.id, "login_name": account.username, "display_name": account.display_name,
            "role": account.role, "status": account.status, "active": account.active,
            "person_source": account.person_source or "INTERNAL_GENERATED",
            "quota": account.quota or {}, "capability_scope": account.capability_scope or {},
            "auth_provider_type": account.auth_provider_type, "issuer": account.issuer,
            "identity_subject": account.identity_subject, "must_change_password": account.must_change_password,
            "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
            "revision": account.revision,
            "created_at": account.created_at.isoformat() if account.created_at else None,
            "updated_at": account.updated_at.isoformat() if account.updated_at else None}


def target(session, principal, person_id: str) -> UserAccount:
    item = session.get(UserAccount, person_id)
    if not item:
        raise HTTPException(404, {"code": "person_not_found"})
    # 对管理员必须明确拒绝越权对象，不能让已知 ID 的写入被前端误判为
    # “对象不存在”。超级管理员仍受唯一超级管理员约束保护。
    if principal.role == ADMIN and item.role != USER:
        raise HTTPException(403, {"code": "admin_can_manage_users_only"})
    return item


def revision(item: UserAccount, if_match: str | None) -> int:
    if if_match != str(item.revision):
        raise HTTPException(409, {"code": "person_revision_conflict", "revision": item.revision,
                                  "person": {"display_name": item.display_name, "role": item.role, "status": item.status}})
    return item.revision


def _remove_account_resources(session, subject: str, storage_uris: list[str]) -> None:
    """Remove terminal user work while retaining bytes still shared by somebody else.

    The function intentionally reuses the public Flow cleanup helper: reports,
    stage rows and Evidence have several dependency edges and must never be
    partially deleted by personnel management.
    """
    from solution_advisor.api.routers.evaluations import _delete_terminal_tasks, delete_terminal_flow_records

    terminal = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMEOUT"}
    flows = list(session.scalars(select(EvaluationFlow).where(EvaluationFlow.owner_subject == subject)))
    standalone = list(session.scalars(select(EvaluationTask).where(
        EvaluationTask.owner_subject == subject, EvaluationTask.flow_id.is_(None),
    )))
    flow_tasks = [task for flow in flows for task in session.scalars(
        select(EvaluationTask).where(EvaluationTask.flow_id == flow.id)
    )]
    if any(task.status not in terminal for task in [*flow_tasks, *standalone]):
        raise HTTPException(409, {"code": "person_has_running_evaluations", "message": "该人员仍有排队或执行中的评估，请先等待结束或取消后再删除。"})
    for flow in flows:
        delete_terminal_flow_records(session, flow, storage_uris)
    _delete_terminal_tasks(session, [task.id for task in standalone], storage_uris)

    # The deleted person must not keep access to another person's model or
    # report, regardless of whether their own model bytes are retained.
    session.execute(delete(EvaluationTaskShare).where(
        or_(EvaluationTaskShare.subject == subject, EvaluationTaskShare.shared_by == subject)
    ))
    session.execute(delete(ResourceAccessAudit).where(or_(
        ResourceAccessAudit.actor_subject == subject, ResourceAccessAudit.recipient_subject == subject,
    )))

    asset_ids = set(session.scalars(select(ModelAssetAccess.model_asset_id).where(ModelAssetAccess.subject == subject)))
    asset_ids.update(session.scalars(select(ModelAsset.id).where(ModelAsset.owner_subject == subject)))
    session.execute(delete(ModelAssetAccess).where(ModelAssetAccess.subject == subject))
    session.flush()

    for asset_id in asset_ids:
        asset = session.get(ModelAsset, asset_id)
        if not asset:
            continue
        remaining_access = session.scalar(select(ModelAssetAccess.id).where(ModelAssetAccess.model_asset_id == asset.id))
        profiles = list(session.scalars(select(ModelProfile).where(ModelProfile.model_asset_id == asset.id)))
        profile_ids = [profile.id for profile in profiles]
        remaining_work = bool(session.scalar(select(EvaluationFlow.id).where(EvaluationFlow.model_profile_id.in_(profile_ids or [""])))) or bool(
            session.scalar(select(EvaluationTask.id).where(EvaluationTask.model_profile_id.in_(profile_ids or [""])) )
        )
        if remaining_access or remaining_work:
            # A shared global byte store needs a durable owner for display and
            # authorization bookkeeping.  The earliest remaining grant wins.
            grant = session.scalar(select(ModelAssetAccess).where(ModelAssetAccess.model_asset_id == asset.id).order_by(ModelAssetAccess.created_at))
            if grant:
                asset.owner_subject = grant.subject
            continue
        for analysis_task in session.scalars(select(AnalysisTask).where(AnalysisTask.model_asset_id == asset.id)):
            session.execute(delete(AnalysisEvent).where(AnalysisEvent.task_id == analysis_task.id))
            session.delete(analysis_task)
        for profile in profiles:
            session.delete(profile)
        model_artifact = session.get(Artifact, asset.artifact_id) if asset.artifact_id else None
        session.delete(asset)
        session.flush()
        if model_artifact:
            storage_uris.append(model_artifact.uri)
            session.delete(model_artifact)


def _transfer_platform_governance(session, storage, subject: str, successor: str, actor) -> None:
    """Preserve global platform facts but never transfer an in-progress claim."""
    session.execute(update(PlatformCatalog).where(PlatformCatalog.created_by == subject).values(created_by=successor))
    session.execute(update(PlatformType).where(PlatformType.created_by == subject).values(created_by=successor))
    session.execute(update(PlatformCandidate).where(PlatformCandidate.created_by == subject).values(created_by=successor))
    # Manual Candidate claims cannot be handed to another person.  Reuse the
    # same cleanup path as a manual/super-admin release, otherwise package and
    # validation material from the deleted person's attempt would leak into a
    # later claim. Catalog-linked Candidates remain immutable provenance.
    from solution_advisor.api.routers.platforms import clear_candidate_work_materials

    claimed = list(session.scalars(select(PlatformCandidate).where(
        PlatformCandidate.claimed_by == subject,
        PlatformCandidate.catalog_id.is_(None),
    )))
    for candidate in claimed:
        old = candidate.revision
        candidate.claimed_by = candidate.claimed_by_name = candidate.claimed_at = candidate.lease_expires_at = None
        candidate.last_handled_by, candidate.last_handled_at, candidate.revision = successor, utcnow(), old + 1
        clear_candidate_work_materials(
            session, storage, candidate, actor=actor,
            action="CANDIDATE_OWNER_ACCOUNT_DELETED",
            reason="认领人员账号已删除，已清理本次接入工作资料",
        )
    # A catalog-linked Candidate is audit provenance and cannot be actively
    # claimed. Clear any anomalous legacy claim without touching its evidence.
    session.execute(update(PlatformCandidate).where(
        PlatformCandidate.claimed_by == subject,
        PlatformCandidate.catalog_id.is_not(None),
    ).values(
        claimed_by=None, claimed_by_name=None, claimed_at=None, lease_expires_at=None,
        last_handled_by=successor, last_handled_at=utcnow(), revision=PlatformCandidate.revision + 1,
    ))
    # Historical audit actors remain immutable facts.  They are not account
    # ownership fields and must not be rewritten during a personnel cleanup.


@router.get("")
def list_people(request: Request, source: str | None = None, role: str | None = None,
                status: str | None = None, keyword: str | None = None,
                page: int | None = None, page_size: int | None = None,
                authorization: str | None = Header(None)):
    principal = actor(request, authorization); session = request.app.state.session_factory()
    try:
        query = select(UserAccount).order_by(UserAccount.created_at)
        if principal.role == ADMIN:
            query = query.where(UserAccount.role == USER)
        if source and source != "ALL":
            if source not in {"SYSTEM_BUILTIN", "INTERNAL_GENERATED", "USER_REGISTERED", "TEST_ONLY"}:
                raise HTTPException(422, {"code": "invalid_person_source"})
            query = query.where(UserAccount.person_source == source)
        if role and role != "ALL":
            if role not in {SUPER_ADMIN, ADMIN, USER}:
                raise HTTPException(422, {"code": "invalid_person_role"})
            query = query.where(UserAccount.role == role)
        if status and status != "ALL":
            if status not in {"ACTIVE", "SUSPENDED"}:
                raise HTTPException(422, {"code": "invalid_person_status"})
            query = query.where(UserAccount.status == status)
        if keyword and keyword.strip():
            value = f"%{keyword.strip()}%"
            query = query.where(or_(UserAccount.display_name.ilike(value), UserAccount.username.ilike(value)))
        # 保留无查询参数时的历史列表契约；人员管理页面显式携带分页参数，
        # 因而可获得 total / page 元数据而无需一次加载所有账号。
        if page is None and page_size is None and not any((source, role, status, keyword)):
            return [payload(item) for item in session.scalars(query)]
        current_page = max(page or 1, 1)
        current_size = page_size or 10
        if current_size not in {10, 20, 50}:
            raise HTTPException(422, {"code": "invalid_person_page_size"})
        total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
        rows = list(session.scalars(query.offset((current_page - 1) * current_size).limit(current_size)))
        return {"items": [payload(item) for item in rows], "total": total,
                "page": current_page, "page_size": current_size,
                "page_count": max((total + current_size - 1) // current_size, 1)}
    finally:
        session.close()


@router.post("", status_code=201)
def create_person(body: PersonCreate, request: Request, authorization: str | None = Header(None)):
    principal = actor(request, authorization)
    if principal.role != SUPER_ADMIN and body.role != USER:
        raise HTTPException(403, {"code": "admin_can_manage_users_only"})
    session = request.app.state.session_factory()
    try:
        login = normalized_login(body.login_name)
        if session.scalar(select(UserAccount).where(UserAccount.username == login)):
            raise HTTPException(409, {"code": "login_name_exists"})
        item = UserAccount(id=f"local:{login}", username=login, display_name=body.display_name, role=body.role,
                           active=True, status="ACTIVE", auth_source="LOCAL", auth_provider_type="LOCAL",
                           identity_subject=login, password_hash=password_hash(body.initial_password),
                           # 人工创建的验收/演示账号需要被明确区分，避免与真实
                           # 内部人员混在同一个治理列表中。
                           person_source="TEST_ONLY" if body.test_only else "INTERNAL_GENERATED", must_change_password=False,
                           quota=body.quota, capability_scope=body.capability_scope, revision=1)
        session.add(item); session.flush()
        session.add(IdentityLink(account_id=item.id, provider_type="LOCAL", issuer=None, subject=login))
        audit(session, principal.subject, item, "PERSON_CREATED", 0,
              f"创建已启用{body.role}本地人员；来源 {'测试专用' if body.test_only else '内部生成'}")
        session.commit(); return payload(item)
    finally:
        session.close()


@router.patch("/{person_id}")
def update_person(person_id: str, body: PersonUpdate, request: Request,
                  if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = actor(request, authorization); session = request.app.state.session_factory()
    try:
        item = target(session, principal, person_id); old = revision(item, if_match)
        if body.role is not None:
            if principal.role != SUPER_ADMIN:
                raise HTTPException(403, {"code": "admin_can_manage_users_only"})
            if item.role == SUPER_ADMIN:
                raise HTTPException(422, {"code": "use_super_admin_handover"})
            item.role = body.role
        if body.display_name is not None: item.display_name = body.display_name
        if body.quota is not None: item.quota = body.quota
        if body.capability_scope is not None: item.capability_scope = body.capability_scope
        item.revision = old + 1
        revoked = revoke_sessions(session, item.id) if body.role is not None else 0
        audit(session, principal.subject, item, "PERSON_UPDATED", old, f"更新人员资料；撤销会话 {revoked} 个", body.reason or None)
        session.commit(); return payload(item)
    finally:
        session.close()


@router.post("/{person_id}/suspend")
def suspend_person(person_id: str, body: StateChange, request: Request,
                   if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = actor(request, authorization); session = request.app.state.session_factory()
    try:
        item = target(session, principal, person_id); old = revision(item, if_match)
        if item.id == principal.subject or item.role == SUPER_ADMIN:
            raise HTTPException(422, {"code": "super_admin_cannot_suspend_self_or_super_admin"})
        item.status, item.active, item.revision = "SUSPENDED", False, old + 1
        revoked = revoke_sessions(session, item.id)
        audit(session, principal.subject, item, "PERSON_SUSPENDED", old, f"停用人员并撤销会话 {revoked} 个", body.reason or None)
        session.commit(); return payload(item)
    finally:
        session.close()


@router.post("/{person_id}/activate")
def activate_person(person_id: str, body: StateChange, request: Request,
                    if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = actor(request, authorization); session = request.app.state.session_factory()
    try:
        item = target(session, principal, person_id); old = revision(item, if_match)
        if item.role == SUPER_ADMIN and principal.role != SUPER_ADMIN:
            raise HTTPException(403, {"code": "super_admin_required"})
        item.status, item.active, item.must_change_password, item.revision = "ACTIVE", True, False, old + 1
        audit(session, principal.subject, item, "PERSON_ACTIVATED", old, "已启用本地人员", body.reason or None)
        session.commit(); return payload(item)
    finally:
        session.close()


@router.post("/{person_id}/password-reset", status_code=204)
def reset_password(person_id: str, body: PasswordReset, request: Request,
                   if_match: str | None = Header(None, alias="If-Match"), authorization: str | None = Header(None)):
    principal = actor(request, authorization); session = request.app.state.session_factory()
    try:
        item = target(session, principal, person_id); old = revision(item, if_match)
        item.password_hash, item.password_updated_at = password_hash(body.initial_password), utcnow()
        item.status, item.active, item.must_change_password, item.revision = "ACTIVE", True, False, old + 1
        revoked = revoke_sessions(session, item.id)
        audit(session, principal.subject, item, "PERSON_PASSWORD_RESET", old, f"已重置初始密码并撤销会话 {revoked} 个", body.reason or None)
        session.commit()
    finally:
        session.close()


@router.delete("/{person_id}")
def delete_person(person_id: str, request: Request,
                  if_match: str | None = Header(None, alias="If-Match"),
                  authorization: str | None = Header(None)) -> dict:
    """Hard-delete a non-super-admin account after its terminal work is cleaned.

    Global platform definitions are governance assets rather than personal
    files, so their ownership is reassigned to the acting super administrator.
    Candidate claims are cleared instead of transferred: another administrator
    must start from a clean workspace under the R3 manual-claim rules.
    """
    principal = actor(request, authorization)
    if principal.role != SUPER_ADMIN:
        raise HTTPException(403, {"code": "super_admin_required"})
    session = request.app.state.session_factory()
    storage_uris: list[str] = []
    try:
        item = target(session, principal, person_id)
        old = revision(item, if_match)
        if item.id == principal.subject:
            raise HTTPException(422, {"code": "cannot_delete_current_super_admin"})
        if item.role == SUPER_ADMIN:
            raise HTTPException(422, {"code": "use_super_admin_handover"})

        _remove_account_resources(session, item.id, storage_uris)
        _transfer_platform_governance(
            session, request.app.state.artifact_storage, item.id, principal.subject, principal,
        )
        session.add(PlatformAudit(
            action="PERSON_PLATFORM_OWNERSHIP_TRANSFERRED", actor=principal.subject,
            result="SUCCEEDED", summary=f"删除人员 {item.username or item.id}；平台治理归属已转移，进行中的 Candidate 认领已清理",
        ))
        session.execute(delete(UserNotificationState).where(UserNotificationState.account_id == item.id))
        session.execute(delete(AuthenticationSession).where(AuthenticationSession.account_id == item.id))
        session.execute(delete(IdentityLink).where(IdentityLink.account_id == item.id))
        session.execute(delete(AccountAudit).where(AccountAudit.account_id == item.id))
        session.delete(item)
        session.commit()
    finally:
        session.close()
    for uri in set(storage_uris):
        try:
            request.app.state.artifact_storage.delete(uri)
        except Exception:
            # The database is the authorization source. A failed physical byte
            # cleanup is safe orphan retention, never a reason to resurrect a
            # deleted user's access.
            pass
    return {"deleted": True, "old_revision": old}
