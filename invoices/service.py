from typing import List, Optional
from fastapi import HTTPException
from datetime_t import datetime
import json
from database import get_db_connection
from psycopg2.extras import RealDictCursor

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

def create_invoice_from_quote(quote_id: str, notes: Optional[str] = None) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        quote = dict(quote)

        if quote["status"] != "Approved":
            raise HTTPException(
                status_code=400,
                detail="Only approved quotes can be converted to invoices",
            )

        cursor.execute("SELECT id FROM invoices WHERE quote_id = %s", (quote_id,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Invoice already exists for this quote",
            )

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        items = [dict(row) for row in cursor.fetchall()]

        raw_charges = quote.get("included_charges")
        try:
            if isinstance(raw_charges, str):
                charges = json.loads(raw_charges)
            else:
                charges = raw_charges or {}
        except Exception:
            charges = {
                "supervision": True,
                "supervision_percentage": 10.0,
                "admin": True,
                "admin_percentage": 4.0,
                "insurance": True,
                "insurance_percentage": 1.0,
                "transport": True,
                "transport_percentage": 3.0,
                "contingency": True,
                "contingency_percentage": 3.0,
            }

        totals = calculate_invoice_totals(items, charges)

        invoice_number = generate_invoice_number()
        invoice_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute(
            """
            INSERT INTO invoices
            (quote_id, invoice_number, invoice_date, client_id, total_amount, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, invoice_number, quote_id, client_id, total_amount, status, invoice_date, notes, created_at, updated_at
            """,
            (
                quote_id,
                invoice_number,
                invoice_date,
                quote["client_id"],
                totals["grand_total"],
                "Pending",
                notes,
            ),
        )

        invoice = dict(cursor.fetchone())

        cursor.execute(
            "UPDATE quotes SET status = 'Invoiced' WHERE quote_id = %s",
            (quote_id,),
        )

        conn.commit()

        invoice["items"] = items
        invoice["totals"] = totals

        return invoice

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create invoice: {str(e)}")
    finally:
        if conn:
            conn.close()

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
                i.status,
                i.notes,
                i.created_at,
                i.updated_at
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

        cursor.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        invoice = dict(invoice)

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (invoice["quote_id"],))
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
            raise HTTPException(status_code=404, detail="Invoice not found")

        return dict(invoice)

    finally:
        if conn:
            conn.close()

def update_invoice_status(invoice_id: int, status: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        valid_statuses = ["Pending", "Paid", "Cancelled", "Overdue"]
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}",
            )

        cursor.execute(
            """
            UPDATE invoices
            SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING *
            """,
            (status, invoice_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Invoice not found")

        conn.commit()

        return dict(cursor.fetchone())

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
    finally:
        if conn:
            conn.close()

def delete_invoice(invoice_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT quote_id FROM invoices WHERE id = %s", (invoice_id,))
        invoice = cursor.fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        quote_id = invoice["quote_id"]

        cursor.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))

        cursor.execute(
            "UPDATE quotes SET status = 'Approved' WHERE quote_id = %s",
            (quote_id,),
        )

        conn.commit()
        return {"message": "Invoice deleted successfully", "quote_reverted": True}

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")
    finally:
        if conn:
            conn.close()

def get_invoice_with_payments(conn, invoice_id):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM invoices WHERE id=%s", (invoice_id,))
        invoice = cur.fetchone()

        cur.execute("SELECT * FROM invoice_payments WHERE invoice_id=%s", (invoice_id,))
        payments = cur.fetchall()

        amount_paid = sum(p["amount"] for p in payments)
        amount_due = invoice["total_amount"] - amount_paid

        invoice["payments"] = payments
        invoice["amount_paid"] = amount_paid
        invoice["amount_due"] = amount_due

        return invoice

def create_payment(conn, invoice_id, data):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO invoice_payments (invoice_id, amount, method, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (invoice_id, data.amount, data.method, data.notes))
        conn.commit()
        return cur.fetchone()["id"]
