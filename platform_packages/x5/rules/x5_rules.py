"""Versioned X5 heuristic rules derived from the local reference implementation.

They are preflight hints only. `hb_mapper` output remains the compilation fact.
"""
from collections import Counter
import re
from onnx import helper

RULE_VERSION = "1.1.0"
QUANT_RISK = {
    "Softmax": "高", "Exp": "高", "Log": "高", "Pow": "高", "Reciprocal": "高",
    "LayerNormalization": "高", "InstanceNormalization": "高", "Sigmoid": "中高",
    "Div": "中高", "Sqrt": "中高", "ReduceMean": "中高", "ReduceSum": "中高",
    "MatMul": "中高", "Gemm": "中高", "ConvTranspose": "中高", "Resize": "中",
    "Concat": "中", "Add": "中", "Mul": "中",
}


def static_rules(model):
    risks = []
    for index, node in enumerate(model.graph.node):
        attrs = {item.name: helper.get_attribute_value(item) for item in node.attribute}
        name = node.name or f"{node.op_type}_{index}"
        if node.op_type == "Conv" and any(int(x) > 1 for x in attrs.get("dilations", [])):
            risks.append({"node": name, "op_type": "Conv", "level": "中高", "code": "CONV_DILATION", "message": "dilation>1，需要以工具链结果确认。"})
        if node.op_type == "Conv" and int(attrs.get("group", 1)) > 1:
            risks.append({"node": name, "op_type": "Conv", "level": "中", "code": "CONV_GROUP", "message": "分组卷积，需要以工具链结果确认。"})
        if node.op_type == "Pad" and str(attrs.get("mode", "constant")).lower() != "constant":
            risks.append({"node": name, "op_type": "Pad", "level": "中高", "code": "PAD_MODE", "message": "非 constant Pad，需要以工具链结果确认。"})
        if node.op_type == "MaxPool" and int(attrs.get("ceil_mode", 0)) == 1:
            risks.append({"node": name, "op_type": "MaxPool", "level": "中", "code": "MAXPOOL_CEIL", "message": "ceil_mode=1，需要以工具链结果确认。"})
        if node.op_type in {"Resize", "Slice", "Gather"}:
            risks.append({"node": name, "op_type": node.op_type, "level": "中", "code": f"{node.op_type.upper()}_ATTR", "message": "属性/输入来源需要以工具链结果确认。"})
    counts = Counter(node.op_type for node in model.graph.node)
    quant = [{"op_type": op, "count": count, "level": QUANT_RISK[op]} for op, count in sorted(counts.items()) if op in QUANT_RISK]
    if counts["Sigmoid"] and counts["Mul"]:
        quant.append({"op_type": "Sigmoid+Mul", "count": counts["Sigmoid"] + counts["Mul"], "level": "中高"})
    return {"rule_version": RULE_VERSION, "attribute_risks": risks, "quantization_risks": quant,
            "disclaimer": "规则为静态风险提示；编译日志和实际编译状态才是工具链执行事实。"}


def parse_compile_log(text: str):
    """Extract the authoritative BPU/CPU allocation table without performance metrics."""
    allocation = {"BPU": [], "CPU": []}; in_table = False; on_column = None
    for line in text.splitlines():
        if "The main quantized node information:" in line: in_table = True; continue
        if in_table and "The quantized model output:" in line: break
        if in_table and line.strip().startswith("Node") and "Subgraph" in line:
            match = re.search(r"\bON\b", line); on_column = match.start() if match else None; continue
        if in_table and on_column is not None:
            fields = line[on_column:].split()
            if fields and fields[0] in allocation: allocation[fields[0]].append(line.split()[0])
    unsupported = sorted(set(re.findall(r"Unsupported\s+op(?:erator)?\s*:?\s*([A-Za-z0-9_]+)", text, re.I)))
    return {"allocation": allocation, "unsupported_ops": unsupported}
