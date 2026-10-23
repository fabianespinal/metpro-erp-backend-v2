from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
from datetime import datetime
import json
from database import get_db_connection
from core.errors import internal_error
from psycopg2.extras import RealDictCursor
import logging
from core import status_history

logger = logging.getLogger("metpro.invoices")


def generate_invoice_number() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"INV-{timestamp}"


def calculate_invoice_totals(items: List[dict], charges: dict, tax_rate: Optional[float] = None) -> dict:
    """Same arithmetic as quotes: one implementation, so the two cannot drift.

    Pass the invoice's stored tax_rate (A1). None keeps the pre-A1 behavior for the parity tests.
    """
    from quotes.service import calculate_quote_totals  # local: avoids import cycle
    return calculate_quote_totals(items, charges, tax_rate)


def _legacy_calculate_invoice_totals(items: List[dict], charges: dict) -> dict:
    """Previous copy, kept only for the parity test. Not used at runtime."""
    items_total = sum(float(item["quantity"] or 0) * float(item["unit_price"] or 0) for item in items)
    total_discounts = 0
    for item in items:
        subtotal = float(item["quantity"] or 0) * float(item["unit_price"] or 0)
        if item.get("discount_type") == "percentage":
            total_discounts += subtotal * (float(item.get("discount_value", 0)) / 100)
        elif item.get("discount_type") == "fixed":
            total_discounts += float(item.get("discount_value", 0))

    items_after_discount = items_total - total_discounts

    supervision_pct = float(charges.get("supervision_percentage", 10.0))
    admin_pct = float(charges.get("admin_percentage", 4.0))
    insurance_pct = float(charges.get("insurance_percentage", 1.0))
    transport_pct = float(charges.get("transport_percentage", 3.0))
    contingency_pct = float(charges.get("contingency_percentage", 3.0))

    supervision = items_after_discount * (supervision_pct / 100) if charges.get("supervision") else 0
    admin = items_after_discount * (admin_pct / 100) if charges.get("admin") else 0
    insurance = items_after_discount * (insurance_pct / 100) if charges.get("insurance") else 0
    transport = items_after_discount * (transport_pct / 100) if charges.get("transport") else 0
    contingency = items_after_discount * (contingency_pct / 100) if charges.get("contingency") else 0

    subtotal_general = items_after_discount + supervision + admin + insurance + transport + contingency
    itbis = subtotal_general * 0.18
    grand_total = subtotal_general + itbis

    return {
        "items_total": items_total,
        "total_discounts": total_discounts,
        "items_after_discount": items_after_discount,
        "supervision": supervision,
        "admin": admin,
        "insurance": insurance,
        "transport": transport,
        "contingency": contingency,
        "subtotal_general": subtotal_general,
        "itbis": itbis,
        "grand_total": grand_total,
    }


# ============================================================
# INVOICE LINES + TOTALS FOR PDFs (F2)
# ============================================================

def _invoice_lines(cursor, invoice: dict):
    """
    Lines for an invoice document.
    Source of truth: invoice_items (written at conversion).
    Legacy fallback: quote_items, only when the invoice has no items.
    Order: line_no (written at conversion, B-19), then ctid for any legacy row without it.
    """
    cursor.execute(
        "SELECT description, quantity, unit_price, discount, total, product_id, category, print_on_pdf, "
        "to_jsonb(invoice_items)->>'unit_of_measure' AS unit_of_measure "
        "FROM invoice_items WHERE invoice_id = %s ORDER BY line_no NULLS LAST, ctid",
        (invoice["id"],),
    )
    rows = cursor.fetchall()
    if rows:
        return [
            {
                "product_name": r["description"] or "",
                "description": None,
                "quantity": float(r["quantity"] or 0),
                "unit_price": float(r["unit_price"] or 0),
                # invoice_items.discount is a currency amount for the whole line.
                "discount_type": "fixed" if float(r["discount"] or 0) > 0 else "none",
                "discount_value": float(r["discount"] or 0),
                "product_id": r.get("product_id"),
                "category": r.get("category"),
                "print_on_pdf": r.get("print_on_pdf", True),
                "unit_of_measure": r.get("unit_of_measure"),
            }
            for r in rows
        ], "invoice_items"

    if invoice.get("quote_id"):
        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (invoice["quote_id"],))
        return [dict(r) for r in cursor.fetchall()], "quote_items"
    return [], "none"


