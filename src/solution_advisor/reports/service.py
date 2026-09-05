from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from solution_advisor.evaluations.service import DemoEvaluationService
from solution_advisor.model_assets.domain import ModelProfile
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationResult, EvaluationTask, TaskSnapshot
from sqlalchemy.orm import Session

MOCK_NOTICE = "Mock / 不可用于交付结论"

_STATUS_LABELS = {
    "SUCCEEDED": "成功", "FAILED": "失败", "QUEUED": "等待执行", "CLAIMED": "已分配执行器",
    "RUNNING": "执行中", "CANCELLED": "已取消", "TIMEOUT": "执行超时", "READY": "就绪",
    "MEASURED": "已测量", "BOARD_MEASURED": "板端实测", "NOT_EXECUTED": "未执行",
    "NOT_VERIFIED": "未验证", "NOT_COLLECTED": "未采集", "NOT_SEPARABLE_BY_RUNTIME_COMMAND": "无法由 Runtime 命令单独区分",
}
_BOARD_STAGE_REASONS = {
    "compiled_model_artifact_not_found": "编译制品证据不完整，无法进入板端性能阶段",
    "x5_board_not_schedulable_READY": "X5 Worker 未声明板端性能能力，无法进入板端性能阶段",
    "board_runtime_failed": "固定 Runtime 执行失败，请查看板端原始日志",
    "board_connection_or_preflight_failed": "板端连接或预检失败，请查看预检证据",
    "cancelled_by_admin": "管理员已取消该板端性能阶段",
}


def status_label(value: object) -> str:
    return _STATUS_LABELS.get(str(value), str(value))


def report_view_model(session: Session, task_id: str) -> dict | None:
    tasks = DemoEvaluationService(session)
    task = tasks.get(task_id)
    if task is None:
        return None
    profile = session.get(ModelProfile, task.model_profile_id)
    results = tasks.results(task.id)
    if task.mode == "REAL":
        x5 = results[0].platform_result if results else {}
        snapshot = session.get(TaskSnapshot, task.snapshot_id) if task.snapshot_id else None
        governance = snapshot.platform_governance if snapshot else {}
        if task.task_kind == "REAL_BOARD_SMOKE":
            return {"task_id": task.id, "mode": "REAL", "task_kind": "REAL_BOARD_SMOKE",
                    "notice": "X5 板端标准性能预设（固定 hrt_model_exec perf）记录；profile 可给出本次运行的性能测量值和证据约束建议。精度、稳定性、功耗和推荐部署均未验证。",
                    "sections": {"onnx_model_profile": profile.analysis["summary"],
                    "x5_board_smoke": x5, "platform_governance": governance}}
        board_task = session.query(EvaluationTask).filter_by(source_task_id=task.id, task_kind="REAL_BOARD_SMOKE").order_by(EvaluationTask.created_at.desc()).first()
        recorded_stage = x5.get("board_stage", {})
        board_stage = ({"task_id": board_task.id, "status": board_task.status,
                        "reason_code": board_task.error_code,
                        "reason": _BOARD_STAGE_REASONS.get(board_task.error_code, "板端性能阶段执行失败" if board_task.status == "FAILED" else None)} if board_task else
                       {"task_id": None, "status": "NOT_EXECUTED",
                        "reason": _BOARD_STAGE_REASONS.get(recorded_stage.get("reason_code"), "自动板端阶段在编译完成时未能入队"),
                        "reason_code": recorded_stage.get("reason_code")})
        return {"task_id":task.id,"mode":"REAL","notice":"REAL 编译事实；板端性能作为自动子任务单独记录，精度、稳定性、功耗和推荐部署仍需独立证据验证。","sections":{"onnx_model_profile":profile.analysis["summary"],"platform_governance":governance,"x5_compile":{"status":x5.get("status","NOT_EXECUTED"),"toolchain":x5.get("toolchain",{}),"platform_package":x5.get("platform_package",{}),"runner_version":x5.get("runner_version"),"rule_version":x5.get("rule_version"),"artifacts":x5.get("artifacts",[]),"evidence":x5.get("evidence",[]),"board_stage":board_stage,"board_validation":"NOT_EXECUTED","performance":"NOT_VERIFIED","accuracy":"NOT_VERIFIED","stability":"NOT_VERIFIED","deployment_recommendation":"NOT_VERIFIED"}}}
    return {
        "task_id": task.id, "mode": task.mode, "mock_notice": MOCK_NOTICE,
        "sections": {
            "multi_platform_summary": "仅供界面演示；不包含真实评估或部署结论。",
            "onnx_model_profile": profile.analysis["summary"],
            "platform_results": [
                {"platform": item.platform, "source": item.source, "fixture_version": item.fixture_version,
                 "mock_notice": MOCK_NOTICE, **item.payload} for item in results
            ],
            "optimization_suggestions": "本阶段不生成平台优化建议。",
            "evidence_appendix": {"analyzer_version": profile.analyzer_version,
                                  "demo_fixture_versions": sorted({item.fixture_version for item in results})},
        },
    }


