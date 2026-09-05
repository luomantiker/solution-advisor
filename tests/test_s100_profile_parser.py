from solution_advisor.workers.s100_profile_parser import PARSER_VERSION, parse_s100_perf_profile


def test_s100_parser_is_independent_and_extracts_runtime_metrics(tmp_path):
    (tmp_path / "profiler.log").write_text("Thread Average: 0.328 ms, FPS: 2775.003\n")
    value = parse_s100_perf_profile(tmp_path)
    assert value["parser"] == PARSER_VERSION
    assert value["status"] == "MEASURED"
    assert value["average_latency_ms"] == 0.328
    assert value["fps"] == 2775.003
