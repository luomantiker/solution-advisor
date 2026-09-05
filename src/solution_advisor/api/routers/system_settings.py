from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Header, HTTPException, Request

from solution_advisor.security import SUPER_ADMIN, resolve_principal
from solution_advisor.system_settings.domain import SystemSetting
from solution_advisor.system_settings.service import (
    model_deletion_enabled,
    onnx_analysis_policy,
    update_model_deletion_enabled,
    update_onnx_analysis_policy,
)
from solution_advisor.common_analyzer.service import ConfigError


router = APIRouter(prefix="/api/admin/system-settings", tags=["system-settings"])


class ModelDeletionPolicyInput(BaseModel):
    allow_evaluated_model_deletion: bool


class OnnxAnalysisPolicyInput(BaseModel):
    revision: int
    extensions: dict[str, bool]


def _super_admin(request: Request, authorization: str | None):
    principal = resolve_principal(request, authorization, SUPER_ADMIN)
    if principal.role != SUPER_ADMIN:
        raise HTTPException(403, {"code": "super_admin_required"})
    return principal


def _payload(session) -> dict:
    setting = session.get(SystemSetting, "allow_evaluated_model_deletion")
    return {
        "allow_evaluated_model_deletion": model_deletion_enabled(session),
        "revision": setting.revision if setting else 0,
        "updated_at": setting.updated_at.isoformat() if setting and setting.updated_at else None,
    }


@router.get("")
def get_system_settings(request: Request, authorization: str | None = Header(None)) -> dict:
    _super_admin(request, authorization)
    session = request.app.state.session_factory()
    try:
        return _payload(session)
    finally:
        session.close()


@router.put("")
def set_system_settings(payload: ModelDeletionPolicyInput, request: Request, authorization: str | None = Header(None)) -> dict:
    principal = _super_admin(request, authorization)
    session = request.app.state.session_factory()
    try:
        update_model_deletion_enabled(session, payload.allow_evaluated_model_deletion, principal.subject)
        session.commit()
        return _payload(session)
    finally:
        session.close()


@router.get("/onnx-analysis-policy")
def get_onnx_analysis_policy(request: Request, authorization: str | None = Header(None)) -> dict:
    _super_admin(request, authorization)
    session = request.app.state.session_factory()
    try:
        result = onnx_analysis_policy(session)
        # Upgraded installations may not have a configuration row yet.
        session.commit()
        return result
    finally:
        session.close()


@router.put("/onnx-analysis-policy")
def set_onnx_analysis_policy(
    payload: OnnxAnalysisPolicyInput, request: Request, authorization: str | None = Header(None)
) -> dict:
    principal = _super_admin(request, authorization)
    session = request.app.state.session_factory()
    try:
        result = update_onnx_analysis_policy(
            session,
            extension_enabled=payload.extensions,
            expected_revision=payload.revision,
            actor=principal.subject,
        )
        session.commit()
        return result
    except ConfigError as exc:
        session.rollback()
        raise HTTPException(409 if str(exc) == "version_conflict" else 422, {"code": str(exc)})
    finally:
        session.close()
