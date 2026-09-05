"""Restricted X5 board smoke adapter.

It is intentionally host-side and only accepts a local, administrator-managed
profile.  The control plane never supplies a board address, credentials, paths
or command text.  `hrt_model_exec perf` is a single fixed Runtime invocation;
its raw profile files remain evidence and are parsed conservatively into a
performance ViewModel. Accuracy, power, stability and deployment conclusions
remain outside this adapter.
"""
from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

import yaml

from solution_advisor.workers.x5_profile_parser import parse_x5_perf_profile, runtime_versions
from solution_advisor.evaluations.x5_performance_advice import build_x5_performance_advice


class BoardSmokeError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class X5BoardSmokeRunner:
    """Runs the fixed X5 board preflight and one fixed Runtime process."""

    def __init__(self, profile_path: Path):
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise BoardSmokeError("board_profile_invalid")
        required = ("host", "port", "username", "password_file", "known_hosts_file", "remote_work_root")
        if any(not isinstance(profile.get(key), (str, int)) or not str(profile.get(key)) for key in required):
            raise BoardSmokeError("board_profile_incomplete")
        password_file = Path(str(profile["password_file"]))
        known_hosts = Path(str(profile["known_hosts_file"]))
        if not password_file.is_file() or password_file.stat().st_mode & 0o077:
            raise BoardSmokeError("board_secret_invalid")
        if not known_hosts.is_file():
            raise BoardSmokeError("board_known_hosts_missing")
        self.profile = profile

    def _base(self) -> list[str]:
        return ["sshpass", "-f", str(self.profile["password_file"])]

    def _ssh(self, command: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        args = [*self._base(), "ssh", "-o", "BatchMode=no", "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={self.profile['known_hosts_file']}", "-p", str(self.profile["port"]),
                f"{self.profile['username']}@{self.profile['host']}", command]
        return subprocess.run(args, text=True, capture_output=True, timeout=60, check=check)

    def _scp_to(self, source: Path, remote: str) -> None:
        args = [*self._base(), "scp", "-P", str(self.profile["port"]), "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={self.profile['known_hosts_file']}", str(source),
                f"{self.profile['username']}@{self.profile['host']}:{remote}"]
        subprocess.run(args, text=True, capture_output=True, timeout=120, check=True)

    def _scp_from(self, remote: str, target: Path) -> None:
        args = [*self._base(), "scp", "-r", "-P", str(self.profile["port"]), "-o", "StrictHostKeyChecking=yes",
                "-o", f"UserKnownHostsFile={self.profile['known_hosts_file']}",
                f"{self.profile['username']}@{self.profile['host']}:{remote}", str(target)]
        subprocess.run(args, text=True, capture_output=True, timeout=120, check=True)

    def run(self, *, task_id: str, model_bin: Path, output_root: Path) -> dict:
        if not task_id.startswith("task_") or not model_bin.is_file():
            raise BoardSmokeError("board_request_invalid")
        output_root.mkdir(parents=True, exist_ok=True)
        remote = f"{str(self.profile['remote_work_root']).rstrip('/')}/{task_id}"
        quoted = shlex.quote(remote)
        preflight: dict[str, str] = {}
        commands = {
            "system": "uname -srmo",
            "runtime": "hrt_model_exec --version || hrt_model_exec -V",
            "bpu_access": "test -r /dev/bpu || test -r /dev/bpu0",
        }
        try:
            for name, command in commands.items():
                completed = self._ssh(command)
                preflight[name] = "ACCESSIBLE" if name == "bpu_access" else (completed.stdout.strip() or "NOT_COLLECTED")
            self._ssh(f"mkdir -p {quoted}/profile")
            self._scp_to(model_bin, f"{remote}/model.bin")
            # This is the sole board Runtime invocation in R0.  No user input,
            # dynamic command, perf_time or thread_num can reach this call.
            runtime = self._ssh(
                f"hrt_model_exec perf --model_file {quoted}/model.bin --profile_path {quoted}/profile",
                check=False,
            )
            (output_root / "board_preflight.json").write_text(
                json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (output_root / "board_load.log").write_text(
                "model.bin 已受控下发；hrt_model_exec perf 将加载与执行合并，加载阶段无法由该 Runtime 单独拆分。\n",
                encoding="utf-8",
            )
            # `hrt_model_exec` writes failures to stderr.  It is a fixed
            # Runtime command, so retaining its diagnostic is necessary to
            # distinguish a real Runtime failure from a connection failure.
            # No SSH stderr, credentials or connection command is retained.
            inference_log = runtime.stdout if runtime.stdout.strip() else runtime.stderr
            (output_root / "board_inference.log").write_text(inference_log, encoding="utf-8")
            profile_dir = output_root / "profile"
            if runtime.returncode == 0:
                self._scp_from(f"{remote}/profile", profile_dir)
            performance = parse_x5_perf_profile(profile_dir) if runtime.returncode == 0 else {
                "schema_version": "1.0", "status": "NOT_COLLECTED", "evidence_level": "NOT_VERIFIED",
                "runner": "hrt_model_exec perf", "reason_code": "runtime_failed",
            }
            performance["environment"] = {"system": preflight.get("system", "NOT_COLLECTED"),
                                          "runtime_version": preflight.get("runtime", "NOT_COLLECTED"),
                                          "bpu_access": preflight.get("bpu_access", "NOT_COLLECTED"),
                                          **runtime_versions(inference_log)}
            performance["guidance"] = build_x5_performance_advice(performance)
            status = "SUCCEEDED" if runtime.returncode == 0 else "FAILED"
            result = {
                "status": status,
                "task_kind": "REAL_BOARD_SMOKE",
                "board_preflight": "SUCCEEDED",
                "model_transfer": "SUCCEEDED",
                "model_load": "NOT_SEPARABLE_BY_RUNTIME_COMMAND",
                "single_runtime_invocation": "SUCCEEDED" if runtime.returncode == 0 else "FAILED",
                "model_bin_sha256": sha256(model_bin),
                "input_sha256": "NOT_COLLECTED_RUNTIME_INTERNAL_INPUT",
                "output_sha256": "NOT_COLLECTED_RUNTIME_PROFILE_ONLY",
                "runtime": {"command": "hrt_model_exec perf", "version": preflight.get("runtime", "NOT_COLLECTED"),
                            **runtime_versions(inference_log)},
                "performance": performance,
                "extensions": {"accuracy": {"status": "NOT_VERIFIED", "extension_point": "versioned_inputs_and_output_comparison"},
                               "power": {"status": "NOT_VERIFIED", "extension_point": "board_power_sampler"}},
                "boundaries": {"performance": performance["status"], "accuracy": "NOT_VERIFIED",
                               "stability": "NOT_VERIFIED", "power": "NOT_VERIFIED",
                               "deployment_recommendation": "NOT_VERIFIED"},
                "reason_code": None if runtime.returncode == 0 else "board_runtime_failed",
            }
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            result = {"status": "FAILED", "task_kind": "REAL_BOARD_SMOKE", "reason_code": "board_connection_or_preflight_failed",
                      "board_preflight": "FAILED", "model_transfer": "NOT_EXECUTED",
                      "model_load": "NOT_EXECUTED", "single_runtime_invocation": "NOT_EXECUTED",
                      "error_class": type(exc).__name__, "boundaries": {"performance": "NOT_VERIFIED",
                      "accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED", "power": "NOT_VERIFIED",
                      "deployment_recommendation": "NOT_VERIFIED"}}
        (output_root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
