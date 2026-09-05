from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "tools" / "platform_extension_kit"


def run_tool(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(KIT / script), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_generator_creates_checkable_platform_package(tmp_path: Path) -> None:
    target = tmp_path / "j6m"

    created = run_tool(
        "create_platform.py",
        "--platform-id",
        "j6m",
        "--display-name",
        "J6M",
        "--output",
        str(target),
    )

    assert created.returncode == 0, created.stderr
    checked = run_tool("check_platform.py", str(target))
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "j6m 平台包离线契约通过" in checked.stdout
    assert (target / "scripts" / "self_check_image.sh").stat().st_mode & 0o111

    result_path = tmp_path / "result.json"
    runner = subprocess.run(
        [
            sys.executable,
            "-m",
            "platform_runner",
            "execute",
            "--request",
            str(target / "tests" / "static-request.json"),
            "--result",
            str(result_path),
        ],
        cwd=target / "runner",
        text=True,
        capture_output=True,
        check=False,
    )
    assert runner.returncode == 0, runner.stderr
    generated_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert generated_result["status"] == "SUCCEEDED"
    assert generated_result["boundaries"]["board_validation"] == "NOT_EXECUTED"


def test_generator_refuses_to_overwrite_existing_package(tmp_path: Path) -> None:
    target = tmp_path / "j6m"
    target.mkdir()

    result = run_tool(
        "create_platform.py",
        "--platform-id",
        "j6m",
        "--display-name",
        "J6M",
        "--output",
        str(target),
    )

    assert result.returncode != 0
    assert "拒绝覆盖" in result.stderr


def test_debug_result_hides_raw_artifact_values(tmp_path: Path) -> None:
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "platform_id": "j6m",
                "stage": "static_check",
                "summary": "受限结果",
                "artifacts": [{"uri": "s3://private/path"}],
                "evidence": [{"uri": "s3://private/log"}],
                "boundaries": {"board_validation": "NOT_EXECUTED"},
            }
        ),
        encoding="utf-8",
    )

    result = run_tool("debug_result.py", str(result_file))

    assert result.returncode == 0
    assert "产物数：1" in result.stdout
    assert "证据数：1" in result.stdout
    assert "s3://private" not in result.stdout
