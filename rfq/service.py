import logging
from datetime import date
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from company_settings.service import seal_for_pdf
from core.errors import api_error, internal_error
from core.rfq_features import rfq_enabled
from database import get_db_connection
from pdf.builder_rfq import create_rfq_pdf
from pdf.utils.signer import resolve_signer_name
from .models import DEFAULT_BILL_TO, DEFAULT_TITLE, rfq_label

logger = logging.getLogger("metpro.rfq")

COMPANY_LINES = ["Parque Industrial Disdo", "Calle Central No. 1, Hato Nuevo Palave", "Tel: (829) 439-8476 | RNC: 131-71683-2"]
RFQ_COLS = ("id, rfq_number, supplier_id, vendor_name, vendor_contact, vendor_email, vendor_phone, vendor_address, "
            "vendor_tax_id, title, rfq_date, bill_to, payment_terms, notes, status, created_by")
ITEM_COLS = "id, position, product_id, item, description, quantity, unit"


def require_enabled() -> None:
    if not rfq_enabled():
        raise api_error(404, "RFQ no está habilitado", "RFQ_DISABLED")


def _shape(row: dict, items: Optional[List[dict]] = None, item_count: Optional[int] = None) -> dict:
    out = dict(row)
    out["label"] = rfq_label(out["rfq_number"])
    out["items"] = [dict(i, quantity=float(i["quantity"])) for i in (items or [])]
    out["item_count"] = item_count if item_count is not None else len(out["items"])
    return out


def _supplier_snapshot(cur, supplier_id: int, keep_if_same_as: Optional[int] = None) -> dict:
    cur.execute("SELECT * FROM suppliers WHERE id = %s", (supplier_id,))
    s = cur.fetchone()
    if not s:
        raise api_error(404, "Suplidor no encontrado", "SUPPLIER_NOT_FOUND")
    if not s["is_active"] and keep_if_same_as != supplier_id:
        raise api_error(400, "El suplidor está inactivo", "SUPPLIER_INACTIVE")
    return {"vendor_name": s["company_name"], "vendor_contact": s["contact_name"], "vendor_email": s["email"],
            "vendor_phone": s["phone"], "vendor_address": s["address"], "vendor_tax_id": s["tax_id"]}


def _check_items(cur, items) -> None:
    if not items:
        raise api_error(400, "Agregue al menos un artículo", "RFQ_NO_ITEMS")
    ids = [i.product_id for i in items if i.product_id is not None]
    if ids:
        cur.execute("SELECT id FROM products WHERE id = ANY(%s)", (ids,))
        found = {r["id"] for r in cur.fetchall()}
        missing = [i for i in ids if i not in found]
        if missing:
            raise api_error(400, "Un producto ya no existe", "RFQ_PRODUCT_NOT_FOUND")


def _write_items(cur, rfq_id: int, items) -> None:
    cur.execute("DELETE FROM rfq_items WHERE rfq_id = %s", (rfq_id,))
    for pos, it in enumerate(items, start=1):
        cur.execute(
            "INSERT INTO rfq_items (rfq_id, position, product_id, item, description, quantity, unit) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (rfq_id, pos, it.product_id, it.item, it.description, it.quantity, it.unit))


def _load(cur, rfq_id: int) -> dict:
    cur.execute(f"SELECT {RFQ_COLS} FROM rfqs WHERE id = %s", (rfq_id,))
    row = cur.fetchone()
    if not row:
        raise api_error(404, "RFQ no encontrado", "RFQ_NOT_FOUND")
    cur.execute(f"SELECT {ITEM_COLS} FROM rfq_items WHERE rfq_id = %s ORDER BY position", (rfq_id,))
    return _shape(row, cur.fetchall())


def list_rfqs() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SELECT {RFQ_COLS}, (SELECT count(*) FROM rfq_items i WHERE i.rfq_id = r.id) AS n "
                    f"FROM rfqs r ORDER BY created_at DESC, id DESC")
        return [_shape({k: v for k, v in r.items() if k != "n"}, [], r["n"]) for r in cur.fetchall()]
    finally:
        if conn:
            conn.close()


