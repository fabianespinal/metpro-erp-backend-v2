from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
import csv
import io
import math
from database import get_db_connection
from core.errors import internal_error
from psycopg2.extras import RealDictCursor



def _cell(row: dict, key: str) -> str:
    """CSV cell as stripped text. Rows shorter than the header give None (debug B-09)."""
    return (row.get(key) or "").strip()

def dimensions_enabled() -> bool:
    """B3 switch. Off: the API refuses dimension values and the form hides the section. Stored values stay readable."""
    import os
    return os.environ.get("PRODUCT_DIMENSIONS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _write_dimensions(cursor, product_id: int, dims: Optional[dict]) -> None:
    """Writes only the dimension fields the caller actually sent (a missing field never wipes a stored value),
    then recalculates area and volume for every value that is not manual (B3 rule: products/dimensions.py).
    An explicit null clears a field. Column names come from fixed lists, never from input.

    Manual rule: a typed area (or volume) with no explicit flag is manual. area_manual=false hands it back to the
    calculation. While the switch is off, nulls and false flags are ignored and any real value is refused."""
    from .models import DIMENSION_FIELDS, FLAG_FIELDS
    from .dimensions import derive_area, derive_volume
    if not dims:
        return
    if not dimensions_enabled():
        # Screens send the whole product back, so dimensions arrive as null and flags as false.
        if any(v not in (None, False) for v in dims.values()):
            raise api_error(400, "Las dimensiones de producto no están habilitadas", "PRODUCT_DIMENSIONS_DISABLED")
        return
    dims = dict(dims)
    for value_key, flag_key in (("area", "area_manual"), ("volume", "volume_manual")):
        if flag_key not in dims and dims.get(value_key) is not None:
            dims[flag_key] = True  # typed without a flag = manual override
        if dims.get(flag_key) is True and dims.get(value_key, "unset") is None:
            dims[flag_key] = False  # manual flag with the value cleared: back to calculated
    cols = [c for c in DIMENSION_FIELDS + FLAG_FIELDS if c in dims]
    if cols:
        cursor.execute(
            "UPDATE products SET " + ", ".join(f"{c} = %s" for c in cols) + " WHERE id = %s",
            [dims[c] for c in cols] + [product_id],
        )
    cursor.execute(
        "SELECT length, width, height, thickness, area_manual, volume_manual FROM products WHERE id = %s",
        (product_id,),
    )
    row = cursor.fetchone()
    sets, params = [], []
    if not row["area_manual"]:
        sets.append("area = %s")
        params.append(derive_area(row["length"], row["width"]))
    if not row["volume_manual"]:
        sets.append("volume = %s")
        params.append(derive_volume(row["length"], row["width"], row["height"], row["thickness"]))
    if sets:
        cursor.execute("UPDATE products SET " + ", ".join(sets) + " WHERE id = %s", params + [product_id])


# ============================================================
# CREATE PRODUCT
# ============================================================

def create_product(name: str, description: str, unit_price: float, cost: Optional[float] = None,
                   dims: Optional[dict] = None) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            INSERT INTO products (name, description, unit_price, cost)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (name, description, unit_price, cost))
        new_id = cursor.fetchone()["id"]
        _write_dimensions(cursor, new_id, dims)

        conn.commit()

        cursor.execute("SELECT * FROM products WHERE id = %s", (new_id,))
        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo crear el producto", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# GET ALL PRODUCTS
# ============================================================

def get_all_products() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM products WHERE archived_at IS NULL ORDER BY name")  # X-05
        return cursor.fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# GET PRODUCT BY ID
# ============================================================

