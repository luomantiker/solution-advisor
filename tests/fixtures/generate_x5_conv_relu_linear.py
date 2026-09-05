"""Generate the small, deterministic X5 static-check ONNX fixture.

This is deliberately a *floating-point* ONNX model. It is useful for schema and
static-rule tests, but is not labelled as Horizon PTQ and must not be used to
claim a successful X5 compilation.
"""
from pathlib import Path
import numpy as np
import onnx
from onnx import TensorProto, checker, helper, numpy_helper

ROOT = Path(__file__).parent
# `minimal.onnx` is the repository-wide deterministic test fixture.  Keep the
# richer X5-compatible topology there so every upload/profile test uses the
# same versioned input.
OUT = ROOT / "minimal.onnx"

input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 8, 8])
output_info = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 4])
weights = [
    numpy_helper.from_array(np.arange(54, dtype=np.float32).reshape(2, 3, 3, 3) / 100, "conv_weight"),
    numpy_helper.from_array(np.zeros(2, dtype=np.float32), "conv_bias"),
    numpy_helper.from_array(np.arange(288, dtype=np.float32).reshape(72, 4) / 1000, "linear_weight"),
    numpy_helper.from_array(np.zeros(4, dtype=np.float32), "linear_bias"),
]
nodes = [
    helper.make_node("Conv", ["input", "conv_weight", "conv_bias"], ["conv"], kernel_shape=[3, 3]),
    helper.make_node("Relu", ["conv"], ["relu"]),
    helper.make_node("Flatten", ["relu"], ["flat"], axis=1),
    helper.make_node("Gemm", ["flat", "linear_weight", "linear_bias"], ["logits"]),
]
model = helper.make_model(helper.make_graph(nodes, "x5_conv_relu_linear", [input_info], [output_info], weights),
                          opset_imports=[helper.make_operatorsetid("", 11)], producer_name="solution-advisor")
model.ir_version = 7
checker.check_model(model)
onnx.save(model, OUT)
print(OUT)
