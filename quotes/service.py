# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
from typing import List, Optional
from fastapi import HTTPException
import json
from datetime import datetime, date
from database import get_db_connection
from psycopg2.extras import RealDictCursor


# =============================================================================
# SECTION 2: HELPER FUNCTIONS
# =============================================================================
def calculate_quote_totals(items: List[dict], charges: dict) -> dict:
    items_total = sum(float(item['quantity'] or 0) * float(item['unit_price'] or 0) for item in items)
    total_discounts = 0
    for item in items:
        subtotal = float(item['quantity'] or 0) * float(item['unit_price'] or 0)
        if item.get('discount_type') == 'percentage':
            total_discounts += subtotal * (float(item.get('discount_value', 0)) / 100)
        elif item.get('discount_type') == 'fixed':
            total_discounts += float(item.get('discount_value', 0))

    items_after_discount = items_total - total_discounts

    supervision_pct = float(charges.get('supervision_percentage', 10.0))
    admin_pct = float(charges.get('admin_percentage', 4.0))
    insurance_pct = float(charges.get('insurance_percentage', 1.0))
    transport_pct = float(charges.get('transport_percentage', 3.0))
    contingency_pct = float(charges.get('contingency_percentage', 3.0))

    supervision = items_after_discount * (supervision_pct / 100) if charges.get('supervision') else 0
    admin = items_after_discount * (admin_pct / 100) if charges.get('admin') else 0
    insurance = items_after_discount * (insurance_pct / 100) if charges.get('insurance') else 0
    transport = items_after_discount * (transport_pct / 100) if charges.get('transport') else 0
    contingency = items_after_discount * (contingency_pct / 100) if charges.get('contingency') else 0

    subtotal_general = items_after_discount + supervision + admin + insurance + transport + contingency
    itbis = subtotal_general * 0.18
    grand_total = subtotal_general + itbis

    return {
        'items_total': items_total,
        'total_discounts': total_discounts,
        'items_after_discount': items_after_discount,
        'supervision': supervision,
        'admin': admin,
        'insurance': insurance,
        'transport': transport,
        'contingency': contingency,
        'subtotal_general': subtotal_general,
        'itbis': itbis,
        'grand_total': grand_total
    }


def generate_quote_id() -> str:
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"Q-{timestamp}"


def _serialize_date(d) -> Optional[str]:
    """Convert a date object to ISO string for psycopg2, or pass None through."""
    if d is None:
        return None
    if isinstance(d, date):
        return d.isoformat()
    return d  # already a string — let Postgres handle it


