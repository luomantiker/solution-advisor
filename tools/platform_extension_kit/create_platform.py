#!/usr/bin/env python3
"""生成一个最小、平台无关的平台包骨架。

本工具只写入新目录，不下载镜像、不启动容器，也不调用任何厂商工具链。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PLATFORM_ID = re.compile(r"^[a-z][a-z0-9-]*$")


README = """# __DISPLAY_NAME__ 平台包

这是由 `tools/platform_extension_kit/create_platform.py` 生成的初始骨架。

它只声明 `static_check` 能力，**不表示**已经完成编译、板端验证、性能测试或可交付部署。

## 接入者下一步

1. 根据厂商正式手册补充 `rules/rules.yaml`；规则必须是平台事实，不能混入控制面逻辑。
2. 在 `docker/image.lock.yaml` 写入已审查的镜像不可变摘要和镜像内固定入口；不要写 Token、密码或主机路径。
3. 在 `runner/platform_runner/__main__.py` 的受控位置实现固定工具调用；不得执行来自任务输入的 Shell、路径或镜像命令。
4. 填写 `worker-agent/instance.config.example.yaml`，由运行人员以通用 Agent 部署该平台实例。
5. 先运行离线契约检查，再由有权限的环境运行镜像自检：

```bash
uv run python tools/platform_extension_kit/check_platform.py platform_packages/__PLATFORM_ID__
bash platform_packages/__PLATFORM_ID__/scripts/self_check_image.sh <已锁定镜像引用>
```

镜像自检脚本不会被控制面自动调用；它是接入人员在有 Docker 权限的主机上使用的显式检查工具。
"""


RUNNER = '''"""__DISPLAY_NAME__ 平台 Runner 示例。

此示例仅执行平台无关的静态检查并输出受限结论。接入真实编译时，
只能在 TODO 标记的固定实现中调用经审查的厂商命令。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PLATFORM_ID = "__PLATFORM_ID__"


def execute(request: dict[str, object]) -> dict[str, object]:
    if request.get("platform_id") != PLATFORM_ID:
        raise ValueError("platform_id_mismatch")
    if not request.get("model_sha256"):
        raise ValueError("model_sha256_required")

    # TODO: 在此处添加固定、白名单化的厂商工具调用；绝不能拼接任务提供的命令。
    return {
        "status": "SUCCEEDED",
        "platform_id": PLATFORM_ID,
        "stage": "static_check",
        "summary": "仅完成离线静态检查；不可用于交付结论。",
        "artifacts": [],
        "evidence": [],
        "boundaries": {
            "board_validation": "NOT_EXECUTED",
            "performance": "NOT_VERIFIED",
            "accuracy": "NOT_VERIFIED",
            "deployment_recommendation": "NOT_VERIFIED",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("execute")
    parser.add_argument("--request", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    result = execute(request)
    Path(args.result).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")


if __name__ == "__main__":
    main()
'''


SELF_CHECK = '''#!/usr/bin/env bash
set -euo pipefail

# 仅供接入人员在有 Docker 权限的主机上手工运行；控制面不会调用它。
image="${1:?请传入 image.lock.yaml 中已审查的镜像引用}"
docker image inspect "$image" >/dev/null

# TODO: 用镜像内固定的厂商工具版本命令替换占位符，例如 `vendor-compiler --version`。
docker run --rm --read-only --entrypoint sh "$image" -lc '<vendor-tool> --version'
'''


def render(value: str, platform_id: str, display_name: str) -> str:
    return value.replace("__PLATFORM_ID__", platform_id).replace("__DISPLAY_NAME__", display_name)


def write_file(root: Path, relative: str, content: str, executable: bool = False) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if executable:
        target.chmod(target.stat().st_mode | 0o111)


def create(platform_id: str, display_name: str, output: Path) -> None:
    if not PLATFORM_ID.fullmatch(platform_id):
        raise ValueError("platform_id 必须为小写字母开头，仅包含小写字母、数字和连字符")
    if output.exists():
        raise FileExistsError(f"输出目录已存在，拒绝覆盖：{output}")
    output.mkdir(parents=True)
    capabilities = ["static_check"]
    write_file(output, "README.md", render(README, platform_id, display_name))
    write_file(output, "manifest.yaml", "\n".join([
        'schema_version: "1.0"', f"id: {platform_id}", 'version: "0.1.0"',
        "capabilities:", *[f"  - {item}" for item in capabilities],
        "runner:", "  module: platform_runner", '  version: "0.1.0"',
        "rules:", '  version: "0.1.0"', "image_lock: docker/image.lock.yaml",
        "board_validation: NOT_EXECUTED", "performance: NOT_VERIFIED",
        "accuracy: NOT_VERIFIED", "deployment_recommendation: NOT_VERIFIED", "",
    ]))
    write_file(output, "docker/image.lock.yaml", "\n".join([
        'schema_version: "1.0"', f"platform_id: {platform_id}", "images: []",
        "# 接入时填入带 digest 的镜像和固定入口；不得写入凭据。", "",
    ]))
    write_file(output, "rules/rules.yaml", "\n".join([
        'schema_version: "1.0"', f"platform_id: {platform_id}", "rules: []",
        "# 仅存放平台事实和受支持范围；不要写控制面、Shell 或主机路径。", "",
    ]))
    write_file(output, "reports/README.md", "# 报告扩展\n\n仅定义该平台报告的受限事实字段；所有未验证项必须显式标为 `NOT_VERIFIED`。\n")
    write_file(output, "tests/static-request.json", json.dumps({"platform_id": platform_id, "model_sha256": "0" * 64}, ensure_ascii=False, indent=2) + "\n")
    write_file(output, "runner/platform_runner/__init__.py", "")
    write_file(output, "runner/platform_runner/__main__.py", render(RUNNER, platform_id, display_name))
    write_file(output, "worker-agent/instance.config.example.yaml", "\n".join([
        f"platform_id: {platform_id}", "instance_id: <平台实例标识，例如 j6m-a>", "control_plane_url: https://<控制面地址>",
        "agent_token: <仅通过受限环境变量或密钥文件注入，禁止提交>", "max_concurrency: 1", "",
    ]))
    write_file(output, "scripts/self_check_image.sh", SELF_CHECK, executable=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成平台包标准骨架")
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        create(args.platform_id, args.display_name, args.output)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"已生成平台包骨架：{args.output}")


if __name__ == "__main__":
    main()
