"""/auth/me returns the name claim from the JWT payload. No database."""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth.router import get_current_user  # noqa: E402


def test_me_returns_name_claim():
    body = get_current_user(user={"sub": "admin", "user_id": "u1", "role": "superadmin", "name": "Fabian Espinal"})
    assert body == {"username": "admin", "user_id": "u1", "role": "superadmin", "name": "Fabian Espinal"}


def test_me_returns_name_key_when_full_name_is_null():
    body = get_current_user(user={"sub": "admin", "user_id": "u1", "role": "admin", "name": None})
    assert "name" in body
    assert body["name"] is None
