import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from company_settings.service import seal_for_pdf
from core.errors import api_error, internal_error
from core.po_features import po_enabled
from database import get_db_connection
from pdf.builder_po import create_po_pdf
from pdf.utils.signer import resolve_signer_name
from rfq.models import DEFAULT_BILL_TO, rfq_label
from rfq.service import COMPANY_LINES, _supplier_snapshot
from .models import DEFAULT_TITLE, po_label

logger = logging.getLogger("metpro.po")

PO_COLS = ("id, po_number, rfq_id, supplier_id, vendor_name, vendor_contact, vendor_email, vendor_phone, vendor_address, "
           "vendor_tax_id, title, po_date, bill_to, payment_terms, notes, status, subtotal, total, created_by")
ITEM_COLS = "id, position, product_id, item, description, quantity, unit, unit_price, amount"
CENT = Decimal("0.01")


def require_enabled() -> None:
    if not po_enabled():
        raise api_error(404, "Órdenes de compra no está habilitado", "PO_DISABLED")


def line_amount(quantity, unit_price) -> Decimal:
    """quantity x unit price in DOP, rounded half up to the cent."""
    return (Decimal(str(quantity)) * Decimal(str(unit_price))).quantize(CENT, rounding=ROUND_HALF_UP)


def compute_totals(items) -> tuple:
    """(amounts per line, subtotal, total). No tax: total equals subtotal."""
    amounts = [line_amount(i.quantity, i.unit_price) for i in items]
    subtotal = sum(amounts, Decimal("0.00"))
    return amounts, subtotal, subtotal


def _shape(row: dict, items: Optional[List[dict]] = None, item_count: Optional[int] = None, rfq_number=None) -> dict:
    out = dict(row)
    out["label"] = po_label(out["po_number"])
    out["rfq_label"] = rfq_label(rfq_number) if rfq_number is not None else None
    out["subtotal"] = float(out["subtotal"])
    out["total"] = float(out["total"])
    out["items"] = [dict(i, quantity=float(i["quantity"]), unit_price=float(i["unit_price"]), amount=float(i["amount"]))
                    for i in (items or [])]
    out["item_count"] = item_count if item_count is not None else len(out["items"])
    return out


def _check_products(cur, items) -> None:
    ids = [i.product_id for i in items if i.product_id is not None]
    if ids:
        cur.execute("SELECT id FROM products WHERE id = ANY(%s)", (ids,))
        found = {r["id"] for r in cur.fetchall()}
        if any(i not in found for i in ids):
            raise api_error(400, "Un producto ya no existe", "PO_PRODUCT_NOT_FOUND")


