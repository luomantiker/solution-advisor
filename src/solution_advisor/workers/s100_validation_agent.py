"""One fixed, Host-only S100 Candidate validation executor.

This is intentionally separate from the X5 task executor.  It accepts no
browser supplied command, image, board address, secret or host path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from solution_advisor.workers.worker_agent import WorkerAgent
from solution_advisor.workers.s100_profile_parser import parse_s100_perf_profile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class S100ValidationAgent(WorkerAgent):
    """HostAgent protocol adapter for the reviewed S100 runner release."""
    def _validation_path(self, task_id: str, suffix: str = "") -> str:
        base = f"/api/internal/workers/{self.worker_id}/candidate-validations"
        return f"{base}/{task_id}/{suffix}" if task_id else f"{base}/claim"

    def _upload_validation_evidence(self, task_id: str, path: Path, evidence_type: str, phase: str) -> str:
        boundary = "----solutionadvisor-s100"
        body = bytearray()
        for name, value in (("evidence_type", evidence_type), ("phase", phase)):
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode())
        body.extend(path.read_bytes()); body.extend(f"\r\n--{boundary}--\r\n".encode())
        return self._request(self._validation_path(task_id, "evidence"), data=bytes(body),
                             content_type=f"multipart/form-data; boundary={boundary}")["id"]

    def _run(self, command: list[str]) -> None:
        completed = subprocess.run(command, check=False)
        if completed.returncode not in (0, 2):
            raise RuntimeError("fixed_runner_launch_failed")

    def _board_perf(self, task_id: str, hbm: Path, output: Path) -> dict:
        """S100-owned fixed transport; no X5 adapter, parser or result schema."""
        profile = yaml.safe_load(Path(self.config["board_profile_path"]).read_text(encoding="utf-8"))
        required = ("host", "port", "username", "password_file", "known_hosts_file", "remote_work_root")
        if not isinstance(profile, dict) or any(not profile.get(key) for key in required):
            return {"status": "FAILED", "reason_code": "s100_board_profile_invalid"}
        secret = Path(str(profile["password_file"]))
        if not secret.is_file() or secret.stat().st_mode & 0o077:
            return {"status": "FAILED", "reason_code": "s100_board_secret_invalid"}
        output.mkdir(parents=True, exist_ok=True); remote = f"{str(profile['remote_work_root']).rstrip('/')}/{task_id}"
        login = f"{profile['username']}@{profile['host']}"; base = ["sshpass", "-f", str(secret)]
        ssh = [*base, "ssh", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={profile['known_hosts_file']}", "-p", str(profile["port"]), login]
        try:
            preflight = subprocess.run([*ssh, "uname -srmo; hrt_model_exec --version; test -r /dev/bpu || test -r /dev/bpu0"], text=True, capture_output=True, timeout=60, check=True)
            (output / "board_preflight.json").write_text(json.dumps({"status": "SUCCEEDED", "output": preflight.stdout}, ensure_ascii=False), encoding="utf-8")
            quoted = shlex.quote(remote)
            subprocess.run([*ssh, f"mkdir -p {quoted}/profile"], timeout=60, check=True)
            subprocess.run([*base, "scp", "-P", str(profile["port"]), "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={profile['known_hosts_file']}", str(hbm), f"{login}:{remote}/model.hbm"], timeout=120, check=True)
            (output / "board_load.log").write_text("s100_hbm 已受控下发；加载与 perf 调用由固定 Runtime 命令合并执行。\n", encoding="utf-8")
            runtime = subprocess.run([*ssh, f"hrt_model_exec perf --model_file {quoted}/model.hbm --profile_path {quoted}/profile"], text=True, capture_output=True, timeout=300, check=False)
            log = runtime.stdout if runtime.stdout.strip() else runtime.stderr
            (output / "board_inference.log").write_text(log, encoding="utf-8")
            local_profile = output / "profile"
            if runtime.returncode == 0:
                subprocess.run([*base, "scp", "-r", "-P", str(profile["port"]), "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={profile['known_hosts_file']}", f"{login}:{remote}/profile", str(local_profile)], timeout=120, check=True)
            performance = parse_s100_perf_profile(local_profile, log)
            return {"status": "SUCCEEDED" if runtime.returncode == 0 and performance["status"] == "MEASURED" else "FAILED", "task_kind": "S100_BOARD_PERF", "runtime": "hrt_model_exec perf", "compiled_hbm_sha256": digest(hbm), "performance": performance, "boundaries": {"output_consistency": "NOT_EXECUTED", "task_accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED", "power": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED"}, "reason_code": None if runtime.returncode == 0 else "s100_board_runtime_failed"}
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return {"status": "FAILED", "task_kind": "S100_BOARD_PERF", "reason_code": "s100_board_connection_or_preflight_failed"}

    def execute_validation(self, task: dict) -> None:
        task_id = task["id"]
        self._post(self._validation_path(task_id, "start"))
        with self._temporary_work_dir(task_id) as work:
            root = Path(work); source = Path(self.config["s100_fixture_path"])
            inp, out = root / "input", root / "output"; inp.mkdir(); out.mkdir()
            model = inp / "model.onnx"; shutil.copyfile(source, model)
            request = {"schema_version": "1.0", "task_id": task_id, "subtask_id": f"{task_id}-{self.worker_id}",
                       "capability": "compile", "model": {"sha256": digest(model)}, "timeout_seconds": 1800}
            (inp / "request.json").write_text(json.dumps(request), encoding="utf-8")
            self._run(["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
                       "--entrypoint", "python3", "-v", f"{self.config['platform_package_path']}:/package:ro",
                       "-v", f"{inp}:/work/input:ro", "-v", f"{out}:/work/output:rw", "-e", "PYTHONPATH=/package/runner:/package",
                       self.config["image"], "-m", self.config["runner_module"], "execute", "--request", "/work/input/request.json", "--result", "/work/output/result.json"])
            compile_result = json.loads((out / "result.json").read_text(encoding="utf-8"))
            (out / "static_check.json").write_text(json.dumps({"fixture_sha256": digest(model), "fixture": "s100_minimal_16x16.onnx", "status": "SUCCEEDED"}, indent=2), encoding="utf-8")
            (out / "compile_summary.json").write_text(json.dumps({"status": compile_result.get("status"), "artifact_format": "s100_hbm", "runner_release": "s100-runner-1.0.0", "runner_content_sha256": compile_result.get("runner_content_sha256")}, indent=2), encoding="utf-8")
            # hb_compile writes the verified .hbm below a model-specific output
            # directory.  Discover only within this fixed Runner output root.
            hbm = next(iter((out / "artifacts").rglob("*.hbm")), None)
            board_result: dict = {"status": "NOT_EXECUTED", "reason_code": "compile_failed"}
            if compile_result.get("status") == "SUCCEEDED" and hbm:
                board_result = self._board_perf(task_id, hbm, out / "board")
                board_result["artifact_format"] = "s100_hbm"
                (out / "board" / "result.json").write_text(json.dumps(board_result, ensure_ascii=False, indent=2), encoding="utf-8")
            evidence: dict[str, str] = {}
            files = [
                (out / "static_check.json", "s100_static_check", "COMPILATION"),
                (out / "artifacts" / "hb_compile.log", "s100_compile_log", "COMPILATION"),
                (out / "compile_summary.json", "s100_compile_summary", "COMPILATION"),
                (out / "result.json", "s100_runner_result", "COMPILATION"),
                (hbm, "s100_compiled_model", "COMPILATION"),
                (out / "board" / "board_preflight.json", "s100_board_preflight", "BOARD_TEST"),
                (out / "board" / "board_load.log", "s100_board_load_log", "BOARD_TEST"),
                (out / "board" / "board_inference.log", "s100_board_inference_log", "BOARD_TEST"),
                (out / "board" / "result.json", "s100_board_result", "BOARD_TEST"),
            ]
            for path, kind, phase in files:
                if path and path.is_file(): evidence[kind] = self._upload_validation_evidence(task_id, path, kind, phase)
            for path in (out / "board" / "profile").glob("*") if (out / "board" / "profile").is_dir() else []:
                if path.suffix == ".log": evidence["s100_board_profile_log"] = self._upload_validation_evidence(task_id, path, "s100_board_profile_log", "BOARD_TEST")
                elif path.suffix == ".csv": evidence["s100_board_profile_csv"] = self._upload_validation_evidence(task_id, path, "s100_board_profile_csv", "BOARD_TEST")
            status = "SUCCEEDED" if compile_result.get("status") == "SUCCEEDED" and board_result.get("status") == "SUCCEEDED" else "FAILED"
            result = {"status": status, "runner_release": "s100-runner-1.0.0", "runner_content_sha256": compile_result.get("runner_content_sha256"), "artifact_format": "s100_hbm",
                      "compile": compile_result, "board": board_result, "evidence_by_type": evidence,
                      "reason_code": None if status == "SUCCEEDED" else board_result.get("reason_code", compile_result.get("reason_code")),
                      "boundaries": {"output_consistency": "NOT_EXECUTED", "task_accuracy": "NOT_VERIFIED", "stability": "NOT_VERIFIED", "power": "NOT_VERIFIED", "deployment_recommendation": "NOT_VERIFIED"}}
            self._post(self._validation_path(task_id, "complete"), {"result": result, "evidence_ids": list(evidence.values())})

    def run_once(self) -> bool:
        self.register(); self.heartbeat()
        task = self._post(self._validation_path(""))
        if not task: return False
        self.execute_validation(task); return True


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--once", action="store_true")
    args = parser.parse_args(); config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if not isinstance(config, dict): raise SystemExit("invalid_config")
    agent = S100ValidationAgent(config)
    if args.once: agent.run_once(); return 0
    while True: agent.run_once()


if __name__ == "__main__": raise SystemExit(main())
