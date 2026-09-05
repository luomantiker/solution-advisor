from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_advisor.common_analyzer.domain import AnalyzerConfigVersion, AnalyzerConfiguration
from solution_advisor.common_analyzer.service import (
    DEFAULT_MODULES,
    ConfigError,
    audit as analyzer_audit,
    config_hash,
    ensure_configuration,
    validate_configuration,
)
from solution_advisor.system_settings.domain import SystemSetting


MODEL_DELETION_KEY = "allow_evaluated_model_deletion"

# 基础结构分析由 core_profile 固定提供，不能在系统设置中关闭。扩展模块
# 只能来自 Git 中已安装、可审查的模块目录；页面只选择是否启用，不接受
# 脚本、命令、路径或任意参数。
ONNX_EXTENSION_MODULES = {
    "model_size": {
        "name": "模型文件与规模检查",
        "description": "记录模型文件大小，便于评估上传与制品规模。",
    },
    "dynamic_shape": {
        "name": "动态 Shape 检查",
        "description": "识别输入输出中的动态维度，提示后续平台评测需使用受控输入。",
    },
}


def model_deletion_enabled(session: Session) -> bool:
    setting = session.get(SystemSetting, MODEL_DELETION_KEY)
    return bool(setting.bool_value) if setting else False


def update_model_deletion_enabled(session: Session, enabled: bool, actor: str) -> SystemSetting:
    setting = session.get(SystemSetting, MODEL_DELETION_KEY)
    if setting is None:
        setting = SystemSetting(key=MODEL_DELETION_KEY, bool_value=enabled, updated_by=actor)
        session.add(setting)
    else:
        setting.bool_value = enabled
        setting.updated_by = actor
        setting.revision += 1
    session.flush()
    return setting


def onnx_analysis_policy(session: Session) -> dict:
    """Return the active, versioned policy without executable details."""
    config = ensure_configuration(session)
    modules = config.modules or {}
    return {
        "revision": config.revision,
        "base_checks": [{
            "id": "core_profile",
            "name": "基础 ONNX 结构检查",
            "description": "校验 ONNX 合法性，并提取 IR、Opset、输入输出、节点和算子统计。",
            "enabled": True,
            "required": True,
        }],
        "extensions": [{
            "id": module_id,
            **metadata,
            "enabled": bool(modules.get(module_id, {}).get("enabled")),
        } for module_id, metadata in ONNX_EXTENSION_MODULES.items()],
    }


def update_onnx_analysis_policy(
    session: Session, *, extension_enabled: dict[str, bool], expected_revision: int, actor: str
) -> dict:
    """Publish one immutable configuration version for selected extensions."""
    if set(extension_enabled) != set(ONNX_EXTENSION_MODULES) or any(
        not isinstance(value, bool) for value in extension_enabled.values()
    ):
        raise ConfigError("invalid_extension_policy")

    config = session.execute(
        select(AnalyzerConfiguration).where(AnalyzerConfiguration.id == "default").with_for_update()
    ).scalar_one_or_none()
    if config is None:
        config = ensure_configuration(session)
    if expected_revision != config.revision:
        raise ConfigError("version_conflict")

    modules = deepcopy(config.modules or DEFAULT_MODULES)
    modules["core_profile"]["enabled"] = True
    for module_id, enabled in extension_enabled.items():
        modules[module_id]["enabled"] = enabled
    validate_configuration(modules, config.max_concurrency)

    if modules != config.modules:
        old_version = config.revision
        next_version = old_version + 1
        session.add(AnalyzerConfigVersion(
            version=next_version,
            modules=deepcopy(modules),
            max_concurrency=config.max_concurrency,
            config_hash=config_hash(modules, config.max_concurrency),
            created_by=actor,
            change_note="更新通用 ONNX 扩展检查策略",
        ))
        config.revision, config.modules = next_version, modules
        analyzer_audit(
            session,
            "SYSTEM_POLICY_PUBLISH",
            actor,
            old_version=old_version,
            new_version=next_version,
            summary="更新通用 ONNX 扩展检查策略",
        )
    session.flush()
    return onnx_analysis_policy(session)
