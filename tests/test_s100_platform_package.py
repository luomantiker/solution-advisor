import hashlib
import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "platform_packages" / "s100"


def load_runner():
    path = PACKAGE / "runner" / "platform_runner" / "__main__.py"
    spec = importlib.util.spec_from_file_location("s100_runner", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_s100_package_declares_its_own_image_artifact_and_boundaries():
    manifest = yaml.safe_load((PACKAGE / "manifest.yaml").read_text())
    lock = yaml.safe_load((PACKAGE / "docker" / "image.lock.yaml").read_text())
    fixture = PACKAGE / "tests" / "fixtures" / "s100_minimal_16x16.onnx"
    assert manifest["id"] == "s100" and manifest["version"] == "3.7.0"
    assert manifest["artifact_format"] == "s100_hbm"
    assert lock["toolchain"]["hb_compile"] == "3.5.3"
    assert fixture.is_file()
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == "77b64fce50ad42b13d8a6380c222e9cf44ef39c2ab9d893820a618d794d8dabe"
    assert "x5" not in (PACKAGE / "runner" / "platform_runner" / "__main__.py").read_text().lower()


def test_s100_runner_rejects_tampered_model_before_invoking_toolchain(tmp_path, monkeypatch):
    runner = load_runner()
    request_dir = tmp_path / "input"; request_dir.mkdir()
    (request_dir / "model.onnx").write_bytes(b"not-the-declared-model")
    (request_dir / "request.json").write_text(json.dumps({"schema_version": "1.0", "capability": "compile", "model": {"sha256": "0" * 64}}))
    invoked = False
    def forbidden(*_args, **_kwargs):
        nonlocal invoked; invoked = True; raise AssertionError("toolchain must not execute")
    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    result_path = tmp_path / "output" / "result.json"
    assert runner.execute(request_dir / "request.json", result_path) == 2
    assert json.loads(result_path.read_text())["reason_code"] == "MODEL_SHA256_MISMATCH"
    assert not invoked
