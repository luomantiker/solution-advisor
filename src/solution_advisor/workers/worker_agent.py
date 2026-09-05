"""Platform-neutral HostAgent.

The HostAgent has no database, object-store or platform-toolchain dependency.  It
uses a Worker Token against the control-plane internal API; platform details
remain in the instance configuration and Platform Package.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yaml
from solution_advisor.platforms.service import is_governance_service_image


class WorkerAgent:
    def __init__(self, config: dict):
        self.config = config

    @property
    def worker_id(self) -> str:
        return self.config["instance_id"]

    def _token(self) -> str:
        return Path(self.config["registration_token_file"]).read_text(encoding="utf-8").strip()

    def _request(self, path: str, *, method: str = "POST", payload: dict | None = None,
                 data: bytes | None = None, content_type: str = "application/json", with_headers: bool = False):
        request = Request(self.config["control_plane_url"].rstrip("/") + path, data=data if data is not None else (
            json.dumps(payload or {}).encode() if method != "GET" else None), method=method,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": content_type})
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                if response.status == 204:
                    return None
                if with_headers:
                    # Generic transport helper used by platform-specific
                    # Agents for integrity headers; never exposes request
                    # headers or credentials.
                    return body, dict(response.headers.items())
                return body if "application/json" not in response.headers.get("Content-Type", "") else json.loads(body)
        except HTTPError as exc:
            # Only surface the stable control-plane code, never headers, URL,
            # request body, Token or board connection data.
            try:
                detail = json.loads(exc.read()).get("detail", {})
                code = detail.get("code", "http_error") if isinstance(detail, dict) else "http_error"
            except Exception:
                code = "http_error"
            raise RuntimeError(f"control_plane_{exc.code}_{code}") from exc

    def _post(self, path: str, payload: dict | None = None):
        return self._request(path, payload=payload)

    def register(self):
        # Discovery is deliberately read-only metadata.  It has no platform_id,
        # cannot create a Binding, and cannot cause a Runner to start.
        candidates = self._discover_images()
        primary = candidates[0] if candidates else {"image_ref": "host-agent:unknown", "image_id": "unknown", "toolchain_version": "NOT_COLLECTED", "evidence": {}}
        self._post("/api/internal/workers/register", {
            "instance_id": self.worker_id, "worker_type": self.config.get("worker_type", "host-agent"),
            "image_ref": primary["image_ref"], "image_id": primary["image_id"],
            "toolchain_version": primary["toolchain_version"],
            "platform_package_version": self.config.get("platform_package_version", "discovery-only"),
            "capabilities": self.config["capabilities"], "max_concurrency": self.config["max_concurrency"],
            "agent_version": "host-agent-1.1", "candidates": candidates,
        })

    def _discover_images(self) -> list[dict]:
        """Read-only Docker discovery; config may restrict the visible image list."""
        configured = self.config.get("discovery_images", [])
        if configured:
            return [{"image_ref": x["image_ref"], "image_id": x["image_id"],
                     "toolchain_version": x.get("toolchain_version", "NOT_COLLECTED"),
                     "evidence": {"source": "hostagent_configured_discovery"}}
                    for x in configured if not is_governance_service_image(x["image_ref"])]
        try:
            result = subprocess.run(["docker", "image", "ls", "--no-trunc", "--format", "{{.Repository}}:{{.Tag}}|{{.ID}}"], capture_output=True, text=True, check=True)
            return [{"image_ref": row.split("|", 1)[0], "image_id": row.split("|", 1)[1],
                     "toolchain_version": "NOT_COLLECTED", "evidence": {"source": "hostagent_docker_read_only"}}
                    for row in result.stdout.splitlines() if "|" in row
                    and not is_governance_service_image(row.split("|", 1)[0])]
        except (OSError, subprocess.SubprocessError):
            return []

    def heartbeat(self):
        self._post(f"/api/internal/workers/{self.worker_id}/heartbeat")

    def _task_path(self, task_id: str, suffix: str) -> str:
        return f"/api/internal/workers/{self.worker_id}/x5-tasks/{task_id}/{suffix}"

    def _upload_evidence(self, task_id: str, path: Path, evidence_type: str, phase: str) -> str:
        boundary = "----solutionadvisorworker"
        fields = [("evidence_type", evidence_type), ("phase", phase)]
        body = bytearray()
        for name, value in fields:
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())
        result = self._request(self._task_path(task_id, "evidence"), data=bytes(body),
                               content_type=f"multipart/form-data; boundary={boundary}")
        return result["id"]

    def _run_runner(self, command: list[str], lease_lost: threading.Event):
        process = subprocess.Popen(command)
        while process.poll() is None:
            if lease_lost.is_set():
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            time.sleep(0.2)
        return process.returncode

    def _renew_task_lease(self, task_id: str, stop: threading.Event, lease_lost: threading.Event) -> None:
        """Renew one task independently while other slots are executing.

        A failed renewal is treated as lease loss.  Compile containers are then
        terminated by their owning slot, rather than continuing after a cancel,
        timeout or control-plane recovery has reclaimed the slot.
        """
        interval = max(1, int(self.config.get("heartbeat_interval_seconds", 15)))
        while not stop.wait(interval):
            try:
                self.heartbeat()
                self._post(self._task_path(task_id, "heartbeat"))
            except RuntimeError:
                lease_lost.set()
                return

    def _evidence_kind(self, path: Path, task_kind: str) -> tuple[str, str]:
        kinds = self.config["evidence_types"]
        if task_kind == "REAL_BOARD_SMOKE":
            if path.name == "board_preflight.json":
                return kinds["board_preflight"], "BOARD_TEST"
            if path.name == "board_load.log":
                return kinds["board_load_log"], "BOARD_TEST"
            if path.name == "board_inference.log":
                return kinds["board_inference_log"], "BOARD_TEST"
            if path.name == "result.json":
                return kinds["board_result"], "BOARD_TEST"
            return "BOARD_LOG", "BOARD_TEST"
        if path.suffix == ".bin":
            return kinds["compiled_model"], "COMPILATION"
        if path.suffix == ".log":
            return kinds["compile_log"], "COMPILATION"
        if path.name == "static_check.json":
            return kinds["static_check"], "STATIC_CHECK"
        if path.name == "compile_summary.json":
            return kinds["compile_summary"], "COMPILATION"
        return kinds["runner_result"], "COMPILATION"

    def _temporary_work_dir(self, task_id: str):
        """Create Runner input outside systemd PrivateTmp when a Host root is configured.

        The Docker daemon cannot see a service's private ``/tmp`` mount.  The
        configured directory is an Agent-owned local fact, never supplied by a
        browser or task payload, and is mounted only into the fixed Runner.
        """
        root = self.config.get("work_root")
        if root:
            location = Path(root)
            location.mkdir(parents=True, exist_ok=True)
            return tempfile.TemporaryDirectory(prefix=f"worker-{task_id}-", dir=location)
        return tempfile.TemporaryDirectory(prefix=f"worker-{task_id}-")

    def _execute_task(self, task: dict) -> None:
        task_id = task["id"]
        stop_renewal, lease_lost = threading.Event(), threading.Event()
        renewal = threading.Thread(target=self._renew_task_lease, args=(task_id, stop_renewal, lease_lost), daemon=True)
        try:
            self._post(self._task_path(task_id, "start"))
            renewal.start()
            with self._temporary_work_dir(task_id) as directory:
                root = Path(directory); inp = root / "input"; out = root / "output"; inp.mkdir(); out.mkdir()
                if task.get("task_kind") == "REAL_BOARD_SMOKE":
                    from solution_advisor.workers.x5_board_smoke import X5BoardSmokeRunner
                    compiled = self._request(self._task_path(task_id, "compiled-model"), method="GET")
                    model_bin = inp / "model.bin"; model_bin.write_bytes(compiled)
                    result = X5BoardSmokeRunner(Path(self.config["board_profile_path"])).run(
                        task_id=task_id, model_bin=model_bin, output_root=out)
                else:
                    model = self._request(self._task_path(task_id, "model"), method="GET")
                    (inp / "model.onnx").write_bytes(model)
                    request = {"schema_version": "1.0", "task_id": task_id,
                        "subtask_id": f"{task_id}-{self.worker_id}", "capability": "compile",
                        "model": {"sha256": task["model"]["sha256"]},
                        "model_profile_ref": task["model_profile"],
                        "platform_package": task["platform"],
                        "timeout_seconds": self.config.get("timeout_seconds", 900)}
                    (inp / "request.json").write_text(json.dumps(request), encoding="utf-8")
                    self._run_runner(["docker", "run", "--rm", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--entrypoint", "python3", "-v", f"{self.config['platform_package_path']}:/package:ro", "-v", f"{inp}:/work/input:ro", "-v", f"{out}:/work/output:rw", "-e", "PYTHONPATH=/package/runner:/package", self.config["image"], "-m", self.config["runner_module"], "execute", "--request", "/work/input/request.json", "--result", "/work/output/result.json"], lease_lost)
                    if lease_lost.is_set():
                        raise RuntimeError("task_lease_lost")
                    result = json.loads((out / "result.json").read_text(encoding="utf-8"))
                evidence_ids = []
                evidence_paths = [out / "result.json", out / "board_preflight.json", *out.rglob("*.log"), *out.rglob("profile/**/*"),
                                  *out.rglob("static_check.json"), *out.rglob("compile_summary.json"), *out.rglob("*.bin")]
                seen_paths: set[Path] = set()
                for path in evidence_paths:
                    if not path.is_file():
                        continue
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    try:
                        evidence_ids.append(self._upload_evidence(
                            task_id, path, *self._evidence_kind(path, task.get("task_kind", "X5_COMPILE"))
                        ))
                    except RuntimeError as exc:
                        # Finish with the actual Runner state even when an
                        # optional evidence upload is rejected.  Only the
                        # stable control-plane code is retained.
                        result.setdefault("evidence_upload_errors", []).append(str(exc))
                self._post(self._task_path(task_id, "complete"), {"result": result, "evidence_ids": evidence_ids})
        except Exception as exc:
            # Keep HostAgent diagnostics non-sensitive: no URL, command, Token,
            # board profile or remote stderr is emitted.
            print(f"任务 {task_id} 执行未完成：{type(exc).__name__}")
            self._post(self._task_path(task_id, "fail"), {"reason_code": "agent_execution_failed"})
        finally:
            stop_renewal.set()
            if renewal.is_alive():
                renewal.join(timeout=1)

    def run_once(self) -> bool:
        self.register()
        self.heartbeat()
        task = self._post(f"/api/internal/workers/{self.worker_id}/x5-tasks/claim")
        if task is None:
            return False
        self._execute_task(task)
        return True

    def run_parallel_cycle(self) -> int:
        """Claim and execute one bounded batch for capacity verification.

        Normal service operation uses :meth:`run_forever`.  Keeping this
        finite operation also makes the slot boundary testable without a
        long-running daemon or real containers.
        """
        capacity = max(1, int(self.config.get("max_concurrency", 1)))
        self.register()
        self.heartbeat()
        tasks: list[dict] = []
        while len(tasks) < capacity:
            task = self._post(f"/api/internal/workers/{self.worker_id}/x5-tasks/claim")
            if task is None:
                break
            tasks.append(task)
        with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="solution-advisor-slot") as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            for future in futures:
                future.result()
        return len(tasks)

    def run_forever(self) -> None:
        """Keep up to the configured number of isolated Runner slots active."""
        capacity = max(1, int(self.config.get("max_concurrency", 1)))
        heartbeat_interval = max(1, int(self.config.get("heartbeat_interval_seconds", 15)))
        active: dict[Future, str] = {}
        next_registration = 0.0
        with ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="solution-advisor-slot") as executor:
            while True:
                now = time.monotonic()
                if now >= next_registration:
                    self.register()
                    self.heartbeat()
                    next_registration = now + heartbeat_interval
                for future in [item for item in active if item.done()]:
                    active.pop(future, None)
                    try:
                        future.result()
                    except Exception:
                        # Slot failures are reported by _execute_task; keep the
                        # Agent available for other isolated slots.
                        pass
                while len(active) < capacity:
                    task = self._post(f"/api/internal/workers/{self.worker_id}/x5-tasks/claim")
                    if task is None:
                        break
                    active[executor.submit(self._execute_task, task)] = task["id"]
                time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    agent = WorkerAgent(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))
    if args.once:
        agent.run_once()
        return
    agent.run_forever()


if __name__ == "__main__":
    main()
