# =============================================================================
# SECTION 1: IMPORTS
# =============================================================================
from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
import json
import uuid
from datetime import datetime, date
import logging
from database import get_db_connection
from core.errors import internal_error
from quotes.dynamic_charges import dynamic_charges_total
from core.numbering import invoice_label
from estimator.quote_lock import ADMIN_ROLES, is_estimate, money_changes
from psycopg2.extras import RealDictCursor, execute_values
from core import pdf_options
from core import status_history

INS_SQL = "INSERT INTO quote_items (quote_id, product_name, quantity, unit_price, discount_type, discount_value) VALUES %s"
# Create and update paths. Requires quoting_v1 migration (item_type, description).
INS_ITEMS_SQL = (
    "INSERT INTO quote_items (quote_id, product_name, quantity, unit_price, discount_type, "
    "discount_value, item_type, description, product_id, category, print_on_pdf) VALUES %s"
)
logger = logging.getLogger(__name__)

QUOTE_STATUS_FINAL = "Final"
FINAL_ALLOWED_NEXT = ("Approved", "Invoiced", "Rejected")

# Strict quote lifecycle. Manual PATCH /quotes/{id}/status may only follow this map.
#   Draft    -> Final      only via POST /quotes/{id}/finalize
#   Final    -> Sent       only via POST /quotes/{id}/send
#   Approved -> Invoiced   only via POST /quotes/{id}/convert-to-invoice
#   Invoiced -> Approved   only by deleting the invoice
# No status returns to Draft. Rework a quote with Duplicate.
QUOTE_STATUSES = ("Draft", "Final", "Sent", "Approved", "Rejected", "Invoiced")
MANUAL_QUOTE_TRANSITIONS = {
    "Draft": set(),
    "Final": {"Approved", "Rejected"},
    "Sent": {"Approved", "Rejected"},
    "Approved": {"Rejected"},
    "Rejected": set(),
    "Invoiced": set(),
}
# Statuses that may be emailed to the client. Only Final moves to Sent.
SENDABLE_STATUSES = ("Final", "Sent", "Approved")
# Statuses that may be deleted. Anything finalized is kept for the record.
DELETABLE_STATUSES = ("Draft", "Rejected")
# Duplicate path only. Requires quoting_v1 migration (item_type, description).
INS_DUP_SQL = (
    "INSERT INTO quote_items (quote_id, product_id, product_name, quantity, unit_price, "
    "discount_type, discount_value, item_type, description, category, print_on_pdf) VALUES %s"
)


# =============================================================================
# SECTION 2: HELPER FUNCTIONS
# =============================================================================
# Pre-A1 rate. Used only when a caller passes no rate (parity tests, subtotal-only callers).
# Documents carry their own snapshot (quotes.tax_rate / invoices.tax_rate).
LEGACY_TAX_RATE = 0.18


def calculate_quote_totals(items: List[dict], charges: dict, tax_rate: Optional[float] = None) -> dict:
    """Totals. Production paths pass the document's stored tax_rate (A1).

    tax_rate=None keeps the pre-A1 behavior (LEGACY_TAX_RATE) for the parity tests and for callers
    that only need subtotals. A document total must never be built without its own rate.
    """
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

    # Dynamic charges (0 when absent, so legacy quotes are unchanged)
    dynamic_total = dynamic_charges_total(charges, items_after_discount)

    subtotal_general = (
        items_after_discount + supervision + admin + insurance + transport + contingency
        + dynamic_total
    )
    rate = LEGACY_TAX_RATE if tax_rate is None else float(tax_rate)
    itbis = subtotal_general * rate
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


def _doc_rate(doc: dict) -> Optional[float]:
    """The document's stored tax rate as a float, or None for a row without a snapshot."""
    r = doc.get("tax_rate")
    return None if r is None else float(r)


def _with_tax_meta(totals: dict, doc: dict) -> dict:
    """Carry the document's tax label and rate with its totals, so every PDF prints the stored label."""
    totals["tax_label"] = doc.get("tax_label")
    totals["tax_rate"] = _doc_rate(doc)
    return totals


def quote_document_totals(quote: dict, items: List[dict], charges: dict) -> dict:
    """Totals printed on every quote PDF: internal download, email and public link (debug B-13).

    Per-charge lines come from calculate_quote_totals. When the quote has stored totals
    (set at create/update/finalize), they are the source of truth for discounts, subtotal,
    ITBIS and grand total, so all four PDF paths print the same numbers.
    """
    breakdown = calculate_quote_totals(items, charges or {}, _doc_rate(quote))
    if all(quote.get(k) is not None for k in ("subtotal", "discount_total", "tax_amount", "grand_total")):
        totals = dict(breakdown)
        totals["total_discounts"] = float(quote["discount_total"])
        totals["items_after_discount"] = breakdown["items_total"] - float(quote["discount_total"])
        totals["subtotal_general"] = float(quote["subtotal"])
        totals["itbis"] = float(quote["tax_amount"])
        totals["grand_total"] = float(quote["grand_total"])
        return _with_tax_meta(totals, quote)
    return _with_tax_meta(breakdown, quote)


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


def _compute_quote_totals(items: List[dict], charges: dict, tax_rate: float) -> dict:
    """Totals via quotes.totals.compute_totals (quoting v1).

    Lazy import: quotes.totals imports calculate_quote_totals from this module.
    """
    from quotes.totals import compute_totals
    return compute_totals(items, charges, tax_rate)


