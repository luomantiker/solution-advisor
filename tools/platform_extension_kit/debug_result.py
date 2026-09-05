#!/usr/bin/env python3
"""以安全、可读的方式摘要 Runner result.json，而不是输出原始结果或敏感字段。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BOUNDARIES = ("board_validation", "performance", "accuracy", "deployment_recommendation")


def summarize(result: dict[str, object]) -> list[str]:
    lines = [
        f"状态：{result.get('status', 'UNKNOWN')}",
        f"平台：{result.get('platform_id', 'UNKNOWN')}",
        f"阶段：{result.get('stage', 'UNKNOWN')}",
        f"摘要：{result.get('summary', '无')}",
        f"产物数：{len(result.get('artifacts', [])) if isinstance(result.get('artifacts'), list) else 0}",
        f"证据数：{len(result.get('evidence', [])) if isinstance(result.get('evidence'), list) else 0}",
        "验证边界：",
    ]
    boundaries = result.get("boundaries")
    if isinstance(boundaries, dict):
        lines.extend(f"  - {key}: {boundaries.get(key, 'UNKNOWN')}" for key in BOUNDARIES)
    else:
        lines.append("  - 未提供")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="摘要平台 Runner 结果")
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        parser.error("result.json 根节点必须为对象")
    print("\n".join(summarize(result)))


if __name__ == "__main__":
    main()
