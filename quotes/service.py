# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
from typing import List, Optional
from fastapi import HTTPException
import json
from datetime import datetime
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


# =============================================================================
# SECTION 3: QUOTE CRUD OPERATIONS
# =============================================================================
def create_quote(client_id: int, project_name: Optional[str], notes: Optional[str],
                 items: List[dict], included_charges: dict) -> dict:
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
            (quote_id, client_id, project_name, notes, status, included_charges, total_amount)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
        """, (
            quote_id,
            client_id,
            project_name,
            notes,
            "Draft",
            json.dumps(included_charges),
            totals["grand_total"]
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
                item.get("discount_value", 0.0)
            ))

        conn.commit()

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        quote = cursor.fetchone()

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
        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        quote = cursor.fetchone()

        if not quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        quote["items"] = cursor.fetchall()

        return quote

    finally:
        if conn:
            conn.close()


def get_all_quotes(client_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        query = """
            SELECT q.*, c.company_name AS client_name
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
    """Update existing quote - only allowed for Draft status"""
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
        
        items = update_dict.pop('items', None)
        included_charges = update_dict.pop('included_charges', None)

        if update_dict:
            set_clause = ", ".join([f"{key} = %s" for key in update_dict.keys()])
            query = f"UPDATE quotes SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s"
            cursor.execute(query, list(update_dict.values()) + [quote_id])

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
                    item.get("discount_value", 0.0)
                ))

        if included_charges is not None or items is not None:
            cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
            current_items = [dict(row) for row in cursor.fetchall()]
            
            if included_charges is not None:
                charges = included_charges.dict() if hasattr(included_charges, 'dict') else included_charges
            else:
                cursor.execute("SELECT included_charges FROM quotes WHERE quote_id = %s", (quote_id,))
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

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        updated_quote = cursor.fetchone()
        
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
    """Duplicate existing quote with new ID"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        original_quote = cursor.fetchone()
        if not original_quote:
            raise HTTPException(status_code=404, detail="Quote not found")

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s", (quote_id,))
        original_items = [dict(row) for row in cursor.fetchall()]

        new_quote_id = generate_quote_id()
        current_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO quotes
            (quote_id, client_id, date, project_name, notes, status, included_charges, total_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """, (
            new_quote_id,
            original_quote["client_id"],
            current_date,
            original_quote.get("project_name"),
            f"[DUPLICATE] {original_quote.get('notes', '')}" if original_quote.get('notes') else None,
            "Draft",
            json.dumps(original_quote["included_charges"]),
            original_quote["total_amount"]
        ))

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
                item.get("discount_type", "none"),
                item.get("discount_value", 0.0)
            ))

        conn.commit()

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (new_quote_id,))
        new_quote = cursor.fetchone()

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

        cursor.execute("UPDATE quotes SET status = %s WHERE quote_id = %s", (status, quote_id))
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
    """Convert approved quote to invoice"""
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
        if isinstance(raw_charges, str):
            charges = json.loads(raw_charges)
        else:
            charges = raw_charges or {}

        totals = calculate_quote_totals(items, charges)

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        invoice_number = f"INV-{timestamp}"
        invoice_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO invoices
            (quote_id, invoice_number, invoice_date, client_id, total_amount, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            quote_id,
            invoice_number,
            invoice_date,
            quote["client_id"],
            totals["grand_total"],
            "Pending",
            quote.get("notes"),
        ))

        invoice_id = cursor.fetchone()["id"]

        for item in items:
            cursor.execute(
                "SELECT id FROM products WHERE name = %s",
                (item["product_name"],)
            )
            product_row = cursor.fetchone()

            if not product_row:
                raise HTTPException(
                    status_code=500,
                    detail=f"Product '{item['product_name']}' not found in products table"
                )

            uuid_product_id = product_row["id"]

            line_total = (item["quantity"] * item["unit_price"]) - item.get("discount_value", 0)

            cursor.execute("""
                INSERT INTO invoice_items
                (invoice_id, product_id, description, quantity, unit_price, discount, total)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                invoice_id,
                uuid_product_id,
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_value", 0),
                line_total
            ))

        conn.commit()

        cursor.execute("SELECT * FROM invoices WHERE id = %s", (invoice_id,))
        new_invoice = cursor.fetchone()
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