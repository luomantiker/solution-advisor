from __future__ import annotations

from collections import Counter

import onnx
from onnx import TensorProto

CONTROL_FLOW_OPERATORS = {"If", "Loop", "Scan"}


class InvalidOnnxError(ValueError):
    """Raised when uploaded bytes cannot be parsed as a valid ONNX model."""


def load_model(payload: bytes) -> onnx.ModelProto:
    try:
        model = onnx.load_model_from_string(payload)
        onnx.checker.check_model(model)
        return model
    except Exception as exc:  # onnx has several exception types across versions
        raise InvalidOnnxError("Uploaded file is not a valid ONNX model") from exc


def _value_info(value: onnx.ValueInfoProto) -> dict:
    tensor_type = value.type.tensor_type
    shape = []
    dynamic_dimensions = []
    for dimension in tensor_type.shape.dim:
        if dimension.HasField("dim_value"):
            shape.append(dimension.dim_value)
            dynamic_dimensions.append(False)
        else:
            shape.append(dimension.dim_param or None)
            dynamic_dimensions.append(True)
    element_type = TensorProto.DataType.Name(tensor_type.elem_type) if tensor_type.elem_type else "UNDEFINED"
    return {
        "name": value.name,
        "element_type": element_type,
        "shape": shape,
        "dynamic_dimensions": dynamic_dimensions,
    }


def analyze(model: onnx.ModelProto, *, filename: str, size_bytes: int, sha256: str) -> dict:
    graph = model.graph
    operator_counts = Counter(node.op_type for node in graph.node)
    inputs = [_value_info(value) for value in graph.input]
    outputs = [_value_info(value) for value in graph.output]
    nodes = [
        {
            "name": node.name,
            "op_type": node.op_type,
            "domain": node.domain,
            "inputs": list(node.input),
            "outputs": list(node.output),
        }
        for node in graph.node
    ]
    uses_external_data = any(
        initializer.data_location == TensorProto.EXTERNAL or bool(initializer.external_data)
        for initializer in graph.initializer
    )
    return {
        "filename": filename,
        "size_bytes": size_bytes,
        "onnx_sha256": sha256,
        "summary": {
            "ir_version": model.ir_version,
            "opset_imports": [
                {"domain": item.domain, "version": item.version} for item in model.opset_import
            ],
            "inputs": inputs,
            "outputs": outputs,
            "node_count": len(nodes),
            "operator_type_count": len(operator_counts),
            "operator_counts": dict(sorted(operator_counts.items())),
            "structure_flags": {
                "has_dynamic_shape": any(
                    any(item["dynamic_dimensions"]) for item in [*inputs, *outputs]
                ),
                "has_control_flow": any(node.op_type in CONTROL_FLOW_OPERATORS for node in graph.node),
                "uses_external_data": uses_external_data,
            },
        },
        "nodes": nodes,
    }
