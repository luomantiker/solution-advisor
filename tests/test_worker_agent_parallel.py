import threading
import time
import json
from pathlib import Path

from solution_advisor.workers.worker_agent import WorkerAgent


def test_parallel_cycle_claims_and_executes_each_slot_concurrently() -> None:
    agent = WorkerAgent({"instance_id": "parallel-test", "max_concurrency": 3})
    pending = [{"id": f"task_{index}"} for index in range(3)]
    active = 0
    peak = 0
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    agent.register = lambda: None
    agent.heartbeat = lambda: None

    def post(path: str, payload=None):
        if path.endswith("/claim"):
            return pending.pop(0) if pending else None
        return None

    def execute(task: dict) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 3:
                entered.set()
        assert entered.wait(1)
        release.wait(1)
        with lock:
            active -= 1

    agent._post = post
    agent._execute_task = execute
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(agent.run_parallel_cycle()))
    thread.start()
    assert entered.wait(1)
    # All three slots are executing before any one is allowed to complete.
    assert peak == 3
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert result == [3]


def test_worker_agent_registers_filtered_discovery_and_completes_fixed_compile(tmp_path: Path, monkeypatch) -> None:
    token = tmp_path / "token"; token.write_text("worker-token", encoding="utf-8")
    agent = WorkerAgent({
        "instance_id": "controlled-x5", "registration_token_file": str(token),
        "control_plane_url": "http://control-plane", "max_concurrency": 1,
        "worker_type": "x5", "platform_package_version": "1.2.8",
        "capabilities": ["static_check", "compile", "board_smoke"],
        "platform_package_path": "/package", "image": "x5-toolchain:test", "runner_module": "runner",
        "evidence_types": {"compiled_model": "x5_compiled_model", "compile_log": "x5_compile_log",
                           "static_check": "x5_static_check", "compile_summary": "x5_compile_summary",
                           "runner_result": "x5_runner_result", "board_preflight": "x5_board_preflight",
                           "board_load_log": "x5_board_load_log", "board_inference_log": "x5_board_inference_log",
                           "board_result": "x5_board_result"},
        "discovery_images": [
            {"image_ref": "solution-advisor-api:test", "image_id": "ignored"},
            {"image_ref": "vendor/x5:1.2.8", "image_id": "sha256:x5"},
        ],
    })
    calls = []
    agent._post = lambda path, payload=None: calls.append((path, payload)) or {"id": "ok"}
    agent.register()
    registration = next(payload for path, payload in calls if path.endswith("/register"))
    assert registration["image_ref"] == "vendor/x5:1.2.8"
    assert [row["image_ref"] for row in registration["candidates"]] == ["vendor/x5:1.2.8"]

    def request(path, *, method="POST", **kwargs):
        assert method == "GET" and path.endswith("/model")
        return b"controlled-onnx"

    def runner(command, lease_lost):
        output_mount = next(value for index, value in enumerate(command) if command[index - 1] == "-v" and value.endswith(":/work/output:rw"))
        output = Path(output_mount.split(":/work/output:rw", 1)[0])
        (output / "nested").mkdir(parents=True)
        (output / "result.json").write_text(json.dumps({"status": "SUCCEEDED"}), encoding="utf-8")
        (output / "nested" / "compile.log").write_text("fixed compile", encoding="utf-8")
        (output / "nested" / "model.bin").write_bytes(b"compiled")
        return 0

    uploads = []
    agent._request = request
    agent._run_runner = runner
    agent._upload_evidence = lambda task_id, path, kind, phase: uploads.append((path.name, kind, phase)) or f"e-{path.name}"
    agent._execute_task({"id": "compile", "task_kind": "X5_COMPILE", "model": {"sha256": "a" * 64},
                         "model_profile": "profile", "platform": "X5"})
    complete = next(payload for path, payload in calls if path.endswith("/complete"))
    assert complete["result"]["status"] == "SUCCEEDED"
    assert {kind for _, kind, _ in uploads} >= {"x5_runner_result", "x5_compile_log", "x5_compiled_model"}


def test_worker_agent_reports_stable_failure_without_sensitive_error(tmp_path: Path, capsys) -> None:
    agent = WorkerAgent({"instance_id": "controlled-x5", "max_concurrency": 1})
    calls = []
    agent._post = lambda path, payload=None: calls.append((path, payload)) or None
    agent._request = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("private transport detail"))
    agent._execute_task({"id": "compile", "task_kind": "X5_COMPILE", "model": {"sha256": "a" * 64}})
    assert any(path.endswith("/x5-tasks/compile/fail") and payload == {"reason_code": "agent_execution_failed"}
               for path, payload in calls)
    assert "private transport detail" not in capsys.readouterr().out