def get_product_by_id(product_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        row = cursor.fetchone()

        if not row:
            raise api_error(404, "Producto no encontrado", "PRODUCT_NOT_FOUND")

        return row

    finally:
        if conn:
            conn.close()


# ============================================================
# UPDATE PRODUCT
# ============================================================

def update_product(product_id: int, name: str, description: str, unit_price: float,
                   cost: Optional[float] = None, cost_set: bool = False, dims: Optional[dict] = None) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            raise api_error(404, "Producto no encontrado", "PRODUCT_NOT_FOUND")

        if cost_set:
            cursor.execute("""
                UPDATE products
                SET name = %s, description = %s, unit_price = %s, cost = %s
                WHERE id = %s
            """, (name, description, unit_price, cost, product_id))
        else:
            cursor.execute("""
                UPDATE products
                SET name = %s, description = %s, unit_price = %s
                WHERE id = %s
            """, (name, description, unit_price, product_id))

        _write_dimensions(cursor, product_id, dims)
        conn.commit()

        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo actualizar el producto", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# DELETE PRODUCT
# ============================================================

def delete_product(product_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) AS n FROM template_pack_items WHERE product_id = %s", (product_id,))
        if cursor.fetchone()["n"] > 0:
            raise api_error(400, "El producto se usa en un paquete de plantilla y no se puede eliminar", "PRODUCT_IN_USE")

        cursor.execute("SELECT id FROM products WHERE id = %s AND archived_at IS NULL", (product_id,))
        if not cursor.fetchone():
            raise api_error(404, "Producto no encontrado", "PRODUCT_NOT_FOUND")

        # X-05: a product used on quote or invoice lines is archived, not deleted. The lines keep
        # their product link, so cost estimates and the variance report keep their coverage.
        # Archived products leave the catalog (list, picker, CSV match, product report).
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM quote_items WHERE product_id = %s) "
            "OR EXISTS (SELECT 1 FROM invoice_items WHERE product_id = %s) AS used",
            (product_id, product_id),
        )
        if cursor.fetchone()["used"]:
            cursor.execute("UPDATE products SET archived_at = now() WHERE id = %s", (product_id,))
            conn.commit()
            return {"message": "Producto archivado: se usa en cotizaciones o facturas", "archived": True}

        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
        return {"message": "Producto eliminado correctamente", "archived": False}

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


# ============================================================
# CSV IMPORT
# ============================================================

async def import_products_from_csv(file_content: bytes, filename: str) -> dict:
    conn = None
    try:
        # Decode CSV
        try:
            csv_text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise api_error(400, "El archivo debe estar codificado en UTF-8", "FILE_ENCODING_INVALID")

        rows = list(csv.DictReader(io.StringIO(csv_text)))

        if not rows:
            raise api_error(400, "El archivo CSV está vacío", "CSV_EMPTY")

        required_cols = ["name", "unit_price"]
        if not all(col in rows[0] for col in required_cols):
            raise api_error(400, f"Faltan columnas obligatorias: {required_cols}", "CSV_COLUMNS_MISSING")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        imported = 0
        updated = 0
        skipped = 0

        for row in rows:
            name = _cell(row, "name")
            if not name:
                skipped += 1
                continue

            try:
                unit_price = float(_cell(row, "unit_price"))
            except ValueError:
                skipped += 1
                continue
            # "nan", "inf" and negative prices are skipped (debug B-01).
            if not math.isfinite(unit_price) or unit_price < 0:
                skipped += 1
                continue

            description = _cell(row, "description")

            # Check if product exists (oldest row with that exact name)
            cursor.execute("SELECT id FROM products WHERE name = %s AND archived_at IS NULL ORDER BY id LIMIT 1", (name,))
            existing = cursor.fetchone()

            if existing:
                # Debug B-20: update that one row by id (was every same-name row) and count it.
                cursor.execute("""
                    UPDATE products
                    SET description = %s, unit_price = %s
                    WHERE id = %s
                """, (description, unit_price, existing["id"]))
                updated += 1

            else:
                # Insert new
                cursor.execute("""
                    INSERT INTO products (name, description, unit_price)
                    VALUES (%s, %s, %s)
                """, (name, description, unit_price))
                imported += 1

        conn.commit()

        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "total": len(rows)
        }

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("No se pudo importar", e)

    finally:
        if conn:
            conn.close()
