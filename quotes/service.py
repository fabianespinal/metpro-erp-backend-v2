# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
import json
import uuid
from datetime import datetime, date
from database import get_db_connection
from core.errors import internal_error
from psycopg2.extras import RealDictCursor, execute_values

INS_SQL = "INSERT INTO quote_items (quote_id, product_name, quantity, unit_price, discount_type, discount_value) VALUES %s"
# Create and update paths. Requires quoting_v1 migration (item_type, description).
INS_ITEMS_SQL = (
    "INSERT INTO quote_items (quote_id, product_name, quantity, unit_price, discount_type, "
    "discount_value, item_type, description, product_id) VALUES %s"
)
QUOTE_STATUS_FINAL = "Final"
FINAL_ALLOWED_NEXT = ("Approved", "Invoiced", "Rejected")
# Duplicate path only. Requires quoting_v1 migration (item_type, description).
INS_DUP_SQL = (
    "INSERT INTO quote_items (quote_id, product_id, product_name, quantity, unit_price, "
    "discount_type, discount_value, item_type, description) VALUES %s"
)


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
    """Random UUID4. Not guessable, no same-second collisions."""
    return str(uuid.uuid4())


def _serialize_date(d) -> Optional[str]:
    """Convert a date object to ISO string for psycopg2, or pass None through."""
    if d is None:
        return None
    if isinstance(d, date):
        return d.isoformat()
    return d  # already a string — let Postgres handle it


def _compute_quote_totals(items: List[dict], charges: dict) -> dict:
    """Totals via quotes.totals.compute_totals (quoting v1).

    Lazy import: quotes.totals imports calculate_quote_totals from this module.
    """
    from quotes.totals import compute_totals
    return compute_totals(items, charges)


def _item_as_dict(item) -> dict:
    if hasattr(item, "dict"):
        return item.dict()
    if isinstance(item, str):
        return json.loads(item)
    return item


def _validate_product_ids(cursor, items: List[dict]) -> None:
    """Every supplied product_id must exist in products. None is allowed (service/custom)."""
    ids = {i.get("product_id") for i in items if i.get("product_id") is not None}
    if not ids:
        return
    cursor.execute("SELECT id FROM products WHERE id = ANY(%s)", (list(ids),))
    found = {r["id"] for r in cursor.fetchall()}
    if ids - found:
        raise api_error(400, "Product not found", "PRODUCT_NOT_FOUND")


def preview_totals(items: List[dict], charges: dict) -> dict:
    """Stateless totals for the take-off screen. No DB access, no writes."""
    t = _compute_quote_totals(items, charges)
    return {
        "items_total": t["items_total"],
        "total_discounts": t["total_discounts"],
        "items_after_discount": t["items_after_discount"],
        "supervision": t["supervision"],
        "admin": t["admin"],
        "insurance": t["insurance"],
        "transport": t["transport"],
        "contingency": t["contingency"],
        "subtotal": t["subtotal_general"],
        "tax_rate": t["tax_rate"],
        "tax_amount": t["tax_amount"],
        "grand_total": t["grand_total"],
    }


def _totals_columns(totals: dict) -> tuple:
    """Values for subtotal, discount_total, tax_amount, grand_total, total_amount."""
    return (
        totals["subtotal_general"],
        totals["total_discounts"],
        totals["tax_amount"],
        totals["grand_total"],
        totals["grand_total"],  # total_amount kept equal to grand_total (legacy readers)
    )


TOTALS_UPDATE_SQL = """
    UPDATE quotes
    SET subtotal = %s,
        discount_total = %s,
        tax_amount = %s,
        grand_total = %s,
        total_amount = %s
    WHERE quote_id = %s
"""


