from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(database_path=tmp_path / "test.db", scheduler_enabled=False)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def monitor_payload():
    return {
        "name": "Production API",
        "url": "https://example.com/health",
        "interval_seconds": 30,
        "failure_threshold": 2,
    }
