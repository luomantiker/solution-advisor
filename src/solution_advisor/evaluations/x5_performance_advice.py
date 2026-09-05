"""Evidence-bound guidance for X5 performance comparison, not deployment advice."""
from __future__ import annotations

ADVICE_VERSION = "x5-performance-advice-1.0"


def build_x5_performance_advice(performance: dict) -> dict:
    """Turn already parsed facts into conservative, customer-readable next steps."""
    status = performance.get("status")
    items: list[dict[str, str]] = []
    if status != "MEASURED":
        items.append({"code": "PROFILE_EVIDENCE_REQUIRED", "level": "ACTION",
                      "message": "尚无可解析的板端 profile Evidence；请重新执行标准性能预设后再比较。"})
    else:
        condition = performance.get("running_condition") or {}
        metrics = performance.get("metrics") or {}
        items.append({"code": "COMPARE_SAME_CONDITION", "level": "ACTION",
                      "message": f"横向比较须保持 core_id、线程数、帧数和模型版本一致；本次线程={condition.get('thread_num', 'NOT_COLLECTED')}、帧数={condition.get('frame_count', 'NOT_COLLECTED')}。"})
        if metrics.get("fps") is None or metrics.get("average_latency_ms") is None:
            items.append({"code": "INCOMPLETE_METRICS", "level": "RISK",
                          "message": "profile 未同时提供 FPS 与平均延迟，不能据此形成性能基线。"})
        if performance.get("cpu_execution_segment_present"):
            cpu = performance.get("model_cpu_operator_assessment") or {}
            allocation = cpu.get("compile_allocation_cpu_operators") or []
            if allocation:
                items.append({"code": "MODEL_CPU_OPERATOR", "level": "ACTION",
                              "message": "编译分配记录存在模型 CPU 算子；优先检查该算子的替代实现、图改写或模型导出方式。"})
            else:
                items.append({"code": "RUNTIME_CPU_STAGE", "level": "INFO",
                              "message": "profile 有 Runtime CPU 执行段，但编译分配未发现模型 CPU 算子；先分析预处理、调度和数据搬运，勿将其表述为模型 CPU 回退。"})
        if not performance.get("segments"):
            items.append({"code": "SEGMENT_DETAIL_MISSING", "level": "RISK",
                          "message": "缺少模型分段耗时，建议保留完整 profile 原始 Evidence 后重新解析。"})
    return {"version": ADVICE_VERSION, "scope": "仅针对本次固定 hrt_model_exec perf 条件的性能优化下一步，不验证精度、稳定性、功耗或部署推荐。", "items": items}
