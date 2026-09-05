"""Conservative parser for S100 ``hrt_model_exec perf`` evidence.

It deliberately does not import the X5 parser: the formats may look similar,
but each platform owns its parser version and evidence contract.
"""
from __future__ import annotations

import re
from pathlib import Path

PARSER_VERSION = "s100-hrt-profile-1.0"


def parse_s100_perf_profile(profile_dir: Path, runtime_log: str = "") -> dict:
    text = runtime_log + "\n" + "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in profile_dir.glob("*.log")
    )
    def number(label: str) -> float | None:
        found = re.search(label + r"\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", text, flags=re.I)
        return float(found.group(1)) if found else None
    average = number("Thread Average")
    fps = number("FPS")
    return {
        "schema_version": "1.0", "parser": PARSER_VERSION,
        "status": "MEASURED" if average is not None and fps is not None else "NOT_COLLECTED",
        "evidence_level": "BOARD_MEASURED" if average is not None and fps is not None else "NOT_VERIFIED",
        "runner": "hrt_model_exec perf", "average_latency_ms": average, "fps": fps,
        "reason_code": None if average is not None and fps is not None else "s100_profile_metrics_missing",
    }