def invoice_lines_and_totals(invoice: dict, charges: dict):
    """
    (items, totals) for any invoice PDF: download, email, public link, conduce.
    The grand total shown is always the billed amount, invoices.total_amount.
    The charge breakdown is computed from the same lines; a mismatch over one
    cent is logged so it can be investigated, never silently re-priced.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        items, source = _invoice_lines(cursor, invoice)
    finally:
        conn.close()

    rate = invoice.get("tax_rate")
    totals = calculate_invoice_totals(items, charges or {}, None if rate is None else float(rate))
    totals["tax_label"] = invoice.get("tax_label")  # A1: printed as stored
    totals["tax_rate"] = None if rate is None else float(rate)
    billed = invoice.get("total_amount")
    if billed is not None:
        billed = float(billed)
        if abs(billed - totals["grand_total"]) > 0.01:
            logger.warning(
                "Invoice %s: billed total %.2f differs from line-derived total %.2f (lines from %s)",
                invoice.get("id"), billed, totals["grand_total"], source,
            )
        totals["grand_total"] = billed
    totals["lines_source"] = source
    return items, totals


def create_invoice_from_quote(quote_id: str, notes: Optional[str] = None, created_by_user_id: Optional[str] = None) -> dict:
    """
    POST /invoices/ path. Delegates to the single conversion path
    (quotes.service.convert_quote_to_invoice) so both routes write the same
    invoice: contact, invoice_items, header totals, and quote status.
    If notes are given they replace the notes copied from the quote.
    """
    from quotes.service import convert_quote_to_invoice  # local: avoids import cycle

    converted = convert_quote_to_invoice(quote_id, created_by_user_id)
    invoice_id = converted["id"]

    if notes is not None:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE invoices SET notes = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (notes, invoice_id),
            )
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise internal_error("La factura se creó, pero no se pudieron guardar las notas", e)
        finally:
            if conn:
                conn.close()

    return get_invoice_by_id(invoice_id)


def get_all_invoices(client_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT
                i.id,
                i.quote_id,
                i.invoice_number,
                i.invoice_date,
                i.client_id,
                c.company_name AS client_name,
                i.total_amount,
                i.itbis_total,
                COALESCE(i.amount_paid, 0) AS amount_paid,
                COALESCE(i.amount_due, i.total_amount) AS amount_due,
                i.status,
                i.notes,
                i.created_at,
                i.updated_at,
                (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = i.created_by_user_id) AS created_by_name
            FROM invoices i
            JOIN clients c ON i.client_id = c.id
            WHERE 1=1
        """
        params = []

        if client_id:
            query += " AND i.client_id = %s"
            params.append(client_id)
        if status:
            query += " AND i.status = %s"
            params.append(status)

        query += " ORDER BY i.invoice_date DESC"
        cursor.execute(query, params)

        rows = [dict(row) for row in cursor.fetchall()]
        return status_history.attach_last(cursor, status_history.INVOICE, rows, "id")
    finally:
        if conn:
            conn.close()


