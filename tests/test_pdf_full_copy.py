"""Internal full copy PDF: every line prints, ignoring print_items = false and per-line print_on_pdf = false.

Admin and superadmin only, behind PDF_FULL_COPY_ENABLED (default off). Public links and emails never use it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_pdf_medidas_m2 import (  # noqa: E402  (reuses the builders and the DB fixture)
    ITEMS, NO_CHARGES, build, client, db, needs_db, text, _rows, _no_db_pages,
)
from auth.service import create_access_token  # noqa: E402


def _hdr(role):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


def _items(hidden_line=True):
    rows = [dict(i) for i in ITEMS]
    if hidden_line:
        rows[1]["print_on_pdf"] = False
    return rows


def test_default_build_is_unchanged_hidden_line_stays_hidden():
    t = text(build(items=_items()))
    assert "Viga W10x12" in t and "Tornillo" not in t


def test_full_copy_prints_hidden_lines():
    t = text(build(items=_items(), full_copy=True))
    assert "Viga W10x12" in t and "Tornillo" in t


def test_full_copy_prints_the_table_when_the_checkbox_is_off():
    assert "Viga W10x12" not in text(build(print_items=False))
    assert "Viga W10x12" in text(build(print_items=False, full_copy=True))


def test_full_copy_changes_no_total():
    a = text(build(items=_items()))
    b = text(build(items=_items(), full_copy=True))
    for number in ("1,050.00", "1,239.00", "189.00"):
        assert (number in a) == (number in b)


def test_check_full_copy_rules(monkeypatch):
    from fastapi import HTTPException
    from pdf.service import _check_full_copy
    _check_full_copy(False, {"role": "user"})  # a normal request is never checked
    monkeypatch.delenv("PDF_FULL_COPY_ENABLED", raising=False)
    with pytest.raises(HTTPException) as e:
        _check_full_copy(True, {"role": "admin"})
    assert e.value.status_code == 404
    monkeypatch.setenv("PDF_FULL_COPY_ENABLED", "true")
    with pytest.raises(HTTPException) as e:
        _check_full_copy(True, {"role": "user"})
    assert e.value.status_code == 403
    for role in ("admin", "superadmin"):
        _check_full_copy(True, {"role": role})


@needs_db
def test_routes_full_copy_for_quote_and_invoice(db, monkeypatch):
    monkeypatch.setenv("PDF_FULL_COPY_ENABLED", "true")
    body = {"client_id": db["cid"], "contact_id": db["ctid"], "project_name": "Torre Norte", "included_charges": NO_CHARGES,
            "print_items": False,
            "items": [{"product_name": "Viga unica", "quantity": 2, "unit_price": 500.0},
                      {"product_name": "Linea oculta", "quantity": 1, "unit_price": 10.0, "print_on_pdf": False}]}
    qid = client.post("/quotes/", json=body, headers=_hdr("admin")).json()["data"]["quote_id"]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr("admin"))
    token = _rows(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))[0]["public_token"]

    normal = client.get(f"/pdf/quotes/{qid}", headers=_hdr("admin"))
    assert "Viga unica" not in text(normal.content)
    full = client.get(f"/pdf/quotes/{qid}?full=true", headers=_hdr("admin"))
    assert full.status_code == 200 and "_completa" in full.headers["content-disposition"]
    t = text(full.content)
    assert "Viga unica" in t and "Linea oculta" in t and "Resumen Financiero" in t
    assert client.get(f"/pdf/quotes/{qid}?full=true", headers=_hdr("superadmin")).status_code == 200
    assert client.get(f"/pdf/quotes/{qid}?full=true", headers=_hdr("user")).status_code == 403
    # Public link and the other internal download never print it.
    assert "Viga unica" not in text(client.get(f"/quotes/public/{token}/pdf").content)
    assert "Viga unica" not in text(client.get(f"/quotes/{qid}/pdf", headers=_hdr("admin")).content)
    monkeypatch.setenv("PDF_FULL_COPY_ENABLED", "false")
    assert client.get(f"/pdf/quotes/{qid}?full=true", headers=_hdr("admin")).status_code == 404
    monkeypatch.setenv("PDF_FULL_COPY_ENABLED", "true")

    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr("admin")).status_code == 200
    iid = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr("admin")).json()["data"]["invoice_id"]
    assert "Viga unica" not in text(client.get(f"/pdf/invoices/{iid}", headers=_hdr("admin")).content)
    fi = client.get(f"/pdf/invoices/{iid}?full=true", headers=_hdr("admin"))
    assert fi.status_code == 200 and "Viga unica" in text(fi.content) and "Linea oculta" in text(fi.content)
    assert client.get(f"/pdf/invoices/{iid}?full=true", headers=_hdr("user")).status_code == 403
    itoken = _rows(db, "SELECT public_token FROM invoices WHERE id = %s", (iid,))[0]["public_token"]
    assert "Viga unica" not in text(client.get(f"/invoices/public/{itoken}/pdf").content)
