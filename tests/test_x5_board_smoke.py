from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from solution_advisor.workers.x5_board_smoke import X5BoardSmokeRunner
from solution_advisor.workers.x5_profile_parser import parse_x5_perf_profile


def profile(tmp_path: Path) -> Path:
    password = tmp_path / "password"
    password.write_text("test-password", encoding="utf-8")
    password.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("board key", encoding="utf-8")
    path = tmp_path / "board.yaml"
    path.write_text("\n".join([
        "host: board.example", "port: 22", "username: worker", f"password_file: {password}",
        f"known_hosts_file: {known_hosts}", "remote_work_root: /tmp/solution-advisor/x5-a", "",
    ]), encoding="utf-8")
    return path


def test_board_smoke_success_parses_profile_without_claiming_accuracy_or_power(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model.bin"; model.write_bytes(b"compiled")
    runner = X5BoardSmokeRunner(profile(tmp_path))

    def ssh(command: str, *, check: bool = True):
        if command.startswith("hrt_model_exec perf"):
            return SimpleNamespace(returncode=0, stdout="raw runtime profile content", stderr="")
        return SimpleNamespace(returncode=0, stdout="version-or-preflight", stderr="")

    monkeypatch.setattr(runner, "_ssh", ssh)
    monkeypatch.setattr(runner, "_scp_to", lambda source, remote: None)
    def copied(remote: str, target: Path) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / "profile.json").write_text('''{"perf_result":{"FPS":12.5,"average_latency":8.0},"running_condition":{"thread_num":1,"frame_count":200,"run_time":99.0}}\n***\n{"model_latency":{"BPU_graph":{"avg_time":7.0,"min_time":6.0,"max_time":8.0}},"processor_latency":{"CPU_inference_time_cost":{"avg_time":1.0}}}''', encoding="utf-8")
    monkeypatch.setattr(runner, "_scp_from", copied)

    result = runner.run(task_id="task_" + "a" * 32, model_bin=model, output_root=tmp_path / "out")

    assert result["status"] == "SUCCEEDED"
    assert result["single_runtime_invocation"] == "SUCCEEDED"
    assert result["boundaries"]["performance"] == "MEASURED"
    assert result["performance"]["metrics"]["fps"] == 12.5
    assert result["performance"]["cpu_execution_segment_present"] is True
    assert result["extensions"]["accuracy"]["status"] == "NOT_VERIFIED"
    assert (tmp_path / "out" / "board_inference.log").read_text(encoding="utf-8") == "raw runtime profile content"


def test_profile_parser_keeps_cpu_timing_distinct_from_model_cpu_operators(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"; profile_dir.mkdir()
    # Runtime 1.24.x writes these JSON fragments to profiler.log.
    (profile_dir / "profiler.log").write_text('''{"perf_result":{"FPS":2985.5,"average_latency":0.326},"running_condition":{"model_name":"model","core_id":0,"thread_num":1,"frame_count":200,"run_time":66.989}}\n***\n{"model_latency":{"BPU_x5_conv_relu_linear_subgraph_0":{"avg_time":0.249425,"min_time":0.198,"max_time":1.071},"Preprocess":{"avg_time":0.006825,"min_time":0.005,"max_time":0.022}},"processor_latency":{"BPU_inference_time_cost":{"avg_time":0.249425},"CPU_inference_time_cost":{"avg_time":0.006825}}}''', encoding="utf-8")
    parsed = parse_x5_perf_profile(profile_dir)
    assert parsed["status"] == "MEASURED"
    assert parsed["metrics"] == {"fps": 2985.5, "average_latency_ms": 0.326}
    assert parsed["segments"][0]["processor"] == "BPU"
    assert parsed["cpu_execution_segment_present"] is True
    assert parsed["model_cpu_operator_assessment"]["status"] == "REQUIRES_COMPILE_ALLOCATION"


def test_board_smoke_runtime_failure_keeps_stderr_as_evidence(tmp_path: Path, monkeypatch) -> None:
    model = tmp_path / "model.bin"; model.write_bytes(b"compiled")
    runner = X5BoardSmokeRunner(profile(tmp_path))

    def ssh(command: str, *, check: bool = True):
        if command.startswith("hrt_model_exec perf"):
            return SimpleNamespace(returncode=1, stdout="", stderr="fixed runtime error")
        return SimpleNamespace(returncode=0, stdout="preflight", stderr="")

    monkeypatch.setattr(runner, "_ssh", ssh)
    monkeypatch.setattr(runner, "_scp_to", lambda source, remote: None)

    result = runner.run(task_id="task_" + "b" * 32, model_bin=model, output_root=tmp_path / "out")

    assert result["status"] == "FAILED"
    assert result["reason_code"] == "board_runtime_failed"
    assert (tmp_path / "out" / "board_inference.log").read_text(encoding="utf-8") == "fixed runtime error"