def get_invoice_status_history(invoice_id: int) -> dict:
    """Full history, newest first. enabled=false when the switch is off."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT status FROM invoices WHERE id = %s", (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")
        return {"enabled": status_history.enabled(), "current_status": invoice["status"],
                "entries": status_history.fetch(cursor, status_history.INVOICE, invoice_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo leer el historial", e)
    finally:
        if conn:
            conn.close()


def get_invoice_by_id(invoice_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT i.*,
                   (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = i.created_by_user_id) AS created_by_name,
                   (SELECT c.company_name FROM clients c WHERE c.id = i.client_id) AS client_name
            FROM invoices i
            WHERE i.id = %s
        """, (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        invoice = dict(invoice)

        # Balances. amount_due = 0 means fully paid; only NULL falls back to total - paid.
        invoice["amount_paid"] = float(invoice.get("amount_paid") or 0)
        if invoice.get("amount_due") is None:
            invoice["amount_due"] = round(float(invoice.get("total_amount") or 0) - invoice["amount_paid"], 2)
        else:
            invoice["amount_due"] = float(invoice["amount_due"])

        # Lines: invoice_items (written at conversion). Legacy fallback: quote_items.
        cursor.execute(
            "SELECT description, quantity, unit_price, discount, total FROM invoice_items "
            "WHERE invoice_id = %s ORDER BY line_no NULLS LAST, ctid",
            (invoice_id,),
        )
        rows = cursor.fetchall()
        if rows:
            items = [
                {
                    "product_name": r["description"] or "",
                    "quantity": float(r["quantity"] or 0),
                    "unit_price": float(r["unit_price"] or 0),
                    "discount_type": "fixed" if float(r["discount"] or 0) > 0 else "none",
                    "discount_value": float(r["discount"] or 0),
                    "total": float(r["total"] or 0),
                }
                for r in rows
            ]
        else:
            cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (invoice["quote_id"],))
            items = [dict(row) for row in cursor.fetchall()]
        invoice["items"] = items

        cursor.execute("SELECT included_charges FROM quotes WHERE quote_id = %s", (invoice["quote_id"],))
        quote_row = cursor.fetchone()
        if quote_row:
            raw_charges = quote_row["included_charges"]
            try:
                if isinstance(raw_charges, str):
                    charges = json.loads(raw_charges)
                else:
                    charges = raw_charges or {}
            except Exception:
                charges = {}

            rate = invoice.get("tax_rate")
            totals = calculate_invoice_totals(items, charges, None if rate is None else float(rate))
            invoice["totals"] = totals

        return invoice

    finally:
        if conn:
            conn.close()


