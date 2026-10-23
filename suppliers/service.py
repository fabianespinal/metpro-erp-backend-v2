import logging
from typing import List, Optional

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from core.errors import api_error, internal_error
from core.supplier_features import suppliers_enabled
from database import get_db_connection

logger = logging.getLogger("metpro.suppliers")

COLS = "id, company_name, contact_name, email, phone, address, tax_id, notes, is_active, is_dummy"


def require_enabled() -> None:
    if not suppliers_enabled():
        raise api_error(404, "Suplidores no está habilitado", "SUPPLIERS_DISABLED")


def _check_unique(cur, email: Optional[str], tax_id: Optional[str], exclude_id: Optional[int] = None) -> None:
    if email and "@" not in email:
        raise api_error(400, "Formato de correo no válido", "EMAIL_INVALID")
    other = " AND id != %s" if exclude_id is not None else ""
    extra = (exclude_id,) if exclude_id is not None else ()
    if email:
        cur.execute("SELECT id FROM suppliers WHERE lower(email) = lower(%s)" + other, (email,) + extra)
        if cur.fetchone():
            raise api_error(400, f"El correo {email} ya está en uso por otro suplidor", "SUPPLIER_EMAIL_TAKEN")
    if tax_id:
        cur.execute("SELECT id FROM suppliers WHERE tax_id = %s" + other, (tax_id,) + extra)
        if cur.fetchone():
            raise api_error(400, f"El RNC {tax_id} ya está en uso por otro suplidor", "SUPPLIER_TAX_ID_TAKEN")


def list_suppliers() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SELECT {COLS} FROM suppliers ORDER BY lower(company_name)")
        return cur.fetchall()
    finally:
        if conn:
            conn.close()


def get_supplier(supplier_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(f"SELECT {COLS} FROM suppliers WHERE id = %s", (supplier_id,))
        row = cur.fetchone()
        if not row:
            raise api_error(404, "Suplidor no encontrado", "SUPPLIER_NOT_FOUND")
        return row
    finally:
        if conn:
            conn.close()


def create_supplier(data: dict) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _check_unique(cur, data.get("email"), data.get("tax_id"))
        cur.execute(
            f"""INSERT INTO suppliers (company_name, contact_name, email, phone, address, tax_id, notes, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLS}""",
            (data["company_name"], data.get("contact_name"), data.get("email"), data.get("phone"),
             data.get("address"), data.get("tax_id"), data.get("notes"), data.get("is_active", True)),
        )
        row = cur.fetchone()
        conn.commit()
        return row
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo crear el suplidor", e)
    finally:
        if conn:
            conn.close()


def update_supplier(supplier_id: int, data: dict) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id FROM suppliers WHERE id = %s", (supplier_id,))
        if not cur.fetchone():
            raise api_error(404, "Suplidor no encontrado", "SUPPLIER_NOT_FOUND")
        _check_unique(cur, data.get("email"), data.get("tax_id"), exclude_id=supplier_id)
        cur.execute(
            f"""UPDATE suppliers SET company_name=%s, contact_name=%s, email=%s, phone=%s, address=%s,
                tax_id=%s, notes=%s, is_active=%s, updated_at=now() WHERE id=%s RETURNING {COLS}""",
            (data["company_name"], data.get("contact_name"), data.get("email"), data.get("phone"),
             data.get("address"), data.get("tax_id"), data.get("notes"), data.get("is_active", True), supplier_id),
        )
        row = cur.fetchone()
        conn.commit()
        return row
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar el suplidor", e)
    finally:
        if conn:
            conn.close()


def delete_supplier(supplier_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM suppliers WHERE id = %s", (supplier_id,))
        if cur.rowcount == 0:
            raise api_error(404, "Suplidor no encontrado", "SUPPLIER_NOT_FOUND")
        conn.commit()
        return {"message": "Suplidor eliminado correctamente"}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo eliminar el suplidor", e)
    finally:
        if conn:
            conn.close()
