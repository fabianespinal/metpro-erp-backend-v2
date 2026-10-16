from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
from datetime import datetime
import json
from database import get_db_connection
from core.errors import internal_error
from psycopg2.extras import RealDictCursor
import logging

logger = logging.getLogger("metpro.invoices")


def generate_invoice_number() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"INV-{timestamp}"


def calculate_invoice_totals(items: List[dict], charges: dict) -> dict:
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
    invoice_items has no line-order column; ctid keeps insertion order because
    these rows are never updated. A line_no column is prepared in migrations.
    """
    cursor.execute(
        "SELECT description, quantity, unit_price, discount, total, product_id "
        "FROM invoice_items WHERE invoice_id = %s ORDER BY ctid",
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

    totals = calculate_invoice_totals(items, charges or {})
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
            raise internal_error("Invoice created but notes could not be saved", e)
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

        return [dict(row) for row in cursor.fetchall()]
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
            raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

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
            "WHERE invoice_id = %s ORDER BY ctid",
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

            totals = calculate_invoice_totals(items, charges)
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
            raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

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


def update_invoice_status(invoice_id: int, status: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if status not in INVOICE_STATUSES:
            raise api_error(400, f"Invalid status. Must be one of: {list(INVOICE_STATUSES)}", "INVOICE_STATUS_INVALID")

        cursor.execute(
            "SELECT id, status, COALESCE(amount_paid, 0) AS amount_paid FROM invoices WHERE id = %s FOR UPDATE",
            (invoice_id,),
        )
        current = cursor.fetchone()
        if not current:
            raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

        if status != current["status"]:
            if status == "Paid":
                raise api_error(400, "Invoices become Paid by recording payments", "INVOICE_PAID_VIA_PAYMENTS")
            allowed = MANUAL_INVOICE_TRANSITIONS.get(current["status"], set())
            if status not in allowed:
                raise api_error(400, f"Cannot change invoice from {current['status']} to {status}", "INVOICE_TRANSITION_INVALID")
            if status == "Cancelled" and float(current["amount_paid"]) > 0:
                raise api_error(400, "Invoice has payments and cannot be cancelled", "INVOICE_HAS_PAYMENTS")

            cursor.execute(
                "UPDATE invoices SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (status, invoice_id),
            )
            conn.commit()

        return get_invoice_by_id(invoice_id)

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Update failed", e)
    finally:
        if conn:
            conn.close()


def delete_invoice(invoice_id: int) -> dict:
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
            raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

        cursor.execute("SELECT COUNT(*) AS n FROM invoice_payments WHERE invoice_id = %s", (invoice_id,))
        if cursor.fetchone()["n"] > 0:
            raise api_error(400, "Invoice has payments and cannot be deleted", "INVOICE_HAS_PAYMENTS")

        quote_id = invoice["quote_id"]

        cursor.execute("DELETE FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        cursor.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
        quote_reverted = False
        if quote_id:
            cursor.execute(
                "UPDATE quotes SET status = 'Approved' WHERE quote_id = %s AND status = 'Invoiced'",
                (quote_id,),
            )
            quote_reverted = cursor.rowcount > 0

        conn.commit()
        return {"message": "Invoice deleted successfully", "quote_reverted": quote_reverted}

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Delete failed", e)
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

                c.company_name,
                c.address AS company_address,

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
            raise api_error(404, "Invoice not found", "INVOICE_NOT_FOUND")

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