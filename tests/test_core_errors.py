"""Unit tests for core.errors.internal_error and the EXPOSE_ERROR_DETAIL toggle."""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.errors import expose_error_detail, internal_error  # noqa: E402

SECRET_TEXT = "password authentication failed for user postgres.abc123 at 10.0.0.5"
CONTEXT = "Quote create failed"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EXPOSE_ERROR_DETAIL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)


def _raise_and_wrap(context=CONTEXT, status_code=500):
    """Raise inside an except block so logger.exception sees the traceback."""
    try:
        raise RuntimeError(SECRET_TEXT)
    except Exception as e:
        return internal_error(context, e, status_code=status_code)


# ---------- toggle resolution ----------

def test_toggle_off_by_default():
    assert expose_error_detail() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_toggle_truthy_values_enable_outside_production(monkeypatch, value):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", value)
    monkeypatch.setenv("APP_ENV", "development")
    assert expose_error_detail() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off-ish"])
def test_toggle_non_truthy_values_disable(monkeypatch, value):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", value)
    monkeypatch.setenv("APP_ENV", "development")
    assert expose_error_detail() is False


def test_toggle_on_but_app_env_production_stays_off(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "true")
    monkeypatch.setenv("APP_ENV", "production")
    assert expose_error_detail() is False


def test_toggle_on_but_app_env_unset_defaults_to_production(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "true")
    assert expose_error_detail() is False


def test_toggle_app_env_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "true")
    monkeypatch.setenv("APP_ENV", "  Production ")
    assert expose_error_detail() is False


# ---------- detail returned to client ----------

def test_default_state_returns_context_only():
    exc = _raise_and_wrap()
    assert exc.status_code == 500
    assert exc.detail == CONTEXT
    assert SECRET_TEXT not in str(exc.detail)
    assert "RuntimeError" not in str(exc.detail)


def test_toggle_off_in_development_still_returns_context_only(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "false")
    monkeypatch.setenv("APP_ENV", "development")
    exc = _raise_and_wrap()
    assert exc.detail == CONTEXT
    assert SECRET_TEXT not in str(exc.detail)


def test_toggle_on_in_production_returns_context_only(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "true")
    monkeypatch.setenv("APP_ENV", "production")
    exc = _raise_and_wrap()
    assert exc.detail == CONTEXT
    assert SECRET_TEXT not in str(exc.detail)


def test_toggle_on_in_development_includes_exception(monkeypatch):
    monkeypatch.setenv("EXPOSE_ERROR_DETAIL", "true")
    monkeypatch.setenv("APP_ENV", "development")
    exc = _raise_and_wrap()
    assert exc.detail == f"{CONTEXT}: RuntimeError: {SECRET_TEXT}"


def test_status_code_is_respected():
    exc = _raise_and_wrap(status_code=502)
    assert exc.status_code == 502
    assert exc.detail == CONTEXT


# ---------- server-side logging ----------

@pytest.mark.parametrize("toggle,app_env", [
    (None, None),
    ("true", "development"),
    ("true", "production"),
])
def test_full_exception_is_logged_in_every_state(monkeypatch, caplog, toggle, app_env):
    if toggle is not None:
        monkeypatch.setenv("EXPOSE_ERROR_DETAIL", toggle)
    if app_env is not None:
        monkeypatch.setenv("APP_ENV", app_env)

    with caplog.at_level(logging.ERROR, logger="metpro.errors"):
        _raise_and_wrap()

    records = [r for r in caplog.records if r.name == "metpro.errors"]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == CONTEXT
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert str(record.exc_info[1]) == SECRET_TEXT