def get_invoice_by_number(invoice_number: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM invoices WHERE invoice_number = %s", (invoice_number,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        return dict(invoice)

    finally:
        if conn:
            conn.close()


# Manual status changes. Paid is reached only by recording payments.
# Cancelled is allowed only while nothing has been paid.
INVOICE_STATUSES = ("Pending", "Paid", "Cancelled", "Overdue")
MANUAL_INVOICE_TRANSITIONS = {
    "Draft": {"Pending", "Cancelled"},      # legacy DB default; not used by the app
    "Pending": {"Overdue", "Cancelled"},
    "Overdue": {"Pending", "Cancelled"},
    "Paid": set(),
    "Cancelled": set(),
}


def _release_quote_if_no_active_invoice(cursor, quote_id, actor_user_id=None) -> bool:
    """Invoiced -> Approved when the quote has no other non-cancelled invoice (B-06).

    The quote can then be invoiced again. Returns True when the quote was released.
    """
    if not quote_id:
        return False
    cursor.execute(
        """
        UPDATE quotes SET status = 'Approved', updated_at = CURRENT_TIMESTAMP
        WHERE quote_id = %s AND status = 'Invoiced'
          AND NOT EXISTS (SELECT 1 FROM invoices WHERE quote_id = %s AND status <> 'Cancelled')
        """,
        (quote_id, quote_id),
    )
    released = cursor.rowcount > 0
    if released:
        status_history.record(cursor, status_history.QUOTE, quote_id, "Invoiced", "Approved", actor_user_id,
                              note="invoice removed")
    return released


def update_invoice_status(invoice_id: int, status: str, actor_user_id: Optional[str] = None) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if status not in INVOICE_STATUSES:
            raise api_error(400, f"Estado no válido. Debe ser uno de: {list(INVOICE_STATUSES)}", "INVOICE_STATUS_INVALID")

        cursor.execute(
            "SELECT id, quote_id, status, COALESCE(amount_paid, 0) AS amount_paid FROM invoices WHERE id = %s FOR UPDATE",
            (invoice_id,),
        )
        current = cursor.fetchone()
        if not current:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        if status != current["status"]:
            if status == "Paid":
                raise api_error(400, "Las facturas pasan a Pagada al registrar pagos", "INVOICE_PAID_VIA_PAYMENTS")
            allowed = MANUAL_INVOICE_TRANSITIONS.get(current["status"], set())
            if status not in allowed:
                raise api_error(400, f"No se puede cambiar la factura de {current['status']} a {status}", "INVOICE_TRANSITION_INVALID")
            if status == "Cancelled" and float(current["amount_paid"]) > 0:
                raise api_error(400, "La factura tiene pagos y no se puede cancelar", "INVOICE_HAS_PAYMENTS")

            cursor.execute(
                "UPDATE invoices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, invoice_id),
            )
            status_history.record(cursor, status_history.INVOICE, invoice_id, current["status"], status, actor_user_id)
            if status == "Cancelled":
                # B-06: the quote returns to Approved so it can be invoiced again.
                _release_quote_if_no_active_invoice(cursor, current["quote_id"], actor_user_id)
            conn.commit()

        return get_invoice_by_id(invoice_id)

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar", e)
    finally:
        if conn:
            conn.close()


def delete_invoice(invoice_id: int, actor_user_id: Optional[str] = None) -> dict:
    """
    Delete one invoice and its line items in a single transaction.
    Refused when the invoice has payments: payment records are never deleted.
    The source quote returns to Approved only if it is currently Invoiced.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id, quote_id FROM invoices WHERE id = %s FOR UPDATE", (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        cursor.execute("SELECT COUNT(*) AS n FROM invoice_payments WHERE invoice_id = %s", (invoice_id,))
        if cursor.fetchone()["n"] > 0:
            raise api_error(400, "La factura tiene pagos y no se puede eliminar", "INVOICE_HAS_PAYMENTS")

        quote_id = invoice["quote_id"]
        invoice_status = None
        if status_history.enabled():  # one extra read, only when the history is on
            cursor.execute("SELECT status FROM invoices WHERE id = %s", (invoice_id,))
            invoice_status = (cursor.fetchone() or {}).get("status")

        cursor.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        # B-05: conduce records belong to the invoice (like its items). Without this the FK
        # made any invoice with a previewed conduce impossible to delete.
        cursor.execute("DELETE FROM conduces WHERE invoice_id = %s", (invoice_id,))
        cursor.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        # Back to Approved only when no other active invoice remains (B-06 re-invoices).
        if status_history.enabled():
            status_history.record(cursor, status_history.INVOICE, invoice_id, invoice_status, "Deleted", actor_user_id)
        quote_reverted = _release_quote_if_no_active_invoice(cursor, quote_id, actor_user_id)

        conn.commit()
        return {"message": "Factura eliminada correctamente", "quote_reverted": quote_reverted}

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo eliminar", e)
    finally:
        if conn:
            conn.close()


def get_invoice_with_contact(invoice_id: int) -> dict:
    """
    Load an invoice joined with full client and contact info.
    Always use this when building a PDF or sending an email.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                i.id,
                i.quote_id,
                i.invoice_number,
                i.invoice_date,
                i.client_id,
                i.total_amount,
                COALESCE(i.amount_paid, 0) AS amount_paid,
                COALESCE(i.amount_due, i.total_amount) AS amount_due,
                i.status,
                i.notes,
                i.created_at,
                i.updated_at,
                (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = i.created_by_user_id) AS created_by_name,
                i.public_token,
                i.tax_type_code,
                i.tax_rate,
                i.tax_label,
                COALESCE((to_jsonb(i)->>'print_items')::boolean, true) AS print_items,
                -- Same source as the internal invoice PDF (pdf/service.py): the quote, then the invoice.
                q.project_name,
                COALESCE(q.payment_terms, i.payment_terms) AS payment_terms,
                COALESCE(q.valid_until, i.valid_until) AS valid_until,

                c.company_name,
                c.address AS company_address,
                c.tax_id AS company_tax_id,

                ct.name  AS contact_name,
                ct.email AS contact_email,
                ct.phone AS contact_phone

            FROM invoices i
            JOIN clients  c  ON i.client_id  = c.id
            LEFT JOIN quotes q ON TRIM(i.quote_id) = TRIM(q.quote_id)
            JOIN contacts ct ON i.contact_id = ct.id
            WHERE i.id = %s
        """, (invoice_id,))

        row = cursor.fetchone()
        if not row:
            raise api_error(404, "Factura no encontrada", "INVOICE_NOT_FOUND")

        invoice = dict(row)

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (invoice["quote_id"],))
        invoice["items"] = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT included_charges FROM quotes WHERE quote_id = %s", (invoice["quote_id"],))
        quote_row = cursor.fetchone()
        if quote_row:
            raw_charges = quote_row["included_charges"]
            if isinstance(raw_charges, str):
                raw_charges = json.loads(raw_charges)
            invoice["included_charges"] = raw_charges or {}
        else:
            invoice["included_charges"] = {}

        return invoice

    finally:
        if conn:
            conn.close()