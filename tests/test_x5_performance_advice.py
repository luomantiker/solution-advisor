from solution_advisor.evaluations.x5_performance_advice import build_x5_performance_advice


def test_advice_distinguishes_runtime_cpu_from_model_cpu_fallback():
    result = build_x5_performance_advice({"status": "MEASURED", "metrics": {"fps": 1, "average_latency_ms": 2},
        "running_condition": {"thread_num": 1, "frame_count": 200}, "segments": [{"name": "BPU", "average_ms": 1}],
        "cpu_execution_segment_present": True, "model_cpu_operator_assessment": {"compile_allocation_cpu_operators": []}})
    assert result["version"] == "x5-performance-advice-1.0"
    assert any(item["code"] == "RUNTIME_CPU_STAGE" for item in result["items"])


def test_advice_requires_evidence_for_unmeasured_result():
    assert build_x5_performance_advice({"status": "NOT_COLLECTED"})["items"][0]["code"] == "PROFILE_EVIDENCE_REQUIRED"