def mock_pdf(report: dict) -> bytes:
    output = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(output, pagesize=A4)
    width, height = A4

    def heading(value: str, y: float) -> float:
        canvas.setFont("STSong-Light", 14)
        canvas.drawString(48, y, value)
        return y - 26

    def line(value: str, y: float) -> float:
        canvas.setFont("STSong-Light", 10)
        canvas.drawString(58, y, value)
        return y - 18

    canvas.setTitle(f"Mock DEMO 报告 {report['task_id']}")
    canvas.setFont("STSong-Light", 18)
    canvas.drawString(48, height - 60, "Mock / 不可用于交付结论")
    y = heading("DEMO 多平台评估报告", height - 100)
    y = line(f"任务：{report['task_id']}    模式：{report['mode']}", y)
    y = heading("0. 多平台评估结论摘要", y)
    y = line(report["sections"]["multi_platform_summary"], y)
    y = heading("1. ONNX 模型检测概要", y)
    summary = report["sections"]["onnx_model_profile"]
    y = line(f"节点数：{summary['node_count']}；算子：{summary['operator_counts']}", y)
    y = heading("2. 各平台适配与板端测试结果", y)
    for result in report["sections"]["platform_results"]:
        y = line(f"{result['platform']}：{result['status']}（{result['mock_notice']}）", y)
    y = heading("3. 后续优化建议", y)
    y = line(report["sections"]["optimization_suggestions"], y)
    y = heading("4. 版本与证据附录", y)
    appendix = report["sections"]["evidence_appendix"]
    line(f"分析器：{appendix['analyzer_version']}；示例结果：{', '.join(appendix['demo_fixture_versions'])}", y)
    canvas.setFont("STSong-Light", 9)
    canvas.drawString(48, 30, MOCK_NOTICE)
    canvas.save()
    return output.getvalue()