# =============================================================================
# SECTION 3: QUOTE CRUD OPERATIONS
# =============================================================================
def create_quote(
    client_id: int,
    contact_id: int,
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
            raise api_error(404, "Client not found", "CLIENT_NOT_FOUND")

        # Validate that the contact belongs to the selected client
        cursor.execute(
            "SELECT id FROM contacts WHERE id = %s AND company_id = %s",
            (contact_id, client_id),
        )
        if not cursor.fetchone():
            raise api_error(400, f"Contact {contact_id} does not belong to client {client_id}", "CONTACT_CLIENT_MISMATCH")

        _validate_product_ids(cursor, items)
        quote_id = generate_quote_id()
        totals = _compute_quote_totals(items, included_charges)

        # public_token is not set here. It stays NULL until finalize.
        cursor.execute("""
            INSERT INTO quotes
                (quote_id, client_id, contact_id, project_name, notes, status,
                 included_charges, total_amount, payment_terms, valid_until,
                 subtotal, discount_total, tax_amount, grand_total)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
        """, (
            quote_id,
            client_id,
            contact_id,
            project_name,
            notes,
            "Draft",
            json.dumps(included_charges),
            totals["grand_total"],
            payment_terms,
            _serialize_date(valid_until),
            totals["subtotal_general"],
            totals["total_discounts"],
            totals["tax_amount"],
            totals["grand_total"],
        ))

        rows = [
            (
                quote_id,
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_type", "none"),
                item.get("discount_value", 0.0),
                item.get("item_type") or "product",
                item.get("description"),
                item.get("product_id"),
            )
            for item in items
        ]
        if rows:
            execute_values(cursor, INS_ITEMS_SQL, rows)

        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   subtotal, discount_total, tax_amount, grand_total,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        quote["items"] = cursor.fetchall()

        return quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to create quote", e)

    finally:
        if conn:
            conn.close()


def get_quote_by_id(quote_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, subtotal, discount_total,
                   tax_amount, grand_total, terms, payment_terms, valid_until,
                   finalized_at, public_token, created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = cursor.fetchone()

        if not quote:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        quote = dict(quote)

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        quote["items"] = cursor.fetchall()

        return quote

    finally:
        if conn:
            conn.close()


def quote_id_for_public_token(token: str) -> str:
    """Resolve a public token to quotes.quote_id. 404 when not found."""
    from fastapi import HTTPException
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT quote_id FROM quotes WHERE public_token = %s", (token,))
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")
    return row["quote_id"]


def get_quote_with_contact(quote_id: str) -> dict:
    """
    Load a quote joined with full client and selected contact info.
    Always use this function when building a PDF — never get_quote_by_id.
    The contact comes from quotes.contact_id, not from any company default.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT
                q.quote_id,
                q.public_token,
                q.client_id,
                q.contact_id,
                q.project_name,
                q.notes,
                q.status,
                q.included_charges,
                q.total_amount,
                q.subtotal,
                q.discount_total,
                q.tax_amount,
                q.grand_total,
                q.payment_terms,
                q.valid_until,
                q.created_at,
                q.updated_at,

                c.company_name,
                c.address        AS company_address,

                ct.name          AS contact_name,
                ct.email         AS contact_email,
                ct.phone         AS contact_phone

            FROM quotes q
            JOIN clients  c  ON q.client_id  = c.id
            JOIN contacts ct ON q.contact_id = ct.id AND ct.company_id = q.client_id
            WHERE q.quote_id = %s
        """, (quote_id,))
        row = cursor.fetchone()

        if not row:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        quote = dict(row)

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
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


# Edit policy toggle.
#   True  -> quotes can be edited in any status (current main/production behavior).
#   False -> only Draft quotes can be edited (dev behavior, PR-era rule).
ALLOW_EDIT_NON_DRAFT_QUOTES = False  # Business rule: only Draft quotes are editable.


def update_quote(quote_id: str, quote_update) -> dict:
    """Update an existing quote."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s", (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        # Finalized quotes are locked regardless of ALLOW_EDIT_NON_DRAFT_QUOTES.
        if quote["status"] == QUOTE_STATUS_FINAL:
            raise api_error(400, "Finalized quotes cannot be edited", "QUOTE_FINALIZED")

        if not ALLOW_EDIT_NON_DRAFT_QUOTES and quote["status"] != "Draft":
            raise api_error(400, "Only Draft quotes can be edited", "QUOTE_NOT_DRAFT")

        update_dict = quote_update.dict(exclude_unset=True)

        # Pull these out — they're handled separately below.
        items = update_dict.pop('items', None)
        included_charges = update_dict.pop('included_charges', None)

        if 'valid_until' in update_dict and update_dict['valid_until'] is not None:
            update_dict['valid_until'] = _serialize_date(update_dict['valid_until'])

        # Scalar fields update
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
            _validate_product_ids(cursor, [_item_as_dict(i) for i in items])
            cursor.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))

            normalized = []
            for item in items:
                # Normalize — item may be a dict or a Pydantic model
                if hasattr(item, 'dict'):
                    item = item.dict()
                elif isinstance(item, str):
                    item = json.loads(item)
                normalized.append(item)

            rows = [
                (
                    quote_id,
                    item.get("product_name", ""),
                    item.get("quantity", 1),
                    item.get("unit_price", 0),
                    item.get("discount_type", "none"),
                    item.get("discount_value", 0.0),
                    item.get("item_type") or "product",
                    item.get("description"),
                    item.get("product_id"),
                )
                for item in normalized
            ]
            if rows:
                execute_values(cursor, INS_ITEMS_SQL, rows)

        # Recalculate totals if items or charges changed
        if included_charges is not None or items is not None:
            cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
            current_items = [dict(row) for row in cursor.fetchall()]

            if included_charges is not None:
                if hasattr(included_charges, 'dict'):
                    charges = included_charges.dict()
                elif isinstance(included_charges, str):
                    charges = json.loads(included_charges)
                else:
                    charges = included_charges
            else:
                cursor.execute(
                    "SELECT included_charges FROM quotes WHERE quote_id = %s", (quote_id,)
                )
                row = cursor.fetchone()
                raw = row['included_charges'] if row else {}
                if isinstance(raw, str):
                    charges = json.loads(raw)
                else:
                    charges = raw or {}

            totals = _compute_quote_totals(current_items, charges)

            cursor.execute("""
                UPDATE quotes
                SET included_charges = %s::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quote_id = %s
            """, (json.dumps(charges), quote_id))
            cursor.execute(TOTALS_UPDATE_SQL, _totals_columns(totals) + (quote_id,))

        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        updated_quote = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        updated_quote["items"] = cursor.fetchall()

        return updated_quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to update quote", e)

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
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        conn.commit()
        return {"message": "Quote deleted successfully"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Delete failed", e)

    finally:
        if conn:
            conn.close()


# =============================================================================
# SECTION 4: QUOTE BUSINESS LOGIC
# =============================================================================
def duplicate_quote(quote_id: str) -> dict:
    """Duplicate an existing quote into a new Draft.

    Copies: client, contact, project, notes (exact), included_charges,
    total_amount, payment_terms, terms, valid_until, and every item
    (product_id, product_name, quantity, unit_price, discount, item_type,
    description). Resets: status = Draft, public_token = NULL, finalized_at
    not copied.

    Requires quoting_v1 migration (terms, item_type, description,
    public_token nullable). Do not deploy this code before that migration.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Fetch original quote
        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until, terms,
                   subtotal, discount_total, tax_amount, grand_total
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        original = cursor.fetchone()
        if not original:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        original = dict(original)

        # 2. Fetch original items
        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
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
                (quote_id, client_id, contact_id, project_name, notes, status,
                 included_charges, total_amount, payment_terms, terms,
                 valid_until, subtotal, discount_total, tax_amount, grand_total, public_token)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, (
            new_quote_id,
            original["client_id"],
            original["contact_id"],
            original.get("project_name"),
            original.get("notes"),
            "Draft",
            included_charges,
            original["total_amount"],
            original.get("payment_terms"),
            original.get("terms"),
            valid_until,
            original.get("subtotal"),
            original.get("discount_total"),
            original.get("tax_amount"),
            original.get("grand_total"),
        ))

        # 7. Duplicate quote items (product_id, item_type, description kept)
        rows = [
            (
                new_quote_id,
                item.get("product_id"),
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_type") or "none",
                item.get("discount_value") or 0.0,
                item.get("item_type") or "product",
                item.get("description"),
            )
            for item in original_items
        ]
        if rows:
            execute_values(cursor, INS_DUP_SQL, rows)

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

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (new_quote_id,))
        new_quote["items"] = cursor.fetchall()

        return new_quote

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to duplicate quote", e)

    finally:
        if conn:
            conn.close()


