"""Item 10, module 1: success envelope helper. Routes are not changed in this module."""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.responses import success_body  # noqa: E402


def test_shape_for_dict_payload():
    assert success_body({"id": 1}) == {"data": {"id": 1}, "success": True}


def test_shape_for_list_payload():
    assert success_body([1, 2]) == {"data": [1, 2], "success": True}


def test_shape_for_none_payload():
    assert success_body(None) == {"data": None, "success": True}


def test_payload_is_passed_through_unchanged():
    payload = {"message": "Client deleted successfully", "nested": {"a": [1, {"b": 2}]}}
    body = success_body(payload)
    assert body["data"] is payload


def test_exact_keys():
    assert set(success_body({})) == {"data", "success"}