# =============================================================================
# SECTION 3: QUOTE CRUD OPERATIONS
# =============================================================================
def create_quote(
    client_id: int,
    project_name: Optional[str],
    notes: Optional[str],
    items: List[dict],
    included_charges: dict,
    payment_terms: Optional[str] = None,
    valid_until: Optional[date] = None,
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Client not found")

        quote_id = generate_quote_id()
        totals = calculate_quote_totals(items, included_charges)

        cursor.execute("""
            INSERT INTO quotes
                (quote_id, client_id, project_name, notes, status,
                 included_charges, total_amount, payment_terms, valid_until)
            VALUES
                (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        """, (
            quote_id,
            client_id,
            project_name,
            notes,
            "Draft",
            json.dumps(included_charges),
            totals["grand_total"],
            payment_terms,
            _serialize_date(valid_until),
        ))

        for item in items:
            cursor.execute("""
                INSERT INTO quote_items
                    (quote_id, product_name, quantity, unit_price, discount_type, discount_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                quote_id,
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_type", "none"),
                item.get("discount_value", 0.0),
            ))

        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        quote["items"] = cursor.fetchall()

        return quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create quote: {str(e)}")

    finally:
        if conn:
            conn.close()


def get_quote_by_id(quote_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = cursor.fetchone()

        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        quote = dict(quote)

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        quote["items"] = cursor.fetchall()

        return quote

    finally:
        if conn:
            conn.close()


def get_all_quotes(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = """
            SELECT q.quote_id, q.client_id, q.project_name, q.notes, q.status,
                   q.included_charges, q.total_amount, q.payment_terms, q.valid_until,
                   q.created_at, q.updated_at,
                   c.company_name AS client_name
            FROM quotes q
            JOIN clients c ON q.client_id = c.id
            WHERE 1=1
        """
        params = []

        if client_id:
            query += " AND q.client_id = %s"
            params.append(client_id)

        if status:
            query += " AND q.status = %s"
            params.append(status)

        query += " ORDER BY q.id DESC"

        cursor.execute(query, params)
        return cursor.fetchall()

    finally:
        if conn:
            conn.close()


def update_quote(quote_id: str, quote_update) -> dict:
    """Update an existing quote. Only Draft quotes can be edited."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        if quote['status'] != 'Draft':
            raise HTTPException(
                status_code=400,
                detail="Only Draft quotes can be edited"
            )

        update_dict = quote_update.dict(exclude_unset=True)

        # Pull these out — they're handled separately below.
        items = update_dict.pop('items', None)
        included_charges = update_dict.pop('included_charges', None)

        # valid_until comes in as a date object from Pydantic. Serialize it
        # so psycopg2 doesn't choke when building the dynamic SET clause.
        if 'valid_until' in update_dict and update_dict['valid_until'] is not None:
            update_dict['valid_until'] = _serialize_date(update_dict['valid_until'])

        # Scalar fields update (project_name, notes, payment_terms, valid_until)
        if update_dict:
            set_clause = ", ".join([f"{key} = %s" for key in update_dict.keys()])
            query = f"""
                UPDATE quotes
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE quote_id = %s
            """
            cursor.execute(query, list(update_dict.values()) + [quote_id])

        # Re-insert items if provided
        if items is not None:
            cursor.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))

            for item in items:
                cursor.execute("""
                    INSERT INTO quote_items
                        (quote_id, product_name, quantity, unit_price, discount_type, discount_value)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    quote_id,
                    item["product_name"],
                    item["quantity"],
                    item["unit_price"],
                    item.get("discount_type", "none"),
                    item.get("discount_value", 0.0),
                ))

        # Recalculate totals if items or charges changed
        if included_charges is not None or items is not None:
            cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
            current_items = [dict(row) for row in cursor.fetchall()]

            if included_charges is not None:
                charges = included_charges.dict() if hasattr(included_charges, 'dict') else included_charges
            else:
                cursor.execute(
                    "SELECT included_charges FROM quotes WHERE quote_id = %s", (quote_id,)
                )
                row = cursor.fetchone()
                charges = row['included_charges'] if row else {}

            totals = calculate_quote_totals(current_items, charges)

            cursor.execute("""
                UPDATE quotes
                SET included_charges = %s::jsonb,
                    total_amount = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quote_id = %s
            """, (json.dumps(charges), totals["grand_total"], quote_id))

        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        updated_quote = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        updated_quote["items"] = cursor.fetchall()

        return updated_quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update quote: {str(e)}")

    finally:
        if conn:
            conn.close()


def delete_quote(quote_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        cursor.execute("DELETE FROM quotes WHERE quote_id = %s", (quote_id,))

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Quote not found")

        conn.commit()
        return {"message": "Quote deleted successfully"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    finally:
        if conn:
            conn.close()


# =============================================================================
# SECTION 4: QUOTE BUSINESS LOGIC
# =============================================================================
def duplicate_quote(quote_id: str) -> dict:
    """Duplicate an existing quote with a new ID. Copies payment_terms and valid_until."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Fetch original quote
        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        original = cursor.fetchone()
        if not original:
            raise HTTPException(status_code=404, detail="Quote not found")

        original = dict(original)

        # 2. Fetch original items
        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        original_items = cursor.fetchall()

        # 3. Generate new quote ID
        new_quote_id = generate_quote_id()

        # 4. Normalize included_charges — it may arrive as dict or string
        included_charges = original.get("included_charges") or ""
        if isinstance(included_charges, dict):
            included_charges = json.dumps(included_charges)
        elif not isinstance(included_charges, str):
            included_charges = ""

        # 5. valid_until — serialize date to string if needed
        valid_until = _serialize_date(original.get("valid_until"))

        # 6. Insert duplicated quote
        cursor.execute("""
            INSERT INTO quotes
                (quote_id, client_id, project_name, notes, status,
                 included_charges, total_amount, payment_terms, valid_until)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        """, (
            new_quote_id,
            original["client_id"],
            original.get("project_name"),
            f"[DUPLICATE] {original.get('notes', '')}" if original.get("notes") else None,
            "Draft",
            included_charges,
            original["total_amount"],
            original.get("payment_terms"),
            valid_until,
        ))

        # 7. Duplicate quote items
        for item in original_items:
            cursor.execute("""
                INSERT INTO quote_items
                    (quote_id, product_name, quantity, unit_price, discount_type, discount_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                new_quote_id,
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_type") or "none",
                item.get("discount_value") or 0.0,
            ))

        conn.commit()

        # 8. Return new quote with items
        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (new_quote_id,))
        new_quote = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (new_quote_id,))
        new_quote["items"] = cursor.fetchall()

        return new_quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to duplicate quote: {str(e)}")

    finally:
        if conn:
            conn.close()


def update_quote_status(quote_id: str, status: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT quote_id FROM quotes WHERE quote_id = %s", (quote_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Quote not found")

        valid_statuses = ["Draft", "Sent", "Approved", "Rejected", "Invoiced"]
        if status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {valid_statuses}"
            )

        cursor.execute(
            "UPDATE quotes SET status = %s WHERE quote_id = %s", (status, quote_id)
        )
        conn.commit()

        return {"message": "Status updated successfully", "quote_id": quote_id, "status": status}

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")

    finally:
        if conn:
            conn.close()


def convert_quote_to_invoice(quote_id: str) -> dict:
    """Convert an approved quote to an invoice."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
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
        if isinstance(raw_charges, str):
            charges = json.loads(raw_charges)
        else:
            charges = raw_charges or {}

        totals = calculate_quote_totals(items, charges)

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        invoice_number = f"INV-{timestamp}"
        invoice_date = datetime.now().strftime("%Y-%m-%d")

        # payment_terms and valid_until are passed through to the invoice
        # so the PDF context has everything it needs.
        cursor.execute("""
            INSERT INTO invoices
                (quote_id, invoice_number, invoice_date, client_id,
                 total_amount, status, notes, payment_terms, valid_until)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            quote_id,
            invoice_number,
            invoice_date,
            quote["client_id"],
            totals["grand_total"],
            "Pending",
            quote.get("notes"),
            quote.get("payment_terms"),
            _serialize_date(quote.get("valid_until")),
        ))

        invoice_id = cursor.fetchone()["id"]

        # Insert invoice items
        for item in items:
            line_total = (item["quantity"] * item["unit_price"]) - item.get("discount_value", 0)
            cursor.execute("""
                INSERT INTO invoice_items
                    (invoice_id, product_id, description, quantity, unit_price, discount, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                invoice_id,
                item["product_id"],
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_value", 0),
                line_total,
            ))

        conn.commit()

        cursor.execute("""
            SELECT i.*,
                   q.payment_terms,
                   q.valid_until
            FROM invoices i
            JOIN quotes q ON i.quote_id = q.quote_id
            WHERE i.id = %s
        """, (invoice_id,))
        new_invoice = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        new_invoice["items"] = cursor.fetchall()

        return new_invoice

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to convert quote to invoice: {str(e)}")

    finally:
        if conn:
            conn.close()