def _write_items(cur, po_id: int, items, amounts) -> None:
    cur.execute("DELETE FROM po_items WHERE po_id = %s", (po_id,))
    for pos, (it, amt) in enumerate(zip(items, amounts), start=1):
        cur.execute(
            "INSERT INTO po_items (po_id, position, product_id, item, description, quantity, unit, unit_price, amount) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (po_id, pos, it.product_id, it.item, it.description, it.quantity, it.unit, it.unit_price, amt))


def _load(cur, po_id: int) -> dict:
    cur.execute(f"SELECT {PO_COLS} FROM purchase_orders WHERE id = %s", (po_id,))
    row = cur.fetchone()
    if not row:
        raise api_error(404, "Orden de compra no encontrada", "PO_NOT_FOUND")
    cur.execute(f"SELECT {ITEM_COLS} FROM po_items WHERE po_id = %s ORDER BY position", (po_id,))
    items = cur.fetchall()
    rfq_number = None
    if row["rfq_id"]:
        cur.execute("SELECT rfq_number FROM rfqs WHERE id = %s", (row["rfq_id"],))
        r = cur.fetchone()
        rfq_number = r["rfq_number"] if r else None
    return _shape(row, items, rfq_number=rfq_number)


def list_pos() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SELECT {PO_COLS}, (SELECT count(*) FROM po_items i WHERE i.po_id = p.id) AS n, "
                    f"(SELECT rfq_number FROM rfqs r WHERE r.id = p.rfq_id) AS rn "
                    f"FROM purchase_orders p ORDER BY created_at DESC, id DESC")
        return [_shape({k: v for k, v in r.items() if k not in ("n", "rn")}, [], r["n"], r["rn"]) for r in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def get_po(po_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        return _load(conn.cursor(cursor_factory=RealDictCursor), po_id)
    finally:
        if conn:
            conn.close()


def _insert(cur, body, actor, rfq_id: Optional[int]) -> int:
    if not body.items:
        raise api_error(400, "Agregue al menos un artículo", "PO_NO_ITEMS")
    snap = _supplier_snapshot(cur, body.supplier_id)
    _check_products(cur, body.items)
    amounts, subtotal, total = compute_totals(body.items)
    cur.execute(
        """INSERT INTO purchase_orders (rfq_id, supplier_id, vendor_name, vendor_contact, vendor_email, vendor_phone,
               vendor_address, vendor_tax_id, title, po_date, bill_to, payment_terms, notes, subtotal, total, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (rfq_id, body.supplier_id, snap["vendor_name"], snap["vendor_contact"], snap["vendor_email"], snap["vendor_phone"],
         snap["vendor_address"], snap["vendor_tax_id"], body.title or DEFAULT_TITLE, body.po_date or date.today(),
         body.bill_to or DEFAULT_BILL_TO, body.payment_terms, body.notes, subtotal, total, actor))
    po_id = cur.fetchone()["id"]
    _write_items(cur, po_id, body.items, amounts)
    return po_id


def create_po(body, actor: Optional[str]) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        po_id = _insert(cur, body, actor, None)
        conn.commit()
        return _load(cur, po_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo crear la orden de compra", e)
    finally:
        if conn:
            conn.close()


def convert_rfq(rfq_id: int, actor: Optional[str]) -> dict:
    """New Draft P.O from an RFQ: same supplier, header and lines, prices at 0 for the user to type.
    The RFQ becomes Converted. One P.O per RFQ while that P.O exists."""
    from .models import PoIn, PoItemIn
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM rfqs WHERE id = %s FOR UPDATE", (rfq_id,))
        r = cur.fetchone()
        if not r:
            raise api_error(404, "RFQ no encontrado", "RFQ_NOT_FOUND")
        if r["status"] == "Converted":
            raise api_error(400, "El RFQ ya fue convertido a orden de compra", "RFQ_ALREADY_CONVERTED")
        cur.execute("SELECT product_id, item, description, quantity, unit FROM rfq_items WHERE rfq_id = %s ORDER BY position",
                    (rfq_id,))
        items = [PoItemIn(product_id=i["product_id"], item=i["item"], description=i["description"],
                          quantity=float(i["quantity"]), unit=i["unit"], unit_price=0) for i in cur.fetchall()]
        body = PoIn(supplier_id=r["supplier_id"], po_date=date.today(), bill_to=r["bill_to"],
                    payment_terms=r["payment_terms"], notes=r["notes"], items=items)
        po_id = _insert(cur, body, actor, rfq_id)
        cur.execute("UPDATE rfqs SET status = 'Converted', updated_at = now() WHERE id = %s", (rfq_id,))
        conn.commit()
        return _load(cur, po_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo convertir el RFQ", e)
    finally:
        if conn:
            conn.close()


def update_po(po_id: int, body) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status, supplier_id FROM purchase_orders WHERE id = %s FOR UPDATE", (po_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "Orden de compra no encontrada", "PO_NOT_FOUND")
        if row["status"] != "Draft":
            raise api_error(400, "Solo se puede editar una orden en borrador", "PO_LOCKED")
        if not body.items:
            raise api_error(400, "Agregue al menos un artículo", "PO_NO_ITEMS")
        snap = _supplier_snapshot(cur, body.supplier_id, keep_if_same_as=row["supplier_id"])
        _check_products(cur, body.items)
        amounts, subtotal, total = compute_totals(body.items)
        cur.execute(
            """UPDATE purchase_orders SET supplier_id=%s, vendor_name=%s, vendor_contact=%s, vendor_email=%s,
                   vendor_phone=%s, vendor_address=%s, vendor_tax_id=%s, title=%s, po_date=%s, bill_to=%s,
                   payment_terms=%s, notes=%s, subtotal=%s, total=%s, updated_at=now() WHERE id=%s""",
            (body.supplier_id, snap["vendor_name"], snap["vendor_contact"], snap["vendor_email"], snap["vendor_phone"],
             snap["vendor_address"], snap["vendor_tax_id"], body.title or DEFAULT_TITLE, body.po_date or date.today(),
             body.bill_to or DEFAULT_BILL_TO, body.payment_terms, body.notes, subtotal, total, po_id))
        _write_items(cur, po_id, body.items, amounts)
        conn.commit()
        return _load(cur, po_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar la orden de compra", e)
    finally:
        if conn:
            conn.close()


def set_status(po_id: int, status: str) -> dict:
    """Draft -> Issued (every line needs a price above 0) and Issued -> Cancelled. Nothing goes back."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status FROM purchase_orders WHERE id = %s FOR UPDATE", (po_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "Orden de compra no encontrada", "PO_NOT_FOUND")
        cur_status = row["status"]
        if status == "Issued":
            if cur_status != "Draft":
                raise api_error(400, "Solo una orden en borrador puede emitirse", "PO_BAD_TRANSITION")
            cur.execute("SELECT count(*) AS n FROM po_items WHERE po_id = %s", (po_id,))
            if cur.fetchone()["n"] == 0:
                raise api_error(400, "Agregue al menos un artículo", "PO_NO_ITEMS")
            cur.execute("SELECT count(*) AS n FROM po_items WHERE po_id = %s AND unit_price <= 0", (po_id,))
            if cur.fetchone()["n"] > 0:
                raise api_error(400, "Todas las líneas necesitan un precio mayor que cero para emitir la orden", "PO_PRICE_MISSING")
        elif status == "Cancelled":
            if cur_status != "Issued":
                raise api_error(400, "Solo una orden emitida puede anularse", "PO_BAD_TRANSITION")
        cur.execute("UPDATE purchase_orders SET status = %s, updated_at = now() WHERE id = %s", (status, po_id))
        conn.commit()
        return _load(cur, po_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo cambiar el estado de la orden", e)
    finally:
        if conn:
            conn.close()


def delete_po(po_id: int) -> dict:
    """Draft only. A P.O that came from an RFQ gives the RFQ back (Converted -> Sent)."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status, rfq_id FROM purchase_orders WHERE id = %s FOR UPDATE", (po_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "Orden de compra no encontrada", "PO_NOT_FOUND")
        if row["status"] != "Draft":
            raise api_error(400, "Solo se puede eliminar una orden en borrador", "PO_LOCKED")
        cur.execute("DELETE FROM purchase_orders WHERE id = %s", (po_id,))
        if row["rfq_id"]:
            cur.execute("UPDATE rfqs SET status = 'Sent', updated_at = now() WHERE id = %s AND status = 'Converted'",
                        (row["rfq_id"],))
        conn.commit()
        return {"message": "Orden de compra eliminada correctamente"}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo eliminar la orden de compra", e)
    finally:
        if conn:
            conn.close()


def generate_po_pdf(po_id: int, current_user: dict, print_seal: bool = False) -> StreamingResponse:
    seal = seal_for_pdf(print_seal)
    try:
        po = get_po(po_id)
        stream = create_po_pdf(po, po["items"], signer_name=resolve_signer_name(current_user, po.get("created_by")),
                               seal=seal, company_lines=COMPANY_LINES)
        return StreamingResponse(stream, media_type="application/pdf",
                                 headers={"Content-Disposition": f"attachment; filename={po['label']}.pdf"})
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo generar el PDF de la orden de compra", e)
