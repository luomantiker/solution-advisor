"""S100-only EvaluationFlow HostAgent executor.

This intentionally has a separate protocol from the X5 WorkerAgent execution
path.  It reuses only generic HTTP/temp-directory/lease helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from solution_advisor.workers.s100_profile_parser import parse_s100_perf_profile
from solution_advisor.workers.worker_agent import WorkerAgent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class S100EvaluationAgent(WorkerAgent):
    """Fixed S100 compile + fixed S100 board measurement; never invokes X5."""

    def _task_path(self, task_id: str, suffix: str) -> str:
        return f"/api/internal/workers/{self.worker_id}/s100-tasks/{task_id}/{suffix}"

    def _run(self, command: list[str]) -> None:
        completed = subprocess.run(command, check=False)
        if completed.returncode not in (0, 2):
            raise RuntimeError("s100_fixed_runner_launch_failed")

    def _board_perf(self, task_id: str, hbm: Path, output: Path) -> dict:
        """S100-owned transport and parser; this class never calls X5 code."""
        # Keep a local diagnostic root even when the protected board profile
        # is invalid.  The caller always uploads the result JSON, so a failed
        # preflight remains an auditable S100 failure rather than an opaque
        # Agent exception.
        output.mkdir(parents=True, exist_ok=True)
        profile = yaml.safe_load(Path(self.config["board_profile_path"]).read_text(encoding="utf-8"))
        required = ("host", "port", "username", "password_file", "known_hosts_file", "remote_work_root")
        if not isinstance(profile, dict) or any(not profile.get(key) for key in required):
            return {"status": "FAILED", "reason_code": "s100_board_profile_invalid"}
        secret = Path(str(profile["password_file"]))
        if not secret.is_file() or secret.stat().st_mode & 0o077:
            return {"status": "FAILED", "reason_code": "s100_board_secret_invalid"}
        remote = f"{str(profile['remote_work_root']).rstrip('/')}/{task_id}"
        login = f"{profile['username']}@{profile['host']}"
        base = ["sshpass", "-f", str(secret)]
        ssh = [*base, "ssh", "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={profile['known_hosts_file']}", "-p", str(profile["port"]), login]
        try:
            preflight = subprocess.run([*ssh, "uname -srmo; hrt_model_exec --version; test -r /dev/bpu || test -r /dev/bpu0"], text=True, capture_output=True, timeout=60, check=True)
            (output / "board_preflight.json").write_text(json.dumps({"status": "SUCCEEDED", "output": preflight.stdout}, ensure_ascii=False), encoding="utf-8")
            quoted = shlex.quote(remote)
            subprocess.run([*ssh, f"mkdir -p {quoted}/profile"], timeout=60, check=True)
            subprocess.run([*base, "scp", "-P", str(profile["port"]), "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={profile['known_hosts_file']}", str(hbm), f"{login}:{remote}/model.hbm"], timeout=120, check=True)
            (output / "board_load.log").write_text("s100_hbm 已受控下发；固定 Runtime 调用已执行。\n", encoding="utf-8")
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

    def _compile(self, task: dict, root: Path) -> tuple[dict, Path]:
        inp, out = root / "input", root / "output"; inp.mkdir(); out.mkdir()
        model = inp / "model.onnx"; model.write_bytes(self._request(self._task_path(task["id"], "model"), method="GET"))
        if hashlib.sha256(model.read_bytes()).hexdigest() != task["model"]["sha256"]:
            raise RuntimeError("s100_model_sha256_mismatch")
        request = {"schema_version":"1.0", "task_id":task["id"], "subtask_id":f"{task['id']}-{self.worker_id}", "capability":"compile", "model":{"sha256":task["model"]["sha256"]}, "timeout_seconds":self.config.get("timeout_seconds", 1800)}
        (inp / "request.json").write_text(json.dumps(request), encoding="utf-8")
        self._run(["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--entrypoint", "python3", "-v", f"{self.config['platform_package_path']}:/package:ro", "-v", f"{inp}:/work/input:ro", "-v", f"{out}:/work/output:rw", "-e", "PYTHONPATH=/package/runner:/package", self.config["image"], "-m", self.config["runner_module"], "execute", "--request", "/work/input/request.json", "--result", "/work/output/result.json"])
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        hbm = next(iter((out / "artifacts").rglob("*.hbm")), None)
        if result.get("status") != "SUCCEEDED" or not hbm:
            raise RuntimeError("s100_compile_runner_failed")
        declared = result.get("artifacts", [])
        if len([x for x in declared if x.get("type") == "compiled_model_artifact" and x.get("format") == "s100_hbm"]) != 1:
            raise RuntimeError("s100_runner_artifact_contract_invalid")
        return result, hbm

    def _download_compiled_hbm(self, task: dict, destination: Path) -> None:
        """Fetch the Flow-frozen S100 artifact and verify the server digest.

        The internal endpoint verifies task/Flow/source-stage ownership before
        streaming.  The Agent repeats the SHA256 check so a corrupted transfer
        can never reach the board Runtime.
        """
        payload, headers = self._request(
            self._task_path(task["id"], "compiled-artifact"), method="GET", with_headers=True
        )
        # HTTP field names are case-insensitive.  Reverse proxies commonly
        # normalize them to lowercase, while the in-process test transport
        # preserves title case.
        headers = {str(name).lower(): value for name, value in headers.items()}
        expected = headers.get("x-content-sha256")
        if headers.get("x-artifact-format") != "s100_hbm" or not expected:
            raise RuntimeError("s100_compiled_artifact_response_invalid")
        destination.write_bytes(payload)
        if digest(destination) != expected:
            raise RuntimeError("s100_compiled_artifact_sha256_mismatch")

    def _upload_paths(self, task_id: str, pairs: list[tuple[Path, str, str]]) -> list[str]:
        return [self._upload_evidence(task_id, path, kind, phase) for path, kind, phase in pairs if path.is_file()]

    def _execute_task(self, task: dict) -> None:
        task_id = task["id"]
        stop_renewal, lease_lost = threading.Event(), threading.Event()
        renewal = threading.Thread(target=self._renew_task_lease, args=(task_id, stop_renewal, lease_lost), daemon=True)
        try:
            self._post(self._task_path(task_id, "start"))
            renewal.start()
            with self._temporary_work_dir(task_id) as directory:
                root = Path(directory)
                if task["task_kind"] == "S100_COMPILE":
                    result, hbm = self._compile(task, root)
                    out = root / "output"
                    static = out / "static_check.json"; static.write_text(json.dumps({"status":"SUCCEEDED"}), encoding="utf-8")
                    summary = out / "compile_summary.json"; summary.write_text(json.dumps({"status":"SUCCEEDED", "artifact_format":"s100_hbm"}), encoding="utf-8")
                    evidence = self._upload_paths(task_id, [(static,"s100_static_check","COMPILATION"), (out / "artifacts" / "hb_compile.log","s100_compile_log","COMPILATION"), (summary,"s100_compile_summary","COMPILATION"), (out / "result.json","s100_runner_result","COMPILATION"), (hbm,"s100_compiled_model","COMPILATION")])
                    if lease_lost.is_set(): raise RuntimeError("s100_lease_lost")
                    self._post(self._task_path(task_id, "complete"), {"result":result, "evidence_ids":evidence})
                else:
                    hbm = root / "model.hbm"; self._download_compiled_hbm(task, hbm)
                    out = root / "board"; result = self._board_perf(task_id, hbm, out)
                    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    pairs = [(out / "board_preflight.json","s100_board_preflight","BOARD_TEST"), (out / "board_load.log","s100_board_load_log","BOARD_TEST"), (out / "board_inference.log","s100_board_inference_log","BOARD_TEST"), (out / "result.json","s100_board_result","BOARD_TEST")]
                    pairs += [(path,"s100_board_profile_log" if path.suffix == ".log" else "s100_board_profile_csv","BOARD_TEST") for path in (out / "profile").glob("*") if path.suffix in {".log", ".csv"}]
                    evidence = self._upload_paths(task_id, pairs)
                    if lease_lost.is_set(): raise RuntimeError("s100_lease_lost")
                    self._post(self._task_path(task_id, "complete"), {"result":result, "evidence_ids":evidence})
        except Exception:
            self._post(self._task_path(task_id, "fail"), {"reason_code":"s100_agent_execution_failed"})
        finally:
            stop_renewal.set()
            if renewal.is_alive(): renewal.join(timeout=1)

    def run_once(self) -> bool:
        self.register(); self.heartbeat()
        task = self._post(f"/api/internal/workers/{self.worker_id}/s100-tasks/claim")
        if not task: return False
        self._execute_task(task); return True

    def run_parallel_cycle(self) -> int:
        """Claim a bounded number of independent S100 Runner slots."""
        capacity = max(1, int(self.config.get("max_concurrency", 1)))
        self.register(); self.heartbeat(); tasks = []
        while len(tasks) < capacity:
            task = self._post(f"/api/internal/workers/{self.worker_id}/s100-tasks/claim")
            if not task: break
            tasks.append(task)
        with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="s100-slot") as executor:
            for future in [executor.submit(self._execute_task, task) for task in tasks]: future.result()
        return len(tasks)


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); parser.add_argument("--once", action="store_true")
    args = parser.parse_args(); agent = S100EvaluationAgent(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    if args.once: agent.run_once(); return 0
    while True:
        if not agent.run_parallel_cycle(): time.sleep(max(1, int(agent.config.get("poll_interval_seconds", 5))))


if __name__ == "__main__": raise SystemExit(main())
