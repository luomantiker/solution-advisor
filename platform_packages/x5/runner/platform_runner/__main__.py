from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNNER_VERSION = "1.0.0"
PACKAGE_VERSION = "1.0.0"
RULE_VERSION = "1.0.0"
IMAGE_ID = "sha256:e9230ca9c1b65e4688f6103dad547b0785f75cd1ecbb536e7d939a7188419593"
sys.path.insert(0, "/runner")
try:
    from rules.x5_rules import parse_compile_log, static_rules
except ImportError:  # packaged image layout
    from x5_rules import parse_compile_log, static_rules


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result_base(request: dict) -> dict:
    return {"schema_version": "1.0", "task_id": request.get("task_id"), "subtask_id": request.get("subtask_id"),
            "status": "FAILED", "stages": [], "input_sha256": request.get("model", {}).get("sha256"),
            "toolchain": {"hb_mapper": "1.24.3", "image_id": IMAGE_ID},
            "platform_package": {"id": "x5", "version": PACKAGE_VERSION},
            "runner_version": RUNNER_VERSION, "rule_version": RULE_VERSION, "artifacts": [], "evidence": [],
            "board_validation": "NOT_EXECUTED", "performance": "NOT_VERIFIED", "accuracy": "NOT_VERIFIED",
            "stability": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED",
            "completed_at": datetime.now(timezone.utc).isoformat()}


def execute(request_path: Path, result_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8")); result = result_base(request)
    model = request_path.parent / "model.onnx"; capability = request.get("capability")
    if request.get("schema_version") != "1.0" or capability not in {"static_check", "compile"}:
        result["reason_code"] = "INVALID_REQUEST"
    elif not model.is_file() or sha256(model) != request["model"]["sha256"]:
        result["reason_code"] = "MODEL_SHA256_MISMATCH"
    else:
        static = {"status": "SUCCEEDED", "rules": [], "model_sha256": sha256(model)}
        try:
            import onnx
            loaded = onnx.load(model)
            static.update({"ir_version": loaded.ir_version, "opsets": [x.version for x in loaded.opset_import], "node_count": len(loaded.graph.node), "rules": static_rules(loaded)})
        except Exception as exc:
            static.update({"status": "FAILED", "reason_code": "ONNX_PARSE_FAILED", "summary": type(exc).__name__})
        result["stages"].append({"name": "static_check", **static})
        static_path = result_path.parent / "artifacts" / "static_check.json"
        static_path.parent.mkdir(parents=True, exist_ok=True)
        static_path.write_text(json.dumps(static, ensure_ascii=False, indent=2), encoding="utf-8")
        result["evidence"].append({"type": "x5_static_check", "path": str(static_path),
                                   "sha256": sha256(static_path), "size_bytes": static_path.stat().st_size})
        if static["status"] != "SUCCEEDED": result["reason_code"] = static["reason_code"]
        elif capability == "static_check": result["status"] = "SUCCEEDED"; result["reason_code"] = "STATIC_CHECK_SUCCEEDED"
        else:
            out = result_path.parent / "artifacts"; out.mkdir(parents=True, exist_ok=True); log = out / "hb_mapper_makertbin.log"
            command = ["hb_mapper", "makertbin", "--fast-perf", "--model", str(model), "--model-type", "onnx", "--march", "bayes-e"]
            try:
                with log.open("wb") as stream:
                    run = subprocess.run(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT, timeout=int(request.get("timeout_seconds", 3600)), check=False)
                parsed = parse_compile_log(log.read_text(encoding="utf-8", errors="ignore"))
                summary_path = out / "compile_summary.json"
                summary_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
                result["evidence"].append({"type": "x5_compile_log", "path": str(log), "sha256": sha256(log), "size_bytes": log.stat().st_size, "summary": parsed})
                result["evidence"].append({"type": "x5_compile_summary", "path": str(summary_path), "sha256": sha256(summary_path), "size_bytes": summary_path.stat().st_size})
                bins = list(out.rglob("*.bin"))
                result["stages"].append({"name": "compile", "status": "SUCCEEDED" if run.returncode == 0 and bins else "FAILED", "returncode": run.returncode})
                if run.returncode == 0 and bins:
                    model_bin = bins[0]
                    result["artifacts"].append({"type": "compiled_model_artifact", "format": "x5_bin", "filename": "model.bin", "path": str(model_bin), "sha256": sha256(model_bin), "size_bytes": model_bin.stat().st_size})
                    result["status"] = "SUCCEEDED"; result["reason_code"] = "COMPILE_SUCCEEDED"
                else: result["reason_code"] = "COMPILE_FAILED"
            except subprocess.TimeoutExpired:
                result["stages"].append({"name": "compile", "status": "TIMED_OUT"}); result["reason_code"] = "COMPILE_TIMEOUT"
    result_path.parent.mkdir(parents=True, exist_ok=True); result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "SUCCEEDED" else 2


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("execute"); parser.add_argument("--request", required=True); parser.add_argument("--result", required=True); args = parser.parse_args()
    return execute(Path(args.request), Path(args.result))

if __name__ == "__main__": raise SystemExit(main())
