from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RUNNER_VERSION = "1.0.0"
PACKAGE_VERSION = "3.7.0"
IMAGE_ID = "sha256:eb401fa186f8f368d2c8d60d9b051893ee2be3c7317285f87c10e296eef9fce7"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runner_content_sha256() -> str:
    """The reviewed release content, recorded with every fixed-runner result."""
    return sha256(Path(__file__).resolve())


def execute(request_path: Path, result_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result = {"schema_version": "1.0", "task_id": request.get("task_id"), "subtask_id": request.get("subtask_id"),
              "status": "FAILED", "stages": [], "artifacts": [], "evidence": [],
              "platform_package": {"id": "s100", "version": PACKAGE_VERSION},
              "runner_release": "s100-runner-1.0.0", "runner_version": RUNNER_VERSION,
              "runner_content_sha256": runner_content_sha256(),
              "toolchain": {"image_id": IMAGE_ID, "hb_compile": "3.5.3", "hbdk": "4.7.5", "hmct": "2.6.5"},
              "accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED", "power": "NOT_VERIFIED",
              "deployment_recommendation": "NOT_VERIFIED", "completed_at": datetime.now(timezone.utc).isoformat()}
    model = request_path.parent / "model.onnx"
    out = result_path.parent / "artifacts"; out.mkdir(parents=True, exist_ok=True)
    log = out / "hb_compile.log"
    if request.get("schema_version") != "1.0" or request.get("capability") != "compile":
        result["reason_code"] = "INVALID_REQUEST"
    elif not model.is_file() or sha256(model) != request.get("model", {}).get("sha256"):
        result["reason_code"] = "MODEL_SHA256_MISMATCH"
    else:
        command = ["hb_compile", "--fast-perf", "--march", "nash-e", "--model", str(model)]
        try:
            with log.open("wb") as stream:
                run = subprocess.run(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT,
                                     timeout=int(request.get("timeout_seconds", 1800)), check=False)
            result["evidence"].append({"type": "s100_compile_log", "path": str(log), "sha256": sha256(log), "size_bytes": log.stat().st_size})
            hbm = next(iter(out.rglob("*.hbm")), None)
            result["stages"].append({"name": "compile", "status": "SUCCEEDED" if run.returncode == 0 and hbm else "FAILED", "returncode": run.returncode})
            if run.returncode == 0 and hbm:
                result["artifacts"].append({"type": "compiled_model_artifact", "format": "s100_hbm", "filename": hbm.name,
                                            "path": str(hbm), "sha256": sha256(hbm), "size_bytes": hbm.stat().st_size})
                result.update({"status": "SUCCEEDED", "reason_code": "COMPILE_SUCCEEDED"})
            else:
                result["reason_code"] = "COMPILE_FAILED"
        except subprocess.TimeoutExpired:
            result["stages"].append({"name": "compile", "status": "TIMED_OUT"}); result["reason_code"] = "COMPILE_TIMEOUT"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "SUCCEEDED" else 2


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("execute"); parser.add_argument("--request", required=True); parser.add_argument("--result", required=True)
    args = parser.parse_args(); return execute(Path(args.request), Path(args.result))


if __name__ == "__main__":
    raise SystemExit(main())