def _check_print_flags(cursor, quote_id, items: List[dict]) -> None:
    """A3 (update only). Hiding a line needs PRINT_CONTROLS_ENABLED. A quote that already has hidden lines may be
    edited while the switch is off, as long as it does not hide MORE lines than it already hides.
    A client that sends no flag cannot silently un-hide lines: refused (409) when the quote has hidden lines."""
    from core.visibility import print_controls_enabled
    hide_count = sum(1 for i in items if i.get("print_on_pdf") is False)
    unset = any(i.get("print_on_pdf") is None for i in items)
    existing = 0
    if quote_id:
        cursor.execute("SELECT COUNT(*) AS n FROM quote_items WHERE quote_id = %s AND print_on_pdf = false", (quote_id,))
        existing = cursor.fetchone()["n"]
    if unset and existing:
        raise api_error(409, "Esta cotización tiene líneas ocultas; actualice la pantalla antes de guardar", "PRINT_FLAG_REQUIRED")
    if hide_count and not print_controls_enabled() and hide_count > existing:
        raise api_error(400, "El control de impresión no está habilitado", "PRINT_CONTROLS_DISABLED")


def _check_print_items(print_items) -> None:
    """Hiding the item table on the PDF needs its switch. True/None always pass."""
    if print_items is False and not pdf_options.print_items_enabled():
        raise api_error(400, "Ocultar productos en el PDF no está habilitado", "PDF_PRINT_ITEMS_DISABLED")


def _item_as_dict(item) -> dict:
    if hasattr(item, "dict"):
        return item.dict()
    if isinstance(item, str):
        return json.loads(item)
    return item


def _validate_item_discounts(items: List[dict]) -> None:
    """percentage discounts are 0-100; fixed discounts may not exceed the line amount."""
    for item in items:
        dtype = item.get("discount_type") or "none"
        value = float(item.get("discount_value") or 0)
        line = float(item.get("quantity") or 0) * float(item.get("unit_price") or 0)
        if dtype == "percentage" and value > 100:
            raise api_error(400, "El descuento porcentual no puede exceder 100", "QUOTE_DISCOUNT_INVALID")
        if dtype == "fixed" and value > line + 0.005:
            raise api_error(400, "El descuento fijo no puede exceder el monto de la línea", "QUOTE_DISCOUNT_INVALID")


def _validate_product_ids(cursor, items: List[dict]) -> None:
    """Every supplied product_id must exist in products. None is allowed (service/custom)."""
    ids = {i.get("product_id") for i in items if i.get("product_id") is not None}
    if not ids:
        return
    cursor.execute("SELECT id FROM products WHERE id = ANY(%s)", (list(ids),))
    found = {r["id"] for r in cursor.fetchall()}
    if ids - found:
        raise api_error(400, "Producto no encontrado", "PRODUCT_NOT_FOUND")


def preview_totals(items: List[dict], charges: dict, tax_type_code: Optional[str] = None,
                   quote_type: Optional[str] = None) -> dict:
    """Stateless totals for the take-off screen. Reads tax_types only; no writes.

    quote_type=engineering_estimate keeps the sent tax code (estimates stay at 1.8%, audit C2)."""
    from tax.service import get_tax_snapshot, derives_tax_for, tax_code_for_charges
    if derives_tax_for(quote_type):
        tax_type_code = tax_code_for_charges(charges)  # 2026-10-22: tax follows charges
    tax = get_tax_snapshot(tax_type_code)
    t = _compute_quote_totals(items, charges, tax["tax_rate"])
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
        "tax_type_code": tax["tax_type_code"],
        "tax_label": tax["tax_label"],
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
def create_quote_in_tx(
    cursor,
    client_id: int,
    contact_id: int,
    project_name: Optional[str],
    notes: Optional[str],
    items: List[dict],
    included_charges: dict,
    payment_terms: Optional[str] = None,
    valid_until: Optional[date] = None,
    created_by_user_id: Optional[str] = None,
    tax_type_code: Optional[str] = None,
    quote_type: Optional[str] = None,
    print_items: bool = True,
) -> str:
    """Validate and insert a Draft quote and its lines on the caller's cursor. No commit. Returns quote_id.

    Shared by create_quote (own connection) and the estimator Generate (one transaction with the run).
    quote_type is written only when given (estimate quotes)."""
    cursor.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
    if not cursor.fetchone():
        raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")

    # Validate that the contact belongs to the selected client
    if contact_id is None:
        raise api_error(400, "Seleccione un contacto del cliente", "CONTACT_REQUIRED")
    cursor.execute(
        "SELECT id FROM contacts WHERE id = %s AND company_id = %s",
        (contact_id, client_id),
    )
    if not cursor.fetchone():
        raise api_error(400, f"El contacto {contact_id} no pertenece al cliente {client_id}", "CONTACT_CLIENT_MISMATCH")

    _validate_product_ids(cursor, items)
    _validate_item_discounts(items)
    quote_id = generate_quote_id()
    from tax.service import resolve_tax_type, derives_tax_for, tax_code_for_charges
    if derives_tax_for(quote_type):
        tax_type_code = tax_code_for_charges(included_charges)  # client value ignored; estimates keep theirs
    tax = resolve_tax_type(cursor, tax_type_code)  # None = the default type
    totals = _compute_quote_totals(items, included_charges, tax["tax_rate"])

    # public_token is not set here. It stays NULL until finalize.
    columns = (
        "quote_id, client_id, contact_id, project_name, notes, status, "
        "included_charges, total_amount, payment_terms, valid_until, "
        "subtotal, discount_total, tax_amount, grand_total, created_by_user_id, "
        "tax_type_code, tax_rate, tax_label"
    )
    values = [
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
        created_by_user_id,
        tax["tax_type_code"],
        tax["tax_rate"],
        tax["tax_label"],
    ]
    placeholders = "%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s"
    if quote_type is not None:
        # Only estimate quotes name the column, so the standard path works before the I1 migration is applied.
        columns += ", quote_type"
        placeholders += ", %s"
        values.append(quote_type)
    _check_print_items(print_items)
    if print_items is False:
        # Named only when false, so the standard path works before the migration is applied.
        columns += ", print_items"
        placeholders += ", %s"
        values.append(False)
    cursor.execute(f"INSERT INTO quotes ({columns}) VALUES ({placeholders})", values)
    status_history.record(cursor, status_history.QUOTE, quote_id, None, "Draft", created_by_user_id)

    # No switch check on create: hidden lines here come from a template pack or a duplicate. The switch
    # (PRINT_CONTROLS_ENABLED) governs the screen control and hiding MORE lines on update.
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
            item.get("category"),
            _print_flag(item),
        )
        for item in items
    ]
    if rows:
        pdf_options.fill_units_from_products(cursor, items)
        sql, rows = pdf_options.with_units(INS_ITEMS_SQL, rows, items)
        execute_values(cursor, sql, rows)
    return quote_id


