"""Versioned, customer-facing reports for platform-neutral EvaluationFlow.

The module intentionally consumes only frozen Flow/Profile facts and Evidence
belonging to that Flow.  It does not inspect a current Catalog, Candidate or
administrator validation result while rendering a customer report.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select

from solution_advisor.artifacts.domain import Artifact, Evidence
from solution_advisor.evaluations.domain import EvaluationFlow, EvaluationResult, EvaluationTask, ReportRevision, TaskSnapshot
from solution_advisor.model_assets.domain import ModelAsset, ModelProfile

REPORT_TEMPLATE_VERSION = "customer-delivery-2.1.0"
_FONT_NAME: str | None = None
_LATIN_FONT_NAME: str | None = None

_STATUS = {
    "SUCCEEDED": "成功", "PARTIALLY_SUCCEEDED": "部分成功", "FAILED": "失败",
    "CANCELLED": "已取消", "TIMEOUT": "超时", "QUEUED": "等待执行",
    "CLAIMED": "已分配执行器", "RUNNING": "执行中", "NOT_EXECUTED": "未执行",
    "NOT_VERIFIED": "未验证", "MEASURED": "已测量",
}
_STAGE = {
    "X5_COMPILE": "X5 编译",
    "S100_COMPILE": "S100 编译",
    "REAL_BOARD_SMOKE": "X5 板端性能",
    "S100_BOARD_PERF": "S100 板端性能",
}


def status_label(value: object) -> str:
    return _STATUS.get(str(value), str(value))


def stage_label(value: object) -> str:
    return _STAGE.get(str(value), str(value))


def _font_name() -> str:
    """Use an embeddable CJK TTF in release images; CID is dev fallback only."""
    global _FONT_NAME
    if _FONT_NAME:
        return _FONT_NAME
    for path in (
        Path("/app/assets/DroidSansFallbackFull.ttf"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
    ):
        if path.exists():
            pdfmetrics.registerFont(TTFont("RealthonCJK", str(path)))
            _FONT_NAME = "RealthonCJK"
            return _FONT_NAME
    # Unit-test and development fallback.  Production Dockerfile installs and
    # copies an embeddable TTF before this branch can be reached.
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    _FONT_NAME = "STSong-Light"
    return _FONT_NAME


def _latin_font_name() -> str:
    """Return an embedded Latin companion font for mixed CJK/ASCII content.

    Droid Sans Fallback is deliberately used for complete Chinese coverage,
    but its PDF cmap does not reliably render ASCII on every ReportLab build.
    Flow IDs, hashes, versions and model names are therefore rendered with an
    explicitly embedded Latin font instead of silently disappearing.
    """
    global _LATIN_FONT_NAME
    if _LATIN_FONT_NAME:
        return _LATIN_FONT_NAME
    for path in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf"),
    ):
        if path.exists():
            pdfmetrics.registerFont(TTFont("RealthonLatin", str(path)))
            _LATIN_FONT_NAME = "RealthonLatin"
            return _LATIN_FONT_NAME
    # This branch is only a development fallback.  The production image
    # installs fonts-dejavu-core alongside the CJK font.
    _LATIN_FONT_NAME = _font_name()
    return _LATIN_FONT_NAME


def _datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value or "未记录")


def _short_sha(value: object) -> str:
    text = str(value or "未记录")
    return text if len(text) <= 20 else f"{text[:16]}…"


def _profile_snapshot(session, flow: EvaluationFlow) -> dict:
    existing = deepcopy(flow.model_snapshot or {})
    if existing.get("analysis"):
        return existing
    profile = session.get(ModelProfile, flow.model_profile_id)
    asset = session.get(ModelAsset, profile.model_asset_id) if profile else None
    if not profile or not asset:
        return {"source": "HISTORICAL_PROFILE_SNAPSHOT_UNAVAILABLE", "unavailable": True}
    # Historic Flow did not have the column at creation.  The referenced
    # Profile/asset pair is still immutable enough to create an explicit new
    # revision, never to rewrite an already-issued report.
    return {
        "source": "HISTORICAL_PROFILE_BACKFILL_VERIFIED",
        "model_asset_id": asset.id,
        "model_profile_id": profile.id,
        "filename": asset.original_filename,
        "sha256": asset.sha256,
        "size_bytes": asset.size_bytes,
        "analyzer_version": profile.analyzer_version,
        "analysis": deepcopy(profile.analysis or {}),
    }


def _final_platform_tasks(session, flow: EvaluationFlow) -> list[tuple[str, EvaluationTask]]:
    tasks = list(session.scalars(select(EvaluationTask).where(EvaluationTask.flow_id == flow.id).order_by(EvaluationTask.created_at)))
    selected: dict[str, EvaluationTask] = {}
    board_kinds = {"REAL_BOARD_SMOKE", "S100_BOARD_PERF"}
    for task in tasks:
        platform = str((task.platforms or ["平台"])[0])
        current = selected.get(platform)
        if current is None or task.task_kind in board_kinds:
            selected[platform] = task
    return list(selected.items())


def _platform_rows(session, flow: EvaluationFlow) -> list[dict]:
    """Freeze one customer-readable result row per platform.

    A board phase is the final result, while the compile phase is deliberately
    retained alongside it.  This avoids presenting a measured latency as if it
    also proved that compilation or the whole platform path succeeded.
    """
    all_tasks = list(session.scalars(
        select(EvaluationTask).where(EvaluationTask.flow_id == flow.id).order_by(EvaluationTask.created_at)
    ))
    tasks_by_platform: dict[str, list[EvaluationTask]] = {}
    for item in all_tasks:
        tasks_by_platform.setdefault(str((item.platforms or ["平台"])[0]), []).append(item)
    evidence_by_task: dict[str, list[Evidence]] = {}
    if all_tasks:
        for item in session.scalars(select(Evidence).where(Evidence.task_id.in_([task.id for task in all_tasks]))):
            evidence_by_task.setdefault(item.task_id, []).append(item)

    rows = []
    for platform, task in _final_platform_tasks(session, flow):
        result = session.scalar(select(EvaluationResult).where(EvaluationResult.task_id == task.id).order_by(EvaluationResult.id.desc()))
        payload = result.platform_result if result else {}
        snapshot = session.get(TaskSnapshot, task.snapshot_id) if task.snapshot_id else None
        frozen = deepcopy(snapshot.platform_governance or {}) if snapshot else {}
        performance = payload.get("performance", {}) if isinstance(payload, dict) else {}
        raw_metrics = performance.get("metrics", performance) if isinstance(performance, dict) else {}
        metrics = {}
        if isinstance(raw_metrics, dict) and (performance.get("status") == "MEASURED" or "fps" in raw_metrics):
            metrics = {key: raw_metrics.get(key) for key in ("fps", "average_latency_ms") if raw_metrics.get(key) is not None}
        runner = frozen.get("runner", {}) if isinstance(frozen.get("runner"), dict) else {}
        platform_tasks = tasks_by_platform.get(platform, [])
        compile_task = next((item for item in reversed(platform_tasks) if item.task_kind in {"X5_COMPILE", "S100_COMPILE"}), None)
        toolchains = []
        for item in [*(evidence_by_task.get(compile_task.id, []) if compile_task else []), *evidence_by_task.get(task.id, [])]:
            if item.toolchain_version and item.toolchain_version not in toolchains:
                toolchains.append(item.toolchain_version)
        rows.append({
            "platform": platform,
            "stage_task_id": task.id,
            "stage_kind": task.task_kind,
            "status": task.status,
            "reason_code": task.error_code,
            "artifact_format": frozen.get("artifact_format") or ("x5_bin" if platform == "X5" else "未记录"),
            "runner_release": frozen.get("runner_release") or runner.get("version") or "未记录",
            "parser": frozen.get("parser") or frozen.get("profile_parser_version") or "未记录",
            "toolchain_version": " / ".join(toolchains) or frozen.get("toolchain_version") or "未记录",
            "compile_status": compile_task.status if compile_task else "NOT_EXECUTED",
            "compile_stage_kind": compile_task.task_kind if compile_task else None,
            "compile_reason_code": compile_task.error_code if compile_task else None,
            "rules": frozen.get("rules", {}),
            "metrics": metrics,
            "measurement_conditions": (performance.get("running_condition") if isinstance(performance, dict) else {}) or {},
            "boundaries": payload.get("boundaries", {}) if isinstance(payload, dict) else {},
        })
    return rows


def _evidence_rows(session, tasks: list[tuple[str, EvaluationTask]]) -> list[dict]:
    ids = [task.id for _, task in tasks]
    if not ids:
        return []
    rows = []
    for evidence, artifact in session.execute(select(Evidence, Artifact).join(Artifact, Artifact.id == Evidence.artifact_id).where(Evidence.task_id.in_(ids))).all():
        rows.append({
            "platform": evidence.platform or "平台",
            "type": evidence.evidence_type,
            "phase": evidence.phase,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "toolchain_version": evidence.toolchain_version,
            "rule_package_version": evidence.rule_package_version,
        })
    return rows


def _flow_status(platforms: list[dict]) -> str:
    statuses = {item["status"] for item in platforms}
    if statuses == {"SUCCEEDED"}:
        return "SUCCEEDED"
    if "SUCCEEDED" in statuses and statuses:
        return "PARTIALLY_SUCCEEDED"
    if statuses and statuses.issubset({"FAILED", "CANCELLED", "TIMEOUT"}):
        return "FAILED"
    if statuses & {"CLAIMED", "RUNNING"}:
        return "RUNNING"
    return "QUEUED"


def _risk_flags(summary: dict) -> list[dict]:
    flags = summary.get("structure_flags", {}) if isinstance(summary, dict) else {}
    values = []
    for key, title in (("has_dynamic_shape", "动态 Shape"), ("has_control_flow", "控制流算子"), ("uses_external_data", "外部权重数据")):
        if flags.get(key):
            values.append({"label": title, "meaning": "这是通用模型事实，仍需由各平台编译与板端 Evidence 进一步判定。"})
    return values or [{"label": "未发现已登记的通用结构风险", "meaning": "这不等同于任何平台已支持，仍需完成平台编译和板端验证。"}]


def _build_snapshot(session, flow: EvaluationFlow) -> dict:
    model = _profile_snapshot(session, flow)
    analysis = model.get("analysis", {}) if isinstance(model, dict) else {}
    summary = analysis.get("summary", {}) if isinstance(analysis, dict) else {}
    extension_modules = analysis.get("analyzer_modules", {}) if isinstance(analysis, dict) else {}
    extensions = [
        {"module": module_id, "result": deepcopy(result)}
        for module_id, result in extension_modules.items()
        if isinstance(result, dict)
    ]
    platforms = _platform_rows(session, flow)
    status = _flow_status(platforms)
    evidence = _evidence_rows(session, _final_platform_tasks(session, flow))
    if status == "SUCCEEDED":
        conclusion = "所选平台的编译与板端最终阶段均已成功完成；性能事实仅适用于各自记录的固定测量条件。"
    elif status == "PARTIALLY_SUCCEEDED":
        conclusion = "部分平台已完成，其他平台的失败或未完成事实已保留；不得以成功平台覆盖其他平台结果。"
    else:
        conclusion = "本次评估未形成全部成功结论，请依据各平台阶段状态、原因和 Evidence 继续处理。"
    return {
        "flow_id": flow.id,
        "mode": "REAL",
        "status": status,
        "preset": flow.preset,
        "generated_from": {"flow_created_at": _datetime(flow.created_at), "profile_snapshot_source": model.get("source")},
        "model": model,
        "sections": {
            "executive_summary": {"conclusion": conclusion, "comparability": "不同平台的输入、线程、帧数与 Runtime 条件未对齐时，不作无条件性能排名。", "next_step": "补齐输出一致性、精度、稳定性、功耗等各自独立 Evidence 后，才可扩大结论范围。"},
            "onnx_model_profile": summary,
            "onnx_extensions": extensions,
            "onnx_risks": _risk_flags(summary),
            "platforms": platforms,
            "evidence": evidence,
            "boundaries": {"output_consistency": "未执行", "task_accuracy": "未验证", "stability": "未验证", "power": "未验证", "deployment_recommendation": "未验证"},
        },
    }


def create_flow_report_revision(session, flow: EvaluationFlow) -> ReportRevision:
    version = (session.scalar(select(func.max(ReportRevision.version)).where(ReportRevision.flow_id == flow.id)) or 0) + 1
    revision = ReportRevision(flow_id=flow.id, version=version, template_version=REPORT_TEMPLATE_VERSION, snapshot=_build_snapshot(session, flow))
    session.add(revision)
    session.flush()
    return revision


def latest_flow_report_revision(session, flow: EvaluationFlow, version: int | None = None, *, create: bool = True) -> ReportRevision | None:
    query = select(ReportRevision).where(ReportRevision.flow_id == flow.id)
    if version is not None:
        return session.scalar(query.where(ReportRevision.version == version))
    revision = session.scalar(query.order_by(ReportRevision.version.desc()))
    # A customer report is immutable.  When the approved template gains a new
    # presentation field, create a distinct audited revision on first access
    # instead of silently rewriting a previously issued report or requiring a
    # user-facing "generate version" operation.
    if revision and revision.template_version != REPORT_TEMPLATE_VERSION and create:
        return create_flow_report_revision(session, flow)
    return revision or (create_flow_report_revision(session, flow) if create else None)


def flow_report_view_model(session, flow_id: str, version: int | None = None) -> dict | None:
    flow = session.get(EvaluationFlow, flow_id)
    if flow is None:
        return None
    revision = latest_flow_report_revision(session, flow, version)
    if revision is None:
        return None
    report = deepcopy(revision.snapshot or {})
    report["revision"] = {"id": revision.id, "version": revision.version, "template_version": revision.template_version, "created_at": _datetime(revision.created_at), "pdf_artifact_id": revision.pdf_artifact_id}
    report["notice"] = "报告只依据本次 Flow 冻结的模型分析、平台快照和当前 Flow 的真实 Evidence；不同平台条件不一致时不作无条件性能排名。"
    return report


def list_flow_report_revisions(session, flow: EvaluationFlow) -> list[dict]:
    return [{"id": row.id, "version": row.version, "template_version": row.template_version, "created_at": _datetime(row.created_at), "pdf_ready": bool(row.pdf_artifact_id)} for row in session.scalars(select(ReportRevision).where(ReportRevision.flow_id == flow.id).order_by(ReportRevision.version.desc()))]


def _styles():
    name = _font_name()
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName=name, fontSize=23, leading=31, textColor=colors.HexColor("#0b2f59"), alignment=TA_CENTER, spaceAfter=11),
        "cover_meta": ParagraphStyle("cover_meta", parent=base["Normal"], fontName=name, fontSize=10, leading=17, textColor=colors.HexColor("#435a77"), alignment=TA_CENTER),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName=name, fontSize=16, leading=24, textColor=colors.HexColor("#0b2f59"), spaceBefore=13, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName=name, fontSize=12, leading=18, textColor=colors.HexColor("#155fae"), spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName=name, fontSize=9, leading=15, textColor=colors.HexColor("#263b54"), spaceAfter=5),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName=name, fontSize=7.6, leading=11, textColor=colors.HexColor("#53677f")),
        "table": ParagraphStyle("table", parent=base["BodyText"], fontName=name, fontSize=7.8, leading=10.5, textColor=colors.HexColor("#253b56")),
    }


def _p(value: object, style: ParagraphStyle) -> Paragraph:
    text = str(value if value not in (None, "") else "未记录")
    # Keep CJK in the complete Chinese font, while always embedding a
    # dedicated Latin font for identifiers, hashes, filenames and numbers.
    # This is especially important for the customer-facing cover page.
    escaped = escape(text)
    escaped = re.sub(r"([\x20-\x7e]+)", rf'<font name="{_latin_font_name()}">\1</font>', escaped)
    return Paragraph(escaped.replace("\n", "<br/>"), style)


def _table(rows: list[list[object]], widths: list[float], styles: dict) -> Table:
    table = Table([[_p(cell, styles["table"]) for cell in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2fb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123b68")),
        ("FONTNAME", (0, 0), (-1, -1), _font_name()),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d8e3f0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fbfe")]),
    ]))
    return table


def flow_report_pdf(report: dict) -> bytes:
    """Render an A4 customer PDF from one immutable ReportRevision snapshot."""
    from io import BytesIO

    styles = _styles(); output = BytesIO()
    model = report.get("model", {}) or {}; sections = report.get("sections", {}) or {}
    report_version = report.get("revision", {}).get("version", 1)
    flow_id = report.get("flow_id", "未记录")
    title = "AI 智能方案顾问 - 多芯片 AI 方案评测报告"

    def draw_right_segments(canvas, right: float, y: float, segments: list[tuple[str, str]], size: float) -> None:
        widths = [pdfmetrics.stringWidth(value, font, size) for value, font in segments]
        x = right - sum(widths)
        for (value, font), width in zip(segments, widths):
            canvas.setFont(font, size)
            canvas.drawString(x, y, value)
            x += width

    def draw_left_segments(canvas, left: float, y: float, segments: list[tuple[str, str]], size: float) -> None:
        x = left
        for value, font in segments:
            canvas.setFont(font, size)
            canvas.drawString(x, y, value)
            x += pdfmetrics.stringWidth(value, font, size)

    def header_footer(canvas, doc):
        canvas.saveState(); canvas.setFillColor(colors.HexColor("#59708c"))
        draw_left_segments(canvas, 18 * mm, A4[1] - 12 * mm, [
            ("AI ", _latin_font_name()), ("智能方案顾问 · 多芯片 ", _font_name()),
            ("AI ", _latin_font_name()), ("方案评测报告", _font_name()),
        ], 7.4)
        draw_right_segments(canvas, A4[0] - 18 * mm, 12 * mm, [
            ("流程：", _font_name()), (_short_sha(flow_id), _latin_font_name()),
            (" · 报告版本：", _font_name()), (f"V{report_version}", _latin_font_name()),
            (" · 生成：", _font_name()), (_datetime(report.get("revision", {}).get("created_at")), _latin_font_name()),
            (" · 第 ", _font_name()), (str(doc.page), _latin_font_name()), (" 页", _font_name()),
        ], 7.4)
        canvas.restoreState()

    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=20 * mm, bottomMargin=18 * mm, title=title, author="Realthon Solution Advisor")
    story = [Spacer(1, 20 * mm)]
    for logo_path in (Path("/app/assets/realthon-logo-mark.png"), Path("frontend/src/assets/realthon-logo-mark.png")):
        if logo_path.exists():
            logo = Image(str(logo_path), width=17 * mm, height=17 * mm, hAlign="CENTER")
            story += [logo, Spacer(1, 6 * mm)]
            break
    story += [_p(title, styles["cover_title"]), Spacer(1, 8 * mm)]
    story += [_p(f"模型：{model.get('filename', '历史 Flow 未冻结模型名称')}", styles["cover_meta"]), _p(f"Flow：{flow_id}　报告版本：V{report_version}　生成时间：{report.get('revision', {}).get('created_at', '本次生成')}", styles["cover_meta"]), _p(f"实际选择平台：{' + '.join(item.get('platform', '') for item in sections.get('platforms', [])) or '未记录'}", styles["cover_meta"]), Spacer(1, 22 * mm), _p("范围声明：性能、精度、稳定性、功耗和部署推荐，只有在具备各自独立 Evidence 时才会标记为已验证。", styles["body"]), Spacer(1, 34 * mm)]
    story.append(_p("REAL · 基于本次 Flow 冻结快照与真实 Evidence", styles["cover_meta"]))
    story.append(PageBreak())

    executive = sections.get("executive_summary", {})
    story += [_p("1. 多平台评估结论摘要", styles["h1"]), _p(executive.get("conclusion"), styles["body"]), _p(executive.get("comparability"), styles["body"])]
    matrix = [["平台", "工具链版本", "编译结果", "推理时延", "最终阶段", "可比性"]]
    for item in sections.get("platforms", []):
        metrics = item.get("metrics") or {}
        latency = f"{metrics.get('average_latency_ms')} ms" if item.get("status") == "SUCCEEDED" and metrics.get("average_latency_ms") is not None else status_label(item.get("status"))
        matrix.append([item.get("platform"), item.get("toolchain_version"), status_label(item.get("compile_status")), latency, stage_label(item.get("stage_kind")), "需对齐条件"])
    story += [_table(matrix, [18*mm, 37*mm, 20*mm, 26*mm, 30*mm, 34*mm], styles), _p(f"下一步：{executive.get('next_step')}", styles["body"])]

    story.append(_p("2. ONNX 模型检测概要", styles["h1"]))
    if model.get("unavailable"):
        story.append(_p("该历史 Flow 未冻结可验证的通用 ONNX Profile 快照，无法补充本节；未重新分析模型，也未猜测历史事实。", styles["body"]))
    else:
        summary = sections.get("onnx_model_profile", {})
        flags = summary.get("structure_flags", {}) if isinstance(summary, dict) else {}
        story.append(_table([["模型名称", "文件标识", "大小", "Profile / 分析器", "ONNX IR / Opset"], [model.get("filename"), _short_sha(model.get("sha256")), f"{model.get('size_bytes', '未记录')} 字节", f"{model.get('model_profile_id', '未记录')} / {model.get('analyzer_version', '未记录')}", f"IR {summary.get('ir_version', '未记录')} / {', '.join(str(x.get('version')) for x in summary.get('opset_imports', [])) or '未记录'}"]], [32*mm, 29*mm, 20*mm, 52*mm, 27*mm], styles))
        story += [_p("2.1 模型结构与兼容性检查", styles["h2"]), _table([["节点数", "算子类别", "动态 Shape", "控制流", "外部权重"], [summary.get("node_count", "未记录"), summary.get("operator_type_count", "未记录"), "存在" if flags.get("has_dynamic_shape") else "未发现", "存在" if flags.get("has_control_flow") else "未发现", "存在" if flags.get("uses_external_data") else "未发现"]], [27*mm, 27*mm, 32*mm, 32*mm, 32*mm], styles)]
        io_rows = [["类别", "名称", "Shape", "dtype", "动态维度"]]
        for category, items in (("输入", summary.get("inputs", [])), ("输出", summary.get("outputs", []))):
            for item in items:
                io_rows.append([category, item.get("name"), str(item.get("shape")), item.get("element_type"), "是" if any(item.get("dynamic_dimensions", [])) else "否"])
        story += [_p("2.2 输入与输出", styles["h2"]), _table(io_rows, [16*mm, 36*mm, 58*mm, 31*mm, 25*mm], styles)]
        ops = summary.get("operator_counts", {})
        story += [_p("2.3 算子分布", styles["h2"]), _p(f"{'，'.join(f'{key} {value}' for key, value in ops.items()) or '未记录'}。", styles["body"]), _p("2.4 通用风险标记", styles["h2"])]
        story += [_p(f"• {item['label']}：{item['meaning']}", styles["body"]) for item in sections.get("onnx_risks", [])]
        extensions = sections.get("onnx_extensions", [])
        if extensions:
            extension_rows = [["扩展检测项", "结果"]]
            extension_rows += [[item.get("module"), "；".join(f"{key}={value}" for key, value in (item.get("result") or {}).items()) or "已完成"] for item in extensions]
            story += [_p("2.5 已启用扩展检测", styles["h2"]), _table(extension_rows, [55*mm, 110*mm], styles)]
        story.append(_p("检测结论：本章仅确认通用 ONNX 结构事实；平台可执行性、性能与其他质量指标仍由后续平台编译和板端 Evidence 判定。", styles["body"]))

    story.append(_p("3. 各平台适配与板端测试结果", styles["h1"]))
    for index, item in enumerate(sections.get("platforms", []), 1):
        story += [_p(f"3.{index} {item.get('platform')}（{status_label(item.get('status'))}）", styles["h2"]), _p(f"结论：最终阶段为 {item.get('stage_kind')}，状态为 {status_label(item.get('status'))}。", styles["body"])]
        story.append(_table([["模型格式", "测试执行器", "结果解析器", "工具链版本"], [item.get("artifact_format"), item.get("runner_release"), item.get("parser"), item.get("toolchain_version")]], [34*mm, 42*mm, 42*mm, 42*mm], styles))
        metrics = item.get("metrics") or {}
        if metrics:
            condition = item.get("measurement_conditions") or {}
            story.append(_p(f"编译结果：{status_label(item.get('compile_status'))}。实测结果：FPS {metrics.get('fps', '未记录')}；平均延迟 {metrics.get('average_latency_ms', '未记录')} ms。测量条件：线程 {condition.get('thread_num', '未记录')}，帧数 {condition.get('frame_count', '未记录')}。", styles["body"]))
        elif item.get("reason_code"):
            story.append(_p(f"当前阻塞/失败原因：{item.get('reason_code')}。", styles["body"]))
        else:
            story.append(_p("该平台尚未采集可展示性能值。", styles["body"]))
        story.append(_p("未验证边界：输出一致性、精度、稳定性、功耗和部署推荐均不能由本阶段自动推断。", styles["small"]))

    story += [_p("4. 后续优化建议", styles["h1"]), _p("4.1 通用建议", styles["h2"]), _p("优先结合动态 Shape、控制流和算子分布，准备与业务输入一致的受控样本；输出一致性、精度和量化质量需使用版本化标注、后处理和明确指标单独验证。", styles["body"]), _p("4.2 平台专用建议", styles["h2"])]
    for item in sections.get("platforms", []):
        if item.get("metrics"):
            story.append(_p(f"{item.get('platform')}：以本报告列出的 Runner、解析器和测量条件为基线复测；如需横向比较，先对齐输入、线程、帧数和 Runtime 条件。", styles["body"]))
        else:
            story.append(_p(f"{item.get('platform')}：先处理该平台当前阶段的阻塞，再重新生成新的 Flow 进行验证。", styles["body"]))

    story += [_p("附录：Evidence、制品、规则、Runner、Parser 与版本快照", styles["h1"])]
    evidence = [["平台", "Evidence 类型", "阶段", "SHA256", "大小"]]
    for item in sections.get("evidence", []):
        evidence.append([item.get("platform"), item.get("type"), item.get("phase"), _short_sha(item.get("sha256")), item.get("size_bytes")])
    story.append(_table(evidence, [20*mm, 42*mm, 25*mm, 50*mm, 22*mm], styles))
    boundaries = sections.get("boundaries", {})
    story.append(_p("；".join(f"{label}：{boundaries.get(key, '未验证')}" for key, label in (
        ("output_consistency", "输出一致性"), ("task_accuracy", "精度"), ("stability", "稳定性"),
        ("power", "功耗"), ("deployment_recommendation", "部署推荐"),
    )), styles["small"]))
    story.append(_p(f"报告模板：{report.get('revision', {}).get('template_version', REPORT_TEMPLATE_VERSION)}；模型快照来源：{model.get('source', '未记录')}。", styles["small"]))
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return output.getvalue()
