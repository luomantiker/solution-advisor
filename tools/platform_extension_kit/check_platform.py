#!/usr/bin/env python3
"""离线检查平台包的最小契约，不访问 Docker、网络、板卡或工具链。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml


REQUIRED_FILES = (
    "README.md",
    "manifest.yaml",
    "docker/image.lock.yaml",
    "rules/rules.yaml",
    "reports/README.md",
    "tests/static-request.json",
    "runner/platform_runner/__init__.py",
    "runner/platform_runner/__main__.py",
    "worker-agent/instance.config.example.yaml",
    "scripts/self_check_image.sh",
)
ALLOWED_CAPABILITIES = {"static_check", "compile"}
PLATFORM_ID = re.compile(r"^[a-z][a-z0-9-]*$")


def load_yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: YAML 根节点必须为对象")
    return value


def check(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"缺少必需文件：{relative}")
    if errors:
        return errors
    try:
        manifest = load_yaml(root / "manifest.yaml")
        image_lock = load_yaml(root / "docker/image.lock.yaml")
        rules = load_yaml(root / "rules/rules.yaml")
        request = json.loads((root / "tests/static-request.json").read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return [f"配置格式错误：{exc}"]

    platform_id = manifest.get("id")
    if not isinstance(platform_id, str) or not PLATFORM_ID.fullmatch(platform_id):
        errors.append("manifest.id 必须是合法的小写平台 ID")
        return errors
    if root.name != platform_id:
        errors.append(f"目录名 {root.name!r} 必须与 manifest.id {platform_id!r} 一致")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append("manifest.capabilities 必须是非空列表")
    elif not set(capabilities).issubset(ALLOWED_CAPABILITIES):
        errors.append("manifest.capabilities 仅允许 static_check 或 compile")
    if image_lock.get("platform_id") != platform_id:
        errors.append("image.lock.yaml 的 platform_id 必须与 manifest.id 一致")
    if rules.get("platform_id") != platform_id:
        errors.append("rules.yaml 的 platform_id 必须与 manifest.id 一致")
    if not isinstance(request, dict) or request.get("platform_id") != platform_id:
        errors.append("tests/static-request.json 的 platform_id 必须与 manifest.id 一致")
    model_hash = request.get("model_sha256") if isinstance(request, dict) else None
    if not isinstance(model_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", model_hash):
        errors.append("tests/static-request.json 必须提供 64 位小写 model_sha256")
    if "board_test" in capabilities if isinstance(capabilities, list) else False:
        errors.append("M4-A 平台包不得声明 board_test；板端验证属于后续边界")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="检查平台包离线契约")
    parser.add_argument("platform_root", type=Path)
    args = parser.parse_args()
    errors = check(args.platform_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    manifest = load_yaml(args.platform_root / "manifest.yaml")
    print(f"OK: {manifest['id']} 平台包离线契约通过")


if __name__ == "__main__":
    main()
