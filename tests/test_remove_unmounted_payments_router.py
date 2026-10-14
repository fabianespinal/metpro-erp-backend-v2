"""Item 1: the unmounted payments router is removed; the live payment route requires auth."""
import importlib.util
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_dead_payments_router_module_is_removed():
    assert importlib.util.find_spec("invoices.payments.router") is None


def test_live_payment_route_requires_auth():
    from main import app

    matches = [
        r for r in app.routes
        if getattr(r, "path", "") == "/invoices/{invoice_id}/payments" and "POST" in getattr(r, "methods", set())
    ]
    assert len(matches) == 1

    dep_names = [d.call.__name__ for d in matches[0].dependant.dependencies if d.call is not None]
    assert "require_auth" in dep_names


def test_no_unauthenticated_payment_route_is_mounted():
    from main import app

    for r in app.routes:
        path = getattr(r, "path", "")
        if "payments" in path and "POST" in getattr(r, "methods", set()):
            dep_names = [d.call.__name__ for d in r.dependant.dependencies if d.call is not None]
            assert "require_auth" in dep_names or "require_role" in dep_names, path