def get_rfq(rfq_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        return _load(conn.cursor(cursor_factory=RealDictCursor), rfq_id)
    finally:
        if conn:
            conn.close()


def create_rfq(body, actor: Optional[str]) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        snap = _supplier_snapshot(cur, body.supplier_id)
        _check_items(cur, body.items)
        cur.execute(
            """INSERT INTO rfqs (supplier_id, vendor_name, vendor_contact, vendor_email, vendor_phone, vendor_address,
                                 vendor_tax_id, title, rfq_date, bill_to, payment_terms, notes, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.supplier_id, snap["vendor_name"], snap["vendor_contact"], snap["vendor_email"], snap["vendor_phone"],
             snap["vendor_address"], snap["vendor_tax_id"], body.title or DEFAULT_TITLE, body.rfq_date or date.today(),
             body.bill_to or DEFAULT_BILL_TO, body.payment_terms, body.notes, actor))
        rfq_id = cur.fetchone()["id"]
        _write_items(cur, rfq_id, body.items)
        conn.commit()
        return _load(cur, rfq_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo crear el RFQ", e)
    finally:
        if conn:
            conn.close()


def update_rfq(rfq_id: int, body) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status, supplier_id FROM rfqs WHERE id = %s FOR UPDATE", (rfq_id,))
        cur_row = cur.fetchone()
        if not cur_row:
            raise api_error(404, "RFQ no encontrado", "RFQ_NOT_FOUND")
        if cur_row["status"] != "Draft":
            raise api_error(400, "Solo se puede editar un RFQ en borrador", "RFQ_LOCKED")
        snap = _supplier_snapshot(cur, body.supplier_id, keep_if_same_as=cur_row["supplier_id"])
        _check_items(cur, body.items)
        cur.execute(
            """UPDATE rfqs SET supplier_id=%s, vendor_name=%s, vendor_contact=%s, vendor_email=%s, vendor_phone=%s,
                   vendor_address=%s, vendor_tax_id=%s, title=%s, rfq_date=%s, bill_to=%s, payment_terms=%s,
                   notes=%s, updated_at=now() WHERE id=%s""",
            (body.supplier_id, snap["vendor_name"], snap["vendor_contact"], snap["vendor_email"], snap["vendor_phone"],
             snap["vendor_address"], snap["vendor_tax_id"], body.title or DEFAULT_TITLE, body.rfq_date or date.today(),
             body.bill_to or DEFAULT_BILL_TO, body.payment_terms, body.notes, rfq_id))
        _write_items(cur, rfq_id, body.items)
        conn.commit()
        return _load(cur, rfq_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar el RFQ", e)
    finally:
        if conn:
            conn.close()


def set_status(rfq_id: int, status: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status FROM rfqs WHERE id = %s FOR UPDATE", (rfq_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "RFQ no encontrado", "RFQ_NOT_FOUND")
        if row["status"] == "Converted":
            raise api_error(400, "El RFQ ya fue convertido", "RFQ_LOCKED")
        cur.execute("UPDATE rfqs SET status = %s, updated_at = now() WHERE id = %s", (status, rfq_id))
        conn.commit()
        return _load(cur, rfq_id)
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo cambiar el estado del RFQ", e)
    finally:
        if conn:
            conn.close()


def delete_rfq(rfq_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT status FROM rfqs WHERE id = %s FOR UPDATE", (rfq_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "RFQ no encontrado", "RFQ_NOT_FOUND")
        if row["status"] != "Draft":
            raise api_error(400, "Solo se puede eliminar un RFQ en borrador", "RFQ_LOCKED")
        cur.execute("DELETE FROM rfqs WHERE id = %s", (rfq_id,))
        conn.commit()
        return {"message": "RFQ eliminado correctamente"}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo eliminar el RFQ", e)
    finally:
        if conn:
            conn.close()


def generate_rfq_pdf(rfq_id: int, current_user: dict, print_seal: bool = False) -> StreamingResponse:
    seal = seal_for_pdf(print_seal)
    try:
        rfq = get_rfq(rfq_id)
        stream = create_rfq_pdf(rfq, rfq["items"], signer_name=resolve_signer_name(current_user, rfq.get("created_by")),
                                seal=seal, company_lines=COMPANY_LINES)
        return StreamingResponse(stream, media_type="application/pdf",
                                 headers={"Content-Disposition": f"attachment; filename={rfq['label']}.pdf"})
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error("No se pudo generar el PDF del RFQ", e)