def real_compile_pdf(report: dict) -> bytes:
    """A factual X5 compile record, deliberately not a deployment report."""
    output = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(output, pagesize=A4)
    width, height = A4
    canvas.setTitle(f"X5 REAL 编译记录 {report['task_id']}")
    canvas.setFont("STSong-Light", 18)
    canvas.drawString(48, height - 60, "X5 REAL 编译记录（非板端交付结论）")
    y = height - 96

    def heading(value: str):
        nonlocal y
        canvas.setFont("STSong-Light", 14); canvas.drawString(48, y, value); y -= 24

    def line(value: str):
        nonlocal y
        if y < 60:
            canvas.showPage(); y = height - 60
        canvas.setFont("STSong-Light", 9); canvas.drawString(58, y, value[:110]); y -= 16

    details = report["sections"]["x5_compile"]
    heading("1. 编译事实")
    line(f"任务：{report['task_id']}；模式：REAL；编译状态：{status_label(details['status'])}")
    line("仅表示在锁定工具链、镜像、Platform Package、Runner 与固定配置下的编译结果。")
    heading("2. ONNX 模型检测概要")
    summary = report["sections"]["onnx_model_profile"]
    line(f"节点数：{summary['node_count']}；算子：{summary['operator_counts']}")
    heading("3. X5 编译与制品")
    line(f"工具链：{details['toolchain']}")
    line(f"平台包：{details['platform_package']}；Runner：{details['runner_version']}；规则：{details['rule_version']}")
    for item in details["artifacts"]:
        line(f"制品：{item.get('filename', item.get('type'))}；SHA256：{item.get('sha256', '未记录')}")
    governance = report["sections"].get("platform_governance", {})
    heading("4. 自动板端性能阶段")
    board_stage = details.get("board_stage", {})
    line(f"状态：{status_label(board_stage.get('status', 'NOT_EXECUTED'))}；任务：{board_stage.get('task_id') or '未创建'}")
    if board_stage.get("reason"): line(f"说明：{board_stage['reason']}")
    heading("5. 平台目录与执行快照")
    line(f"平台：{governance.get('platform_id', 'NOT_COLLECTED')}；目录：{governance.get('catalog_version', 'NOT_COLLECTED')}；Binding：{governance.get('binding_id', 'NOT_COLLECTED')}")
    line(f"Worker：{governance.get('worker_id', 'NOT_COLLECTED')}；固定 Runner：{governance.get('runner_version', 'NOT_COLLECTED')}；镜像锁定：{governance.get('image_lock', 'NOT_COLLECTED')}")
    heading("6. 未验证边界")
    line("精度：未验证；稳定性：未验证；功耗：未验证；推荐部署：未验证。")
    line("本编译记录不构成可交付结论；板端阶段的事实请以其独立记录为准。")
    canvas.save()
    return output.getvalue()


def real_board_smoke_pdf(report: dict) -> bytes:
    """Factual board record with conservative, evidence-backed profile metrics."""
    output = BytesIO(); pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(output, pagesize=A4); width, height = A4
    canvas.setTitle(f"X5 REAL 板端性能评测记录 {report['task_id']}")
    y = height - 60
    def heading(value: str):
        nonlocal y
        canvas.setFont("STSong-Light", 14); canvas.drawString(48, y, value); y -= 24
    def line(value: str):
        nonlocal y
        if y < 60: canvas.showPage(); y = height - 60
        canvas.setFont("STSong-Light", 9); canvas.drawString(58, y, value[:110]); y -= 16
    board = report["sections"]["x5_board_smoke"]
    canvas.setFont("STSong-Light", 18); canvas.drawString(48, y, "X5 REAL 板端性能评测记录"); y -= 36
    heading("1. 模型与编译制品")
    summary = report["sections"]["onnx_model_profile"]
    line(f"任务：{report['task_id']}；节点数：{summary['node_count']}；算子：{summary['operator_counts']}")
    line(f"model.bin SHA256：{board.get('model_bin_sha256', 'NOT_COLLECTED')}")
    heading("2. 板端执行事实")
    line(f"预检：{status_label(board.get('board_preflight', 'NOT_EXECUTED'))}；制品下发：{status_label(board.get('model_transfer', 'NOT_EXECUTED'))}")
    line(f"加载：{status_label(board.get('model_load', 'NOT_EXECUTED'))}；受控 Runtime 调用：{status_label(board.get('single_runtime_invocation', 'NOT_EXECUTED'))}")
    line(f"输入 SHA256：{board.get('input_sha256', 'NOT_COLLECTED')}；输出 SHA256：{board.get('output_sha256', 'NOT_COLLECTED')}")
    performance = board.get("performance", {})
    heading("3. 板端性能测量（固定 Runtime profile）")
    if performance.get("status") == "MEASURED":
        metrics = performance.get("metrics", {})
        condition = performance.get("running_condition", {})
        line(f"证据等级：{performance.get('evidence_level')}；Runner：{performance.get('runner')}；解析器：{performance.get('parser_version')}")
        environment = performance.get("environment", {})
        line(f"系统：{environment.get('system', 'NOT_COLLECTED')}；Runtime：{environment.get('runtime_version', 'NOT_COLLECTED')}；BPU：{environment.get('bpu_access', 'NOT_COLLECTED')}")
        line(f"FPS：{metrics.get('fps')}；平均延迟(ms)：{metrics.get('average_latency_ms')}；线程：{condition.get('thread_num')}；帧数：{condition.get('frame_count')}；运行时间(ms)：{condition.get('run_time_ms')}")
        for segment in performance.get("segments", []):
            line(f"分段：{segment.get('name')} [{segment.get('processor')}]，avg/min/max(ms)：{segment.get('average_ms')}/{segment.get('minimum_ms')}/{segment.get('maximum_ms')}")
        cpu = performance.get("model_cpu_operator_assessment", {})
        line(f"CPU 执行段：{performance.get('cpu_execution_segment_present')}；模型 CPU 算子：{cpu.get('status')}；编译期 CPU 列表：{cpu.get('compile_allocation_cpu_operators', 'NOT_COLLECTED')}")
    else:
        line("profile 未能解析为性能记录：NOT_COLLECTED。")
    governance = report["sections"].get("platform_governance", {})
    heading("4. 执行环境快照")
    line(f"平台：{governance.get('platform_id', 'NOT_COLLECTED')}；目录：{governance.get('catalog_version', 'NOT_COLLECTED')}；Binding：{governance.get('binding_id', 'NOT_COLLECTED')}")
    line(f"Worker：{governance.get('worker_id', 'NOT_COLLECTED')}；固定 Runner：{governance.get('runner_version', 'NOT_COLLECTED')}；镜像锁定：{governance.get('image_lock', 'NOT_COLLECTED')}")
    heading("5. 验证边界")
    line(f"Runtime：{board.get('runtime', {}).get('command', 'NOT_COLLECTED')}；版本：{board.get('runtime', {}).get('version', 'NOT_COLLECTED')}")
    line("本节仅描述固定 Runtime profile 的单次受控运行测量，不证明精度、稳定性、功耗或推荐部署。")
    line("精度、稳定性、功耗和推荐部署：未验证。")
    heading("6. 后续性能优化建议")
    for item in performance.get("guidance", {}).get("items", []):
        line(f"[{item.get('level', 'INFO')}] {item.get('message', '')}")
    canvas.save(); return output.getvalue()


