"""Item 3: /health returns only a status field."""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


def test_health_returns_only_status_field():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_health_has_no_module_or_timestamp_fields():
    body = TestClient(app).get("/health").json()
    assert "modules" not in body
    assert "timestamp" not in body
