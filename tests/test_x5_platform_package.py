import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "platform_packages" / "x5"
MODEL = ROOT / "tests" / "fixtures" / "minimal.onnx"

def controlled_request() -> dict:
    request = json.loads((PACKAGE / "tests" / "static-request.json").read_text())
    request["model"]["sha256"] = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    return request


def test_x5_manifest_and_image_lock_are_restricted():
    manifest = yaml.safe_load((PACKAGE / "manifest.yaml").read_text())
    lock = yaml.safe_load((PACKAGE / "docker" / "image.lock.yaml").read_text())
    assert manifest["capabilities"] == ["static_check", "compile"]
    assert lock["toolchain"]["hb_mapper"] == "1.24.3"
    assert "board_test" not in manifest["capabilities"]


def test_runner_static_request_result_contract(tmp_path):
    request = controlled_request()
    (tmp_path / "request.json").write_text(json.dumps(request)); (tmp_path / "model.onnx").write_bytes(MODEL.read_bytes())
    result = tmp_path / "result.json"; env = {**os.environ, "PYTHONPATH": f"{PACKAGE / 'runner'}:{PACKAGE}"}
    run = subprocess.run([sys.executable, "-m", "platform_runner", "execute", "--request", str(tmp_path / "request.json"), "--result", str(result)], env=env, check=False)
    payload = json.loads(result.read_text())
    assert run.returncode == 0 and payload["status"] == "SUCCEEDED"
    assert payload["stages"][0]["opsets"] == [11]
    assert payload["board_validation"] == "NOT_EXECUTED"
    assert payload["performance"] == payload["accuracy"] == payload["stability"] == payload["deployment_recommendation"] == "NOT_VERIFIED"
    assert (tmp_path / "artifacts" / "static_check.json").is_file()


def test_runner_rejects_model_hash_mismatch(tmp_path):
    request = controlled_request(); request["model"]["sha256"] = "0" * 64
    (tmp_path / "request.json").write_text(json.dumps(request)); (tmp_path / "model.onnx").write_bytes(MODEL.read_bytes())
    result = tmp_path / "result.json"; env = {**os.environ, "PYTHONPATH": f"{PACKAGE / 'runner'}:{PACKAGE}"}
    run = subprocess.run([sys.executable, "-m", "platform_runner", "execute", "--request", str(tmp_path / "request.json"), "--result", str(result)], env=env, check=False)
    assert run.returncode == 2 and json.loads(result.read_text())["reason_code"] == "MODEL_SHA256_MISMATCH"