def report_pdf(report: dict) -> bytes:
    if report["mode"] != "REAL":
        return mock_pdf(report)
    return real_board_smoke_pdf(report) if report.get("task_kind") == "REAL_BOARD_SMOKE" else real_compile_pdf(report)


def flow_report_view_model(session: Session, flow_id: str) -> dict | None:
    """User-facing report for one platform-neutral EvaluationFlow.

    Internal compilation and board tasks remain separately auditable, but the
    report selects the final reachable stage for each platform.  It never
    compares platform metrics as a ranking because their test conditions may
    differ.
    """
    flow = session.get(EvaluationFlow, flow_id)
    if flow is None:
        return None
    profile = session.get(ModelProfile, flow.model_profile_id)
    if profile is None:
        return None
    tasks = list(session.query(EvaluationTask).filter_by(flow_id=flow.id).order_by(EvaluationTask.created_at))
    selected: dict[str, EvaluationTask] = {}
    board_kinds = {"REAL_BOARD_SMOKE", "S100_BOARD_PERF"}
    for task in tasks:
        platform = str(task.platforms[0])
        current = selected.get(platform)
        if current is None or task.task_kind in board_kinds:
            selected[platform] = task
    platforms = []
    for platform, task in selected.items():
        result = session.query(EvaluationResult).filter_by(task_id=task.id).order_by(EvaluationResult.id.desc()).first()
        payload = result.platform_result if result else {}
        snapshot = session.get(TaskSnapshot, task.snapshot_id) if task.snapshot_id else None
        governance = snapshot.platform_governance if snapshot else {}
        performance = payload.get("performance", {})
        raw_metrics = performance.get("metrics", performance) if isinstance(performance, dict) else {}
        metrics = ({"fps": raw_metrics.get("fps"), "average_latency_ms": raw_metrics.get("average_latency_ms")}
                   if isinstance(raw_metrics, dict) and performance.get("status") == "MEASURED" else {})
        runner = governance.get("runner", {}) if isinstance(governance.get("runner"), dict) else {}
        platforms.append({
            "platform": platform, "stage_task_id": task.id, "stage_kind": task.task_kind,
            "status": task.status, "reason_code": task.error_code,
            "artifact_format": governance.get("artifact_format") or ("x5_bin" if platform == "X5" else None),
            "runner_release": governance.get("runner_release") or runner.get("version"),
            "parser": governance.get("parser") or governance.get("profile_parser_version"),
            "performance": performance, "metrics": metrics,
            "boundaries": payload.get("boundaries", {}),
        })
    statuses = {item["status"] for item in platforms}
    status = "SUCCEEDED" if statuses == {"SUCCEEDED"} else (
        "PARTIALLY_SUCCEEDED" if "SUCCEEDED" in statuses and statuses else
        "FAILED" if statuses and statuses.issubset({"FAILED", "CANCELLED", "TIMEOUT"}) else
        "RUNNING" if statuses & {"CLAIMED", "RUNNING"} else "QUEUED")
    return {"flow_id": flow.id, "mode": "REAL", "status": status, "preset": flow.preset,
            "notice": "一次评估流程汇总各平台真实阶段。不同平台的输入、线程、帧数与 Runtime 条件未对齐时，不作无条件性能排名；精度、稳定性、功耗和部署推荐仍未验证。",
            "sections": {"onnx_model_profile": profile.analysis["summary"], "platforms": platforms}}