def finalize_quote(quote_id: str) -> dict:
    """Draft -> Final. Persists totals, sets finalized_at, generates public_token.

    public_token is generated only if NULL, so an existing link keeps working
    if a finalized quote is ever re-finalized (not reachable today: Final is locked).
    Requires quoting_v1 migration.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute(
            "SELECT quote_id, status, included_charges FROM quotes WHERE quote_id = %s FOR UPDATE",
            (quote_id,),
        )
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")
        if quote["status"] != "Draft":
            raise api_error(400, "Only Draft quotes can be finalized", "QUOTE_NOT_DRAFT")

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        current_items = [dict(row) for row in cursor.fetchall()]
        if not current_items:
            raise api_error(400, "Quote must have at least one item to finalize", "QUOTE_EMPTY")

        raw = quote.get("included_charges") or {}
        if isinstance(raw, str):
            raw = json.loads(raw) if raw else {}
        totals = _compute_quote_totals(current_items, raw)

        cursor.execute(
            """
            UPDATE quotes
            SET status = %s,
                finalized_at = CURRENT_TIMESTAMP,
                public_token = COALESCE(public_token, %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE quote_id = %s
            """,
            (QUOTE_STATUS_FINAL, str(uuid.uuid4()), quote_id),
        )
        cursor.execute(TOTALS_UPDATE_SQL, _totals_columns(totals) + (quote_id,))
        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   subtotal, discount_total, tax_amount, grand_total,
                   finalized_at, created_at, updated_at
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        result = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        result["items"] = cursor.fetchall()
        return result

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to finalize quote", e)

    finally:
        if conn:
            conn.close()


def update_quote_status(quote_id: str, status: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Row lock: serializes concurrent status changes (approve vs finalize, convert).
        cursor.execute("SELECT quote_id, status FROM quotes WHERE quote_id = %s FOR UPDATE", (quote_id,))
        current = cursor.fetchone()
        if not current:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        valid_statuses = ["Draft", "Sent", "Approved", "Rejected", "Invoiced", QUOTE_STATUS_FINAL]
        if status not in valid_statuses:
            raise api_error(400, f"Invalid status. Must be one of: {valid_statuses}", "QUOTE_STATUS_INVALID")

        # Final is set only by finalize (it generates public_token and totals).
        if status == QUOTE_STATUS_FINAL:
            raise api_error(400, "Use the finalize endpoint to set Final", "QUOTE_USE_FINALIZE")

        # Final may move forward (Approved, Invoiced) or to Rejected only.
        # Final -> Draft / Sent is blocked. Content edits stay locked (update_quote).
        if current["status"] == QUOTE_STATUS_FINAL and status not in FINAL_ALLOWED_NEXT:
            raise api_error(400, "Finalized quotes can only move to Approved, Rejected or Invoiced", "QUOTE_FINALIZED")

        # Approval and invoicing require a finalized quote. A Draft cannot jump
        # to Approved or Invoiced: it would have no public_token and no totals lock.
        if status == "Approved" and current["status"] != QUOTE_STATUS_FINAL:
            raise api_error(400, "Quote must be finalized before it can be approved", "QUOTE_NOT_FINALIZED")
        if status == "Invoiced" and current["status"] not in (QUOTE_STATUS_FINAL, "Approved"):
            raise api_error(400, "Quote must be finalized before it can be invoiced", "QUOTE_NOT_FINALIZED")

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
        raise internal_error("Failed to update status", e)

    finally:
        if conn:
            conn.close()


def convert_quote_to_invoice(quote_id: str) -> dict:
    """Convert an approved quote to an invoice."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Load quote
        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, grand_total, payment_terms, valid_until
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Quote not found", "QUOTE_NOT_FOUND")

        quote = dict(quote)

        if quote["status"] != "Approved":
            raise api_error(400, "Only approved quotes can be converted to invoices", "QUOTE_NOT_APPROVED")

        # 2. Prevent duplicate invoices
        cursor.execute("SELECT id FROM invoices WHERE quote_id = %s", (quote_id,))
        if cursor.fetchone():
            raise api_error(400, "Invoice already exists for this quote", "INVOICE_EXISTS")

        # 3. Load quote items (deterministic order)
        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        items = [dict(row) for row in cursor.fetchall()]

        raw_charges = quote.get("included_charges")
        charges = json.loads(raw_charges) if isinstance(raw_charges, str) else (raw_charges or {})

        # Invoice total is the stored grand_total set at finalize/save.
        # Recompute only for legacy rows that have no stored total.
        if quote.get("grand_total") is not None:
            invoice_total = float(quote["grand_total"])
        else:
            invoice_total = calculate_quote_totals(items, charges)["grand_total"]

        # 4. Create invoice
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        invoice_number = f"INV-{timestamp}"
        invoice_date = datetime.now().strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO invoices
                (quote_id, invoice_number, invoice_date, client_id, contact_id,
                 total_amount, status, notes, payment_terms, valid_until)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            quote_id,
            invoice_number,
            invoice_date,
            quote["client_id"],
            quote["contact_id"],
            invoice_total,
            "Pending",
            quote.get("notes"),
            quote.get("payment_terms"),
            _serialize_date(quote.get("valid_until")),
        ))

        invoice_id = cursor.fetchone()["id"]   # FIXED

        # 5. Insert invoice items
        invoice_item_rows = [
            (
                invoice_id,
                item["product_id"],
                item["product_name"],
                item["quantity"],
                item["unit_price"],
                item.get("discount_value", 0),
                (item["quantity"] * item["unit_price"]) - item.get("discount_value", 0),
            )
            for item in items
        ]
        if invoice_item_rows:
            execute_values(
                cursor,
                "INSERT INTO invoice_items (invoice_id, product_id, description, quantity, unit_price, discount, total) VALUES %s",
                invoice_item_rows,
            )

        # Same transaction: the quote moves to Invoiced with the invoice.
        cursor.execute(
            "UPDATE quotes SET status = 'Invoiced' WHERE quote_id = %s AND status = 'Approved'",
            (quote_id,),
        )
        conn.commit()

        # 6. Return invoice with items
        cursor.execute("""
            SELECT i.*, q.payment_terms, q.valid_until
            FROM invoices i
            JOIN quotes q ON i.quote_id = q.quote_id
            WHERE i.id = %s
        """, (invoice_id,))                     # FIXED
        new_invoice = dict(cursor.fetchone())

        cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = %s", (invoice_id,))  # FIXED
        new_invoice["items"] = cursor.fetchall()

        return new_invoice

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to convert quote to invoice", e)

    finally:
        if conn:
            conn.close()
