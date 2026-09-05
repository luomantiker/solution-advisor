"""Parse raw profile files emitted by ``hrt_model_exec perf`` conservatively.

Raw files remain Evidence.  A CPU timing segment is not by itself proof that a
model operator ran on CPU; compile allocation is the source for that conclusion.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PARSER_VERSION = "x5-hrt-profile-1.0"


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _documents(profile_dir: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    # X5 Runtime 1.24.x may store the JSON fragments in ``profiler.log``
    # instead of a ``.json`` file.  The files are produced by the fixed
    # Runtime invocation and retained as Evidence; CSV and unrelated logs are
    # still ignored when they contain no valid JSON document.
    for path in profile_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".json", ".log"}:
            continue
        try:
            for part in path.read_text(encoding="utf-8", errors="replace").split("***"):
                value = json.loads(part.strip()) if part.strip() else None
                if isinstance(value, dict):
                    documents.append(value)
        except (OSError, json.JSONDecodeError):
            continue
    return documents


def parse_x5_perf_profile(profile_dir: Path) -> dict[str, Any]:
    """Return a stable performance ViewModel without guessing unavailable data."""
    perf: dict[str, Any] = {}; condition: dict[str, Any] = {}; model_latency: dict[str, Any] = {}
    processor_latency: dict[str, Any] = {}; task_latency: dict[str, Any] = {}
    for document in _documents(profile_dir):
        perf.update(document.get("perf_result") or {})
        condition.update(document.get("running_condition") or {})
        model_latency.update(document.get("model_latency") or {})
        processor_latency.update(document.get("processor_latency") or {})
        task_latency.update(document.get("task_latency") or {})
    segments = []
    for name, timing in model_latency.items():
        if isinstance(timing, dict):
            segments.append({"name": name, "processor": "BPU" if name.startswith("BPU_") else "RUNTIME_STAGE",
                             "average_ms": _number(timing.get("avg_time")), "minimum_ms": _number(timing.get("min_time")),
                             "maximum_ms": _number(timing.get("max_time"))})
    cpu_timing = processor_latency.get("CPU_inference_time_cost")
    bpu_timing = processor_latency.get("BPU_inference_time_cost")
    available = bool(perf or condition or segments or processor_latency)
    return {
        "schema_version": "1.0", "parser_version": PARSER_VERSION,
        "status": "MEASURED" if available else "NOT_COLLECTED",
        "evidence_level": "BOARD_MEASURED" if available else "NOT_VERIFIED", "runner": "hrt_model_exec perf",
        "metrics": {"fps": _number(perf.get("FPS")), "average_latency_ms": _number(perf.get("average_latency"))},
        "running_condition": {"model_name": condition.get("model_name", "NOT_COLLECTED"),
                              "core_id": _number(condition.get("core_id")), "thread_num": _number(condition.get("thread_num")),
                              "frame_count": _number(condition.get("frame_count")), "run_time_ms": _number(condition.get("run_time"))},
        "segments": segments,
        "processor_latency_ms": {"bpu": bpu_timing if isinstance(bpu_timing, dict) else "NOT_COLLECTED",
                                  "cpu": cpu_timing if isinstance(cpu_timing, dict) else "NOT_COLLECTED"},
        "task_latency_ms": task_latency or "NOT_COLLECTED",
        "cpu_execution_segment_present": isinstance(cpu_timing, dict),
        "model_cpu_operator_assessment": {"status": "REQUIRES_COMPILE_ALLOCATION",
            "explanation": "profile 的 CPU 耗时只证明 Runtime 存在 CPU 执行段；模型 CPU 算子需结合编译分配日志判断。"},
        "raw_profile_files": sorted(path.name for path in profile_dir.rglob("*") if path.is_file()),
    }


def runtime_versions(inference_log: str) -> dict[str, str]:
    patterns = {"model_builder_version": r"model builder version\s*=\s*([^\s]+)",
                "bpu_platform_version": r"BPU platform version\s*=\s*([^\s]+)"}
    return {key: match.group(1) for key, pattern in patterns.items()
            if (match := re.search(pattern, inference_log, flags=re.IGNORECASE))}
