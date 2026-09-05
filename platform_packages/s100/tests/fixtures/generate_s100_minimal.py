"""Generate the small deterministic S100 compilation fixture.

The S100 ``hb_compile --fast-perf`` flow inserts NV12 image conversion.  Its
runtime requires the image width to be at least 16 pixels, so the repository
wide 8x8 static fixture is deliberately not reused here.
"""
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, checker, helper, numpy_helper


OUT = Path(__file__).with_name("s100_minimal_16x16.onnx")

input_info = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 16, 16])
output_info = helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, 4])
weights = [
    numpy_helper.from_array(np.arange(54, dtype=np.float32).reshape(2, 3, 3, 3) / 100, "conv_weight"),
    numpy_helper.from_array(np.zeros(2, dtype=np.float32), "conv_bias"),
    numpy_helper.from_array(np.arange(1568, dtype=np.float32).reshape(392, 4) / 1000, "linear_weight"),
    numpy_helper.from_array(np.zeros(4, dtype=np.float32), "linear_bias"),
]
nodes = [
    helper.make_node("Conv", ["input", "conv_weight", "conv_bias"], ["conv"], kernel_shape=[3, 3]),
    helper.make_node("Relu", ["conv"], ["relu"]),
    helper.make_node("Flatten", ["relu"], ["flat"], axis=1),
    helper.make_node("Gemm", ["flat", "linear_weight", "linear_bias"], ["logits"]),
]
model = helper.make_model(
    helper.make_graph(nodes, "s100_minimal_16x16", [input_info], [output_info], weights),
    opset_imports=[helper.make_operatorsetid("", 11)],
    producer_name="solution-advisor-s100",
)
model.ir_version = 7
checker.check_model(model)
onnx.save(model, OUT)
print(OUT)