def flow_report_pdf(report: dict) -> bytes:
    """Generate a concise factual PDF for a user-visible EvaluationFlow."""
    output = BytesIO(); pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(output, pagesize=A4); width, height = A4; y = height - 58
    def heading(value: str):
        nonlocal y
        if y < 70: canvas.showPage(); y = height - 58
        canvas.setFont("STSong-Light", 14); canvas.drawString(48, y, value); y -= 24
    def line(value: str):
        nonlocal y
        if y < 50: canvas.showPage(); y = height - 58
        canvas.setFont("STSong-Light", 9); canvas.drawString(58, y, value[:110]); y -= 16
    canvas.setTitle(f"评估流程报告 {report['flow_id']}")
    canvas.setFont("STSong-Light", 18); canvas.drawString(48, y, "多平台真实评估流程报告"); y -= 34
    line(f"流程：{report['flow_id']}；汇总状态：{status_label(report['status'])}；预设：{report['preset']}")
    heading("1. 评估范围与边界")
    line(report["notice"])
    summary = report["sections"]["onnx_model_profile"]
    heading("2. ONNX 模型检测概要")
    line(f"节点数：{summary.get('node_count')}；算子：{summary.get('operator_counts')}")
    heading("3. 各平台最终阶段")
    for item in report["sections"]["platforms"]:
        line(f"{item['platform']}：{status_label(item['status'])}；阶段：{item['stage_kind']}；制品：{item.get('artifact_format') or '未记录'}")
        line(f"固定 Runner：{item.get('runner_release') or '未记录'}；解析器：{item.get('parser') or '未记录'}；内部阶段：{item['stage_task_id']}")
        metrics = item.get("metrics") or {}
        if metrics:
            line(f"固定条件下实测：FPS={metrics.get('fps')}；平均延迟(ms)={metrics.get('average_latency_ms')}")
        elif item.get("reason_code"):
            line(f"失败原因：{item['reason_code']}")
    heading("4. 未验证边界")
    line("输出一致性：未执行；精度：未验证；稳定性：未验证；功耗：未验证；部署推荐：未验证。")
    canvas.save(); return output.getvalue()


# Customer delivery reports were versioned in M5-C-R1-R1.  Keep the legacy
# task report functions above for historical X5/DEMO endpoints, then replace
# only the Flow-level symbols consumed by the user report APIs.
from solution_advisor.reports.flow_delivery import flow_report_pdf, flow_report_view_model
