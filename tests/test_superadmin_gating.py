"""Role gating: superadmin passes every require_role check. Admin passes admin only.

Calls the dependency wrapper directly. No database.
"""
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth.service import _allowed_roles, require_role  # noqa: E402


def _passes(required: str, role: str) -> bool:
    wrapper = require_role(required)
    try:
        wrapper(user={"role": role})
        return True
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.code == "INSUFFICIENT_PERMISSIONS"
        return False


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_admin_gate_passes_admin_and_superadmin(role):
    assert _passes("admin", role) is True


def test_admin_gate_rejects_plain_user():
    assert _passes("admin", "user") is False


def test_superadmin_gate_passes_superadmin_only():
    assert _passes("superadmin", "superadmin") is True
    assert _passes("superadmin", "admin") is False
    assert _passes("superadmin", "user") is False


@pytest.mark.parametrize("role", ["user", "missing"])
def test_unknown_or_missing_role_rejected(role):
    assert _passes("admin", role) is False


def test_other_required_role_passes_that_role_and_superadmin():
    assert _passes("custom", "custom") is True
    assert _passes("custom", "superadmin") is True
    assert _passes("custom", "admin") is False


def test_allowed_roles_map():
    assert _allowed_roles("admin") == {"admin", "superadmin"}
    assert _allowed_roles("superadmin") == {"superadmin"}
    assert _allowed_roles("custom") == {"custom", "superadmin"}
