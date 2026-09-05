from __future__ import annotations

from pathlib import Path

import pytest
import fakeredis
from fastapi.testclient import TestClient

from solution_advisor.api.app import create_app
from solution_advisor.common_analyzer.queue import RedisAnalysisQueue


@pytest.fixture
def model_bytes() -> bytes:
    return (Path(__file__).parent / "fixtures" / "minimal.onnx").read_bytes()


@pytest.fixture
def app(tmp_path: Path):
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        storage_root=tmp_path / "uploads",
        queue=RedisAnalysisQueue(fakeredis.FakeRedis()),
        test_identities=True,
    )


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        # Ordinary portal calls use an explicit development identity; authorization
        # boundary tests override this header with an empty value or another role.
        test_client.headers.update({"Authorization": "Bearer development-user-token"})
        yield test_client