def create_quote(
    client_id: int,
    contact_id: int,
    project_name: Optional[str],
    notes: Optional[str],
    items: List[dict],
    included_charges: dict,
    payment_terms: Optional[str] = None,
    valid_until: Optional[date] = None,
    created_by_user_id: Optional[str] = None,
    tax_type_code: Optional[str] = None,
    print_items: bool = True,
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        quote_id = create_quote_in_tx(
            cursor, client_id, contact_id, project_name, notes, items, included_charges,
            payment_terms, valid_until, created_by_user_id, tax_type_code, print_items=print_items,
        )

        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   subtotal, discount_total, tax_amount, grand_total,
                   tax_type_code, tax_rate, tax_label,
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
        raise internal_error("No se pudo crear la cotización", e)

    finally:
        if conn:
            conn.close()


def get_quote_by_id(quote_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT quote_id, quote_number, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, subtotal, discount_total,
                   tax_amount, grand_total, terms, payment_terms, valid_until,
                   tax_type_code, tax_rate, tax_label,
                   finalized_at, public_token, created_at, updated_at,
                   to_jsonb(quotes)->>'quote_type' AS quote_type,
                   COALESCE((to_jsonb(quotes)->>'print_items')::boolean, true) AS print_items,
                   (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = quotes.created_by_user_id) AS created_by_name
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        quote = cursor.fetchone()

        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

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
        raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
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
                q.id,
                q.quote_number,
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
                q.tax_type_code,
                q.tax_rate,
                q.tax_label,
                q.payment_terms,
                q.valid_until,
                q.created_at,
                q.updated_at,
                COALESCE((to_jsonb(q)->>'print_items')::boolean, true) AS print_items,

                c.company_name,
                c.address        AS company_address,
                c.tax_id         AS company_tax_id,

                ct.name          AS contact_name,
                ct.email         AS contact_email,
                ct.phone         AS contact_phone,
                (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = q.created_by_user_id) AS created_by_name

            FROM quotes q
            LEFT JOIN clients  c  ON q.client_id  = c.id
            LEFT JOIN contacts ct ON q.contact_id = ct.id AND ct.company_id = q.client_id
            WHERE q.quote_id = %s
        """, (quote_id,))
        row = cursor.fetchone()

        if not row:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

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
            SELECT q.quote_id, q.quote_number, q.grand_total, q.client_id, q.project_name, q.notes, q.status,
                   q.included_charges, q.total_amount, q.payment_terms, q.valid_until,
                   q.created_at, q.updated_at,
                   c.company_name AS client_name,
                   (SELECT COALESCE(u.full_name, u.username) FROM users u WHERE u.id = q.created_by_user_id) AS created_by_name
            FROM quotes q
            LEFT JOIN clients c ON q.client_id = c.id
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
        rows = [dict(r) for r in cursor.fetchall()]
        return status_history.attach_last(cursor, status_history.QUOTE, rows, "quote_id")

    finally:
        if conn:
            conn.close()


def get_quote_status_history(quote_id: str) -> dict:
    """Full history, newest first. enabled=false when the switch is off (the screen then shows nothing extra)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT status, created_at, (SELECT COALESCE(u.full_name, u.username) FROM users u "
                       "WHERE u.id = quotes.created_by_user_id) AS created_by_name FROM quotes WHERE quote_id = %s",
                       (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
        return {"enabled": status_history.enabled(), "current_status": quote["status"],
                "entries": status_history.fetch(cursor, status_history.QUOTE, quote_id)}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo leer el historial", e)
    finally:
        if conn:
            conn.close()


# Edit policy toggle (production value: False).
#   False -> only Draft quotes can be edited. Finalized quotes are always locked.
#   True  -> non-Draft quotes become editable (not used; would break document integrity).
ALLOW_EDIT_NON_DRAFT_QUOTES = False  # Business rule: only Draft quotes are editable.


def update_quote(quote_id: str, quote_update, actor: Optional[dict] = None) -> dict:
    """Update an existing quote. actor = the token payload (role, user_id); used only by the estimate-quote lock."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Row lock (debug B-23): a save cannot interleave with finalize or another save.
        cursor.execute("SELECT * FROM quotes WHERE quote_id = %s FOR UPDATE", (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

        # Finalized quotes are locked regardless of ALLOW_EDIT_NON_DRAFT_QUOTES.
        if quote["status"] == QUOTE_STATUS_FINAL:
            raise api_error(400, "Las cotizaciones finalizadas no se pueden editar", "QUOTE_FINALIZED")

        if not ALLOW_EDIT_NON_DRAFT_QUOTES and quote["status"] != "Draft":
            raise api_error(400, "Solo las cotizaciones en Borrador se pueden editar", "QUOTE_NOT_DRAFT")

        update_dict = quote_update.dict(exclude_unset=True)

        # Pull these out — they're handled separately below.
        items = update_dict.pop('items', None)
        included_charges = update_dict.pop('included_charges', None)
        # A1: choosing a tax type re-reads it from tax_types and stores the snapshot. Only Draft quotes get here.
        tax_type_code = update_dict.pop('tax_type_code', None)
        edit_reason = update_dict.pop('edit_reason', None)
        print_items = update_dict.pop('print_items', None)
        _check_print_items(print_items)

        # Estimate quotes (quote_type = engineering_estimate): money fields are locked for regular users; an admin
        # needs a reason and every change is audited. Other quotes never enter this block.
        estimate_audit = []
        if is_estimate(quote):
            cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
            old_rows = [dict(r) for r in cursor.fetchall()]
            new_items = None if items is None else [_item_as_dict(i) for i in items]
            new_charges = None
            if included_charges is not None:
                new_charges = included_charges.dict() if hasattr(included_charges, 'dict') else (
                    json.loads(included_charges) if isinstance(included_charges, str) else included_charges)
            old_charges = quote.get("included_charges")
            if isinstance(old_charges, str):
                old_charges = json.loads(old_charges)
            estimate_audit = money_changes(old_rows, new_items, old_charges, new_charges,
                                           quote.get("tax_type_code"), tax_type_code)
            if estimate_audit:
                if (actor or {}).get("role") not in ADMIN_ROLES:
                    raise api_error(403, "Los precios, cantidades, descuentos, cargos e impuestos de un estimado de ingeniería solo los puede cambiar un administrador", "ESTIMATE_LOCKED")
                if not (edit_reason or "").strip():
                    raise api_error(400, "Indique el motivo del cambio", "ESTIMATE_EDIT_REASON_REQUIRED")
                for ch in estimate_audit:
                    cursor.execute(
                        "INSERT INTO quote_edit_audit (quote_id, quote_item_id, field, old_value, new_value, reason, user_id) "
                        "SELECT id, %s, %s, %s, %s, %s, %s FROM quotes WHERE quote_id = %s",
                        (ch["item_id"], ch["field"], ch["old"], ch["new"], edit_reason.strip(), (actor or {}).get("user_id"), quote_id),
                    )

        if 'valid_until' in update_dict and update_dict['valid_until'] is not None:
            update_dict['valid_until'] = _serialize_date(update_dict['valid_until'])

        if print_items is not None:
            # Display only: totals are untouched. Allowed on estimate quotes (no money change).
            cursor.execute("UPDATE quotes SET print_items = %s, updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s", (print_items, quote_id))

        # Scalar fields update
        if update_dict:
            set_clause = ", ".join([f"{key} = %s" for key in update_dict.keys()])
            query = f"""
                UPDATE quotes
                SET {set_clause}, updated_at = CURRENT_TIMESTAMP
                WHERE quote_id = %s
            """
            cursor.execute(query, list(update_dict.values()) + [quote_id])

        from tax.service import resolve_tax_type, derives_tax_for, tax_code_for_charges
        # Estimate quotes never re-derive: their 1.8% survives every save (audit C2, decision 2026-10-24).
        derive_tax = derives_tax_for(quote.get("quote_type"))
        if derive_tax:
            tax_type_code = None  # client value ignored; derived from charges below
        if tax_type_code is not None and not derive_tax:
            tax = resolve_tax_type(cursor, tax_type_code)
            cursor.execute(
                "UPDATE quotes SET tax_type_code = %s, tax_rate = %s, tax_label = %s, updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s",
                (tax["tax_type_code"], tax["tax_rate"], tax["tax_label"], quote_id),
            )
        else:
            tax = None  # read from the stored snapshot only if totals are recalculated below

        # Re-insert items if provided
        if items is not None:
            _validate_product_ids(cursor, [_item_as_dict(i) for i in items])
            _validate_item_discounts([_item_as_dict(i) for i in items])
            normalized = []
            for item in items:
                # Normalize — item may be a dict or a Pydantic model
                if hasattr(item, 'dict'):
                    item = item.dict()
                elif isinstance(item, str):
                    item = json.loads(item)
                normalized.append(item)
            _check_print_flags(cursor, quote_id, normalized)  # reads the old rows, so it runs before the delete
            cursor.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))

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
                    item.get("category"),
                    _print_flag(item),
                )
                for item in normalized
            ]
            if rows:
                pdf_options.fill_units_from_products(cursor, normalized)
                sql, rows = pdf_options.with_units(INS_ITEMS_SQL, rows, normalized)
                execute_values(cursor, sql, rows)

        # Recalculate totals if items, charges or the tax type changed
        if included_charges is not None or items is not None or tax_type_code is not None or derive_tax:
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

            if derive_tax:
                tax = resolve_tax_type(cursor, tax_code_for_charges(charges))
                cursor.execute(
                    "UPDATE quotes SET tax_type_code = %s, tax_rate = %s, tax_label = %s, updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s",
                    (tax["tax_type_code"], tax["tax_rate"], tax["tax_label"], quote_id),
                )
            if tax is None:
                from tax.service import snapshot_from_document
                tax = snapshot_from_document(quote)
            totals = _compute_quote_totals(current_items, charges, tax["tax_rate"])

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
                   tax_type_code, tax_rate, tax_label,
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
        raise internal_error("No se pudo actualizar la cotización", e)

    finally:
        if conn:
            conn.close()


def _has_estimate_history(cursor, quote_id: str) -> bool:
    """True when estimator runs or audited edits reference the quote. Works before the estimator tables exist."""
    cursor.execute("SELECT to_regclass('public.estimator_runs') AS r, to_regclass('public.quote_edit_audit') AS a")
    t = cursor.fetchone() or {}
    checks = []
    if t.get("r"):
        checks.append("EXISTS (SELECT 1 FROM estimator_runs r JOIN quotes q ON q.id = r.quote_id WHERE q.quote_id = %s)")
    if t.get("a"):
        checks.append("EXISTS (SELECT 1 FROM quote_edit_audit a JOIN quotes q ON q.id = a.quote_id WHERE q.quote_id = %s)")
    if not checks:
        return False
    cursor.execute("SELECT (" + " OR ".join(checks) + ") AS has_history", tuple(quote_id for _ in checks))
    row = cursor.fetchone() or {}
    return bool(row.get("has_history"))


def delete_quote(quote_id: str, actor_user_id: Optional[str] = None) -> dict:
    """Delete a Draft or Rejected quote and its items. Finalized or invoiced quotes are kept."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT status FROM quotes WHERE quote_id = %s FOR UPDATE", (quote_id,))
        row = cursor.fetchone()
        if not row:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
        if row["status"] not in DELETABLE_STATUSES:
            raise api_error(400, "Solo se pueden eliminar cotizaciones en Borrador o Rechazadas", "QUOTE_DELETE_BLOCKED")

        cursor.execute("SELECT id FROM invoices WHERE quote_id = %s", (quote_id,))
        if cursor.fetchone():
            raise api_error(400, "La cotización tiene una factura y no se puede eliminar", "QUOTE_DELETE_BLOCKED")

        # Audit H1 (2026-10-24): an estimate quote with a calculation run or audited edits keeps its history
        # (append-only tables reference it). Refuse cleanly instead of failing in the database.
        if _has_estimate_history(cursor, quote_id):
            raise api_error(400, "Este estimado de ingeniería conserva su historial de cálculo y cambios auditados, por eso no se puede eliminar.", "ESTIMATE_QUOTE_HAS_HISTORY")

        cursor.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        cursor.execute("DELETE FROM quotes WHERE quote_id = %s", (quote_id,))
        status_history.record(cursor, status_history.QUOTE, quote_id, row["status"], "Deleted", actor_user_id)
        conn.commit()
        return {"message": "Cotización eliminada correctamente"}

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


# =============================================================================
# SECTION 4: QUOTE BUSINESS LOGIC
# =============================================================================
def duplicate_quote(
    quote_id: str,
    created_by_user_id: Optional[str] = None,
    client_id: Optional[int] = None,
    contact_id: Optional[int] = None,
) -> dict:
    """Duplicate an existing quote into a new Draft.

    Copies: client, contact, project, notes (exact), included_charges,
    total_amount, payment_terms, terms, valid_until, and every item
    (product_id, product_name, quantity, unit_price, discount, item_type,
    description). Resets: status = Draft, public_token = NULL, finalized_at
    not copied.

    B1: client_id and/or contact_id move the copy to another client or contact (needs
    DUPLICATE_CHANGE_CLIENT_ENABLED). The contact must belong to the target client, so changing the
    client always needs a contact of the new client. Everything else is copied unchanged, including
    prices and the tax snapshot. The original quote is never modified.

    Requires quoting_v1 migration (terms, item_type, description,
    public_token nullable). Do not deploy this code before that migration.
    """
    conn = None
    try:
        if client_id is not None or contact_id is not None:
            from core.quote_features import duplicate_change_client_enabled
            if not duplicate_change_client_enabled():
                raise api_error(404, "No disponible", "NOT_FOUND")
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Fetch original quote
        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until, terms,
                   subtotal, discount_total, tax_amount, grand_total,
                   tax_type_code, tax_rate, tax_label,
                   to_jsonb(quotes)->>'quote_type' AS quote_type,
                   COALESCE((to_jsonb(quotes)->>'print_items')::boolean, true) AS print_items
            FROM quotes
            WHERE quote_id = %s
        """, (quote_id,))
        original = cursor.fetchone()
        if not original:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

        original = dict(original)

        target_client = original["client_id"]
        target_contact = original["contact_id"]
        if client_id is not None or contact_id is not None:
            target_client = client_id if client_id is not None else original["client_id"]
            cursor.execute("SELECT id FROM clients WHERE id = %s", (target_client,))
            if not cursor.fetchone():
                raise api_error(404, "Cliente no encontrado", "CLIENT_NOT_FOUND")
            if contact_id is None:
                if target_client != original["client_id"]:
                    raise api_error(400, "Seleccione un contacto del cliente", "CONTACT_REQUIRED")
            else:
                target_contact = contact_id
            cursor.execute("SELECT id FROM contacts WHERE id = %s AND company_id = %s", (target_contact, target_client))
            if not cursor.fetchone():
                raise api_error(400, f"El contacto {target_contact} no pertenece al cliente {target_client}", "CONTACT_CLIENT_MISMATCH")

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

        # 5. valid_until — a date already past is not copied (debug B-23, approved 2026-10-18);
        #    the user sets a new one before finalizing.
        from core.dates import business_today
        original_valid = original.get("valid_until")
        if isinstance(original_valid, date) and original_valid < business_today():
            original_valid = None
        valid_until = _serialize_date(original_valid)

        # 6. Insert duplicated quote
        cursor.execute("""
            INSERT INTO quotes
                (quote_id, client_id, contact_id, project_name, notes, status,
                 included_charges, total_amount, payment_terms, terms,
                 valid_until, subtotal, discount_total, tax_amount, grand_total, created_by_user_id,
                 tax_type_code, tax_rate, tax_label, public_token)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """, (
            new_quote_id,
            target_client,
            target_contact,
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
            created_by_user_id,
            original["tax_type_code"],  # the copy keeps the original's snapshot, so its stored totals stay consistent
            original["tax_rate"],
            original["tax_label"],
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
                item.get("category"),
                item.get("print_on_pdf", True) is not False,  # the copy keeps the original's visibility
            )
            for item in original_items
        ]
        if rows:
            sql, rows = pdf_options.with_units(INS_DUP_SQL, rows, [dict(i) for i in original_items])
            execute_values(cursor, sql, rows)
        if original.get("print_items") is False:
            cursor.execute("UPDATE quotes SET print_items = false WHERE quote_id = %s", (new_quote_id,))
        status_history.record(cursor, status_history.QUOTE, new_quote_id, None, "Draft", created_by_user_id,
                              note="duplicate of " + str(quote_id))

        # R4: a copy of an estimate quote stays an estimate quote (the money lock follows the copy).
        # to_jsonb in the SELECT above keeps this working before the quote_type column exists (NULL).
        if original.get("quote_type"):
            cursor.execute("UPDATE quotes SET quote_type = %s WHERE quote_id = %s", (original["quote_type"], new_quote_id))

        # Audit H3 (2026-10-24): with TAX_FROM_CHARGES on, the copy follows the current rule, not the
        # original's snapshot. Estimate copies keep the original 1.8%.
        from tax.service import derives_tax_for, resolve_tax_type, tax_code_for_charges
        if derives_tax_for(original.get("quote_type")):
            dup_charges = json.loads(included_charges) if included_charges else {}
            tax = resolve_tax_type(cursor, tax_code_for_charges(dup_charges))
            if tax["tax_type_code"] != original["tax_type_code"] or float(tax["tax_rate"]) != float(original["tax_rate"]):
                cursor.execute(
                    "UPDATE quotes SET tax_type_code = %s, tax_rate = %s, tax_label = %s WHERE quote_id = %s",
                    (tax["tax_type_code"], tax["tax_rate"], tax["tax_label"], new_quote_id),
                )
                cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (new_quote_id,))
                dup_totals = _compute_quote_totals([dict(r) for r in cursor.fetchall()], dup_charges, tax["tax_rate"])
                cursor.execute(TOTALS_UPDATE_SQL, _totals_columns(dup_totals) + (new_quote_id,))

        conn.commit()

        # 8. Return new quote with items
        cursor.execute("""
            SELECT quote_id, client_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   tax_type_code, tax_rate, tax_label,
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
        raise internal_error("No se pudo duplicar la cotización", e)

    finally:
        if conn:
            conn.close()


def finalize_quote(quote_id: str, actor_user_id: Optional[str] = None) -> dict:
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
            "SELECT quote_id, status, included_charges, tax_rate, to_jsonb(quotes)->>'quote_type' AS quote_type "
            "FROM quotes WHERE quote_id = %s FOR UPDATE",
            (quote_id,),
        )
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
        if quote["status"] != "Draft":
            raise api_error(400, "Solo las cotizaciones en Borrador se pueden finalizar", "QUOTE_NOT_DRAFT")

        # M3 (2026-10-22, toggle BLOCK_ZERO_LINE_FINALIZE, default OFF): no finalize with a $0 line.
        # Audit M2 (2026-10-24): a $0 line is any line whose total is 0 or less: price 0, quantity 0,
        # a 100% discount or a fixed discount that covers the whole line.
        from core.switches import switch_on
        if switch_on("BLOCK_ZERO_LINE_FINALIZE"):
            cursor.execute(
                """SELECT product_name FROM quote_items
                   WHERE quote_id = %s
                     AND (unit_price <= 0 OR quantity <= 0
                          OR (discount_type = 'percentage' AND discount_value >= 100)
                          OR (discount_type = 'fixed' AND discount_value >= quantity * unit_price))
                   ORDER BY id""",
                (quote_id,),
            )
            zero = [r["product_name"] for r in cursor.fetchall()]
            if zero:
                raise api_error(
                    400,
                    "No se puede finalizar: hay lineas con precio 0: " + ", ".join(zero[:5]),
                    "ZERO_PRICE_LINE",
                )

        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        current_items = [dict(row) for row in cursor.fetchall()]
        if not current_items:
            raise api_error(400, "La cotización debe tener al menos un ítem para finalizarla", "QUOTE_EMPTY")

        raw = quote.get("included_charges") or {}
        if isinstance(raw, str):
            raw = json.loads(raw) if raw else {}

        # Audit M1 (2026-10-24): the charge-name rule also holds on the finalize path, not only on save.
        if switch_on("REQUIRE_CHARGE_NAME"):
            for dc in (raw.get("dynamic_charges") or [])[:3]:
                if isinstance(dc, dict) and dc.get("enabled") and float(dc.get("percentage") or 0) > 0 \
                        and not str(dc.get("name") or "").strip():
                    raise api_error(400, "Cada cargo adicional activo necesita un nombre", "CHARGE_NAME_REQUIRED")

        # Audit H3 (2026-10-24): a draft that was never saved under the rule (a duplicate, or a draft from
        # before TAX_FROM_CHARGES) takes the rule's tax here. Estimate quotes keep theirs.
        rate = float(quote["tax_rate"])
        from tax.service import derives_tax_for, resolve_tax_type, tax_code_for_charges
        if derives_tax_for(quote.get("quote_type")):
            tax = resolve_tax_type(cursor, tax_code_for_charges(raw))
            cursor.execute(
                "UPDATE quotes SET tax_type_code = %s, tax_rate = %s, tax_label = %s WHERE quote_id = %s",
                (tax["tax_type_code"], tax["tax_rate"], tax["tax_label"], quote_id),
            )
            rate = tax["tax_rate"]
        totals = _compute_quote_totals(current_items, raw, rate)

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
        status_history.record(cursor, status_history.QUOTE, quote_id, "Draft", QUOTE_STATUS_FINAL, actor_user_id)
        conn.commit()

        cursor.execute("""
            SELECT quote_id, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, payment_terms, valid_until,
                   subtotal, discount_total, tax_amount, grand_total,
                   tax_type_code, tax_rate, tax_label,
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
        raise internal_error("No se pudo finalizar la cotización", e)

    finally:
        if conn:
            conn.close()


def update_quote_status(quote_id: str, status: str, actor_user_id: Optional[str] = None) -> dict:
    """Manual status change. Follows MANUAL_QUOTE_TRANSITIONS strictly."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Row lock: serializes concurrent status changes (approve vs finalize, convert).
        cursor.execute("SELECT quote_id, status FROM quotes WHERE quote_id = %s FOR UPDATE", (quote_id,))
        current = cursor.fetchone()
        if not current:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

        if status not in QUOTE_STATUSES:
            raise api_error(400, f"Estado no válido. Debe ser uno de: {list(QUOTE_STATUSES)}", "QUOTE_STATUS_INVALID")

        # Statuses owned by dedicated endpoints.
        if status == QUOTE_STATUS_FINAL:
            raise api_error(400, "Use la acción de finalizar para establecer Final", "QUOTE_USE_FINALIZE")
        if status == "Sent":
            raise api_error(400, "Use la acción de enviar para marcar una cotización como Enviada", "QUOTE_USE_SEND")
        if status == "Invoiced":
            raise api_error(400, "Use convertir a factura para facturar una cotización", "QUOTE_USE_CONVERT")
        if status == "Draft":
            raise api_error(400, "Las cotizaciones no pueden volver a Borrador. Duplique la cotización para reelaborarla", "QUOTE_REOPEN_BLOCKED")

        if status == current["status"]:
            return {"message": "Estado sin cambios", "quote_id": quote_id, "status": status}

        allowed = MANUAL_QUOTE_TRANSITIONS.get(current["status"], set())
        if status not in allowed:
            raise api_error(400, f"No se puede cambiar la cotización de {current['status']} a {status}", "QUOTE_TRANSITION_INVALID")

        cursor.execute(
            "UPDATE quotes SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s", (status, quote_id)
        )
        status_history.record(cursor, status_history.QUOTE, quote_id, current["status"], status, actor_user_id)

        # X-02 (approved 2026-10-18): rejecting a quote cancels its project. Completed projects are kept.
        if status == "Rejected":
            cursor.execute(
                "UPDATE projects SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
                "WHERE quote_id = %s AND status NOT IN ('completed', 'cancelled')",
                (quote_id,),
            )

        # Approval creates the project (Phase 2). Savepoint: a project failure never blocks the approval.
        if status == "Approved":
            cursor.execute("SAVEPOINT project_from_quote")
            try:
                from projects.service import create_project_from_quote  # local: avoids import cycle
                from psycopg2.extras import RealDictCursor as _RDC
                pcur = conn.cursor(cursor_factory=_RDC)
                create_project_from_quote(pcur, quote_id)
                cursor.execute("RELEASE SAVEPOINT project_from_quote")
            except Exception:
                cursor.execute("ROLLBACK TO SAVEPOINT project_from_quote")
                logger.exception("Project creation failed for approved quote %s", quote_id)

        conn.commit()

        return {"message": "Estado actualizado correctamente", "quote_id": quote_id, "status": status}

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar el estado", e)

    finally:
        if conn:
            conn.close()


def assert_quote_sendable(quote: dict) -> None:
    """Called by the send route BEFORE building the PDF or emailing anything."""
    if quote.get("status") not in SENDABLE_STATUSES or not quote.get("public_token"):
        raise api_error(400, "Solo se pueden enviar cotizaciones finalizadas", "QUOTE_NOT_FINALIZED")
    if not quote.get("contact_email"):
        raise api_error(400, "El contacto de la cotización no tiene correo electrónico", "QUOTE_NO_CONTACT_EMAIL")


def mark_quote_sent(quote_id: str, actor_user_id: Optional[str] = None) -> str:
    """After a successful send: Final -> Sent. Sent and Approved keep their status."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE quotes SET status = 'Sent', updated_at = CURRENT_TIMESTAMP WHERE quote_id = %s AND status = %s",
            (quote_id, QUOTE_STATUS_FINAL),
        )
        if getattr(cursor, "rowcount", 0) > 0:
            status_history.record(cursor, status_history.QUOTE, quote_id, QUOTE_STATUS_FINAL, "Sent", actor_user_id)
        conn.commit()
        cursor.execute("SELECT status FROM quotes WHERE quote_id = %s", (quote_id,))
        row = cursor.fetchone()
        return row["status"] if row else "Sent"
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("La cotización se envió por correo, pero no se pudo actualizar su estado", e)
    finally:
        if conn:
            conn.close()


def _print_flag(item: dict) -> bool:
    """A3: only a literal False hides a line (missing or None prints)."""
    return item.get("print_on_pdf", True) is not False


def _invoice_line_amounts(item: dict) -> tuple:
    """
    (quantity, unit_price, discount_amount, line_total) for one invoice line.
    discount_amount is always currency: percentage discounts are converted,
    fixed discounts are taken as-is. Same rule as calculate_quote_totals.
    """
    qty = float(item.get("quantity") or 0)
    price = float(item.get("unit_price") or 0)
    gross = qty * price
    value = float(item.get("discount_value") or 0)
    dtype = item.get("discount_type") or "none"
    if dtype == "percentage":
        discount = gross * value / 100
    elif dtype == "fixed":
        discount = value
    else:
        discount = 0.0
    discount = round(discount, 2)
    return qty, price, discount, round(gross - discount, 2)


def convert_quote_to_invoice(quote_id: str, created_by_user_id: Optional[str] = None) -> dict:
    """Convert an approved quote to an invoice."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Load quote
        cursor.execute("""
            SELECT quote_id, quote_number, client_id, contact_id, project_name, notes, status,
                   included_charges, total_amount, grand_total, payment_terms, valid_until,
                   tax_type_code, tax_rate, tax_label,
                   COALESCE((to_jsonb(quotes)->>'print_items')::boolean, true) AS print_items
            FROM quotes
            WHERE quote_id = %s
            FOR UPDATE
        """, (quote_id,))
        quote = cursor.fetchone()
        if not quote:
            raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")

        quote = dict(quote)

        if quote["status"] != "Approved":
            raise api_error(400, "Solo las cotizaciones aprobadas se pueden convertir en facturas", "QUOTE_NOT_APPROVED")

        # 2. Prevent duplicate invoices. A cancelled invoice does not count (B-06):
        #    the quote can be invoiced again and the cancelled one stays for the record.
        cursor.execute("SELECT id FROM invoices WHERE quote_id = %s AND status <> 'Cancelled'", (quote_id,))
        if cursor.fetchone():
            raise api_error(400, "Ya existe una factura para esta cotización", "INVOICE_EXISTS")
        cursor.execute("SELECT COUNT(*) AS n FROM invoices WHERE quote_id = %s", (quote_id,))
        previous_invoices = int(cursor.fetchone()["n"])

        # 3. Load quote items (deterministic order)
        cursor.execute("SELECT * FROM quote_items WHERE quote_id = %s ORDER BY id", (quote_id,))
        items = [dict(row) for row in cursor.fetchall()]

        raw_charges = quote.get("included_charges")
        charges = json.loads(raw_charges) if isinstance(raw_charges, str) else (raw_charges or {})

        # Invoice total is the stored grand_total set at finalize/save.
        # Recompute only for legacy rows that have no stored total.
        breakdown = calculate_quote_totals(items, charges, float(quote["tax_rate"]))
        if quote.get("grand_total") is not None:
            invoice_total = float(quote["grand_total"])
        else:
            invoice_total = breakdown["grand_total"]
        # Header columns. subtotal = line items before discounts; charges_total =
        # supervision + admin + insurance + transport + contingency.
        header_subtotal = round(breakdown["items_total"], 2)
        header_discounts = round(breakdown["total_discounts"], 2)
        header_charges = round(breakdown["subtotal_general"] - breakdown["items_after_discount"], 2)
        header_itbis = round(breakdown["itbis"], 2)

        # 4. Create invoice
        # Q-10002 -> F-10002. One invoice per quote (checked above), so the label is unique.
        # Quotes without a number (not expected) keep the timestamp form.
        quote_number = quote.get("quote_number")
        if quote_number:
            invoice_number = invoice_label(quote_number)
            if previous_invoices:  # re-invoice after a cancel: F-10002 -> F-10002-2
                invoice_number = f"{invoice_number}-{previous_invoices + 1}"
        else:
            invoice_number = f"INV-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        from core.dates import business_today  # B-04: DR calendar date, not server UTC
        invoice_date = business_today().isoformat()

        cursor.execute("""
            INSERT INTO invoices
                (quote_id, invoice_number, invoice_date, client_id, contact_id,
                 total_amount, status, notes, payment_terms, valid_until, created_by_user_id,
                 subtotal, discount_total, charges_total, itbis_total, grand_total,
                 amount_paid, amount_due, quote_number,
                 tax_type_code, tax_rate, tax_label)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            created_by_user_id,
            header_subtotal,
            header_discounts,
            header_charges,
            header_itbis,
            invoice_total,
            0,
            invoice_total,
            quote_number,
            quote["tax_type_code"],  # snapshot: the invoice keeps the quote's type, rate and label for good
            quote["tax_rate"],
            quote["tax_label"],
        ))

        invoice_id = cursor.fetchone()["id"]   # FIXED

        # 5. Insert invoice items
        invoice_item_rows = [
            (invoice_id, item["product_id"], item["product_name"], *_invoice_line_amounts(item), item.get("category"), n,
             item.get("print_on_pdf", True) is not False)  # A3: visibility travels quote -> invoice
            for n, item in enumerate(items, start=1)   # B-19: line_no keeps the quote's line order
        ]
        if invoice_item_rows:
            inv_sql, invoice_item_rows = pdf_options.with_units(
                "INSERT INTO invoice_items (invoice_id, product_id, description, quantity, unit_price, discount, total, category, line_no, print_on_pdf) VALUES %s",
                invoice_item_rows, items,
            )
            execute_values(cursor, inv_sql, invoice_item_rows)
        if quote.get("print_items") is False:
            cursor.execute("UPDATE invoices SET print_items = false WHERE id = %s", (invoice_id,))  # the invoice inherits the checkbox

        # Same transaction: the quote moves to Invoiced with the invoice.
        cursor.execute(
            "UPDATE quotes SET status = 'Invoiced' WHERE quote_id = %s AND status = 'Approved'",
            (quote_id,),
        )
        # The quote was read FOR UPDATE as Approved above, so the UPDATE always matches.
        status_history.record(cursor, status_history.QUOTE, quote_id, "Approved", "Invoiced", created_by_user_id,
                              note="invoice " + str(invoice_number))
        status_history.record(cursor, status_history.INVOICE, invoice_id, None, "Pending", created_by_user_id,
                              note="from quote " + str(quote_id))

        # X-01: an invoiced quote always has a project. Quotes approved before Phase 2 had none.
        # Idempotent (one project per quote). Savepoint: a project failure never blocks the invoice.
        cursor.execute("SAVEPOINT project_on_invoice")
        try:
            from projects.service import create_project_from_quote  # local: avoids import cycle
            create_project_from_quote(cursor, quote_id)
            cursor.execute("RELEASE SAVEPOINT project_on_invoice")
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT project_on_invoice")
            logger.exception("Project creation failed for invoiced quote %s", quote_id)
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
        raise internal_error("No se pudo convertir la cotización en factura", e)

    finally:
        if conn:
            conn.close()
