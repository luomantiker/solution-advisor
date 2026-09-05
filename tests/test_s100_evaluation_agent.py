"""Unit coverage for the S100-only Flow HostAgent orchestration."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from solution_advisor.workers.s100_evaluation_agent import S100EvaluationAgent


def agent(tmp_path: Path) -> S100EvaluationAgent:
    token = tmp_path / "token"; token.write_text("test-token", encoding="utf-8")
    return S100EvaluationAgent({
        "instance_id": "s100-agent", "registration_token_file": str(token),
        "control_plane_url": "http://control-plane", "work_root": str(tmp_path / "work"),
        "platform_package_path": "/package", "image": "s100-toolchain:test",
        "runner_module": "platform_runner", "capabilities": ["compile", "board_smoke"],
        "max_concurrency": 1,
    })


def test_download_compiled_hbm_rechecks_response_digest(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path); payload = b"s100-hbm"; target = tmp_path / "model.hbm"
    monkeypatch.setattr(subject, "_request", lambda *args, **kwargs: (payload, {
        "X-Content-Sha256": hashlib.sha256(payload).hexdigest(), "X-Artifact-Format": "s100_hbm"}))
    subject._download_compiled_hbm({"id": "board"}, target)
    assert target.read_bytes() == payload

    monkeypatch.setattr(subject, "_request", lambda *args, **kwargs: (payload, {
        "X-Content-Sha256": "0" * 64, "X-Artifact-Format": "s100_hbm"}))
    with pytest.raises(RuntimeError, match="sha256"):
        subject._download_compiled_hbm({"id": "board"}, target)

    monkeypatch.setattr(subject, "_request", lambda *args, **kwargs: (payload, {
        "x-content-sha256": hashlib.sha256(payload).hexdigest(), "x-artifact-format": "s100_hbm"}))
    subject._download_compiled_hbm({"id": "board"}, target)


def test_compile_stage_uploads_only_s100_evidence_and_completes(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path); hbm = tmp_path / "nested" / "model.hbm"; hbm.parent.mkdir(); hbm.write_bytes(b"hbm")
    result = {"status": "SUCCEEDED", "artifacts": [{"type": "compiled_model_artifact", "format": "s100_hbm", "filename": "nested/model.hbm", "sha256": hashlib.sha256(b"hbm").hexdigest(), "size_bytes": 3}]}
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(subject, "_post", lambda path, payload=None: calls.append((path, payload)) or {"id": "ok"})
    def compile_result(task, root):
        (root / "output" / "artifacts").mkdir(parents=True)
        return result, hbm
    monkeypatch.setattr(subject, "_compile", compile_result)
    monkeypatch.setattr(subject, "_upload_paths", lambda task_id, pairs: [f"e-{kind}" for _, kind, _ in pairs])
    subject._execute_task({"id": "compile", "task_kind": "S100_COMPILE", "model": {"sha256": "a"}})
    complete = [payload for path, payload in calls if path.endswith("/complete")]
    assert len(complete) == 1
    assert complete[0]["result"] == result
    assert all(item.startswith("e-s100_") for item in complete[0]["evidence_ids"])


def test_board_stage_uses_downloaded_s100_hbm_and_s100_evidence(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path); calls: list[tuple[str, object]] = []
    def download(task, target): target.write_bytes(b"hbm")
    monkeypatch.setattr(subject, "_download_compiled_hbm", download)
    def board_result(task_id, hbm, out):
        out.mkdir(parents=True)
        return {"status": "SUCCEEDED", "performance": {"status": "MEASURED"}}
    monkeypatch.setattr(subject, "_board_perf", board_result)
    monkeypatch.setattr(subject, "_upload_paths", lambda task_id, pairs: [f"e-{kind}" for _, kind, _ in pairs])
    monkeypatch.setattr(subject, "_post", lambda path, payload=None: calls.append((path, payload)) or {"id": "ok"})
    subject._execute_task({"id": "board", "task_kind": "S100_BOARD_PERF"})
    complete = [payload for path, payload in calls if path.endswith("/complete")]
    assert len(complete) == 1
    assert all(item.startswith("e-s100_board_") for item in complete[0]["evidence_ids"])


def test_board_preflight_failure_still_creates_a_diagnostic_root(tmp_path: Path) -> None:
    subject = agent(tmp_path)
    profile = tmp_path / "invalid-board.yaml"
    profile.write_text("host: ''\n", encoding="utf-8")
    subject.config["board_profile_path"] = str(profile)

    output = tmp_path / "board"
    result = subject._board_perf("board", tmp_path / "model.hbm", output)

    assert output.is_dir()
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "s100_board_profile_invalid"


def test_agent_failure_reports_stable_code_and_run_once_claims(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path); calls: list[tuple[str, object]] = []
    monkeypatch.setattr(subject, "register", lambda: calls.append(("register", None)))
    monkeypatch.setattr(subject, "heartbeat", lambda: calls.append(("heartbeat", None)))
    monkeypatch.setattr(subject, "_post", lambda path, payload=None: {"id": "compile", "task_kind": "S100_COMPILE", "model": {"sha256": "x"}} if path.endswith("/claim") else calls.append((path, payload)))
    monkeypatch.setattr(subject, "_compile", lambda task, root: (_ for _ in ()).throw(RuntimeError("broken")))
    assert subject.run_once() is True
    assert any(path.endswith("/fail") and payload == {"reason_code": "s100_agent_execution_failed"} for path, payload in calls if isinstance(path, str))


def test_compile_uses_fixed_runner_and_recursively_returns_declared_hbm(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path)
    model = b"controlled-onnx"
    monkeypatch.setattr(subject, "_request", lambda *args, **kwargs: model)
    commands = []

    def fixed_runner(command):
        commands.append(command)
        result_path = Path(command[-1].replace("/work/output", str(root / "output")))
        result_path.parent.mkdir(parents=True, exist_ok=True)
        hbm = root / "output" / "artifacts" / "nested" / "model.hbm"
        hbm.parent.mkdir(parents=True, exist_ok=True)
        hbm.write_bytes(b"compiled-hbm")
        result_path.write_text(json.dumps({
            "status": "SUCCEEDED",
            "artifacts": [{"type": "compiled_model_artifact", "format": "s100_hbm",
                           "filename": "artifacts/nested/model.hbm", "sha256": hashlib.sha256(b"compiled-hbm").hexdigest(),
                           "size_bytes": len(b"compiled-hbm")}],
        }), encoding="utf-8")

    root = tmp_path / "compile-root"
    root.mkdir()
    monkeypatch.setattr(subject, "_run", fixed_runner)
    result, hbm = subject._compile({"id": "compile", "model": {"sha256": hashlib.sha256(model).hexdigest()}}, root)
    assert result["status"] == "SUCCEEDED" and hbm.name == "model.hbm"
    assert commands and commands[0][:3] == ["docker", "run", "--rm"]
    assert "--network" in commands[0] and "none" in commands[0]


def test_compile_refuses_corrupt_model_before_running_runner(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path)
    monkeypatch.setattr(subject, "_request", lambda *args, **kwargs: b"wrong-model")
    monkeypatch.setattr(subject, "_run", lambda command: (_ for _ in ()).throw(AssertionError("must not run")))
    root = tmp_path / "root"; root.mkdir()
    with pytest.raises(RuntimeError, match="sha256"):
        subject._compile({"id": "compile", "model": {"sha256": "0" * 64}}, root)


def test_board_perf_uses_protected_profile_and_returns_measured_s100_result(tmp_path: Path, monkeypatch) -> None:
    subject = agent(tmp_path)
    password = tmp_path / "board.password"; password.write_text("private", encoding="utf-8"); os.chmod(password, 0o600)
    known_hosts = tmp_path / "known_hosts"; known_hosts.write_text("board-key", encoding="utf-8")
    profile = tmp_path / "board.yaml"
    profile.write_text("\n".join((
        "host: protected-board", "port: 22", "username: worker", f"password_file: {password}",
        f"known_hosts_file: {known_hosts}", "remote_work_root: /controlled/work",
    )), encoding="utf-8")
    subject.config["board_profile_path"] = str(profile)
    calls = []

    def controlled_run(command, **kwargs):
        calls.append(command)
        if "-r" in command:
            destination = Path(command[-1]); destination.mkdir(parents=True, exist_ok=True)
            (destination / "profiler.log").write_text("Thread Average: 0.5 ms, FPS: 2000\n", encoding="utf-8")
        if "hrt_model_exec perf" in " ".join(command):
            return subprocess.CompletedProcess(command, 0, stdout="Thread Average: 0.5 ms, FPS: 2000\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="Linux test\n", stderr="")

    monkeypatch.setattr(subprocess, "run", controlled_run)
    hbm = tmp_path / "model.hbm"; hbm.write_bytes(b"hbm")
    result = subject._board_perf("board-task", hbm, tmp_path / "output")
    assert result["status"] == "SUCCEEDED"
    assert result["performance"]["parser"] == "s100-hrt-profile-1.0"
    assert result["performance"]["fps"] == 2000.0
    assert any("hrt_model_exec perf" in " ".join(command) for command in calls)
