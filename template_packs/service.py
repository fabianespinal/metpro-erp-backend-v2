"""Template packs: predefined product groups for quoting.

Writes are admin-only (enforced in the router). Reads are open to any
authenticated user. Each write runs in one transaction.
"""
from typing import Iterable, List

from psycopg2.extras import RealDictCursor

from core.errors import api_error, internal_error
from database import get_db_connection

from .models import PackIn


def _check_products_exist(cursor, product_ids: Iterable[int]) -> None:
    ids = sorted(set(product_ids))
    if not ids:
        return
    cursor.execute("SELECT id FROM products WHERE id = ANY(%s)", (ids,))
    found = {row["id"] for row in cursor.fetchall()}
    missing = [pid for pid in ids if pid not in found]
    if missing:
        raise api_error(
            400,
            f"Products not found: {', '.join(str(m) for m in missing)}",
            "TEMPLATE_PRODUCT_NOT_FOUND",
        )


def _insert_categories(cursor, pack_id: int, categories: List) -> None:
    for cat in categories:
        cursor.execute(
            """
            INSERT INTO template_pack_categories (pack_id, name, sort_order)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (pack_id, cat.name, cat.sort_order),
        )
        category_id = cursor.fetchone()["id"]
        for item in cat.items:
            cursor.execute(
                """
                INSERT INTO template_pack_items
                    (category_id, product_id, default_qty, optional, sort_order, pack_price_override)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (category_id, item.product_id, item.default_qty, item.optional, item.sort_order,
                 item.pack_price_override),
            )


def _insert_charges(cursor, pack_id: int, charges: List) -> None:
    for i, ch in enumerate(charges):
        cursor.execute(
            """
            INSERT INTO template_pack_charges
                (pack_id, name, type, value, enabled_by_default, sort_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (pack_id, ch.name, ch.type, ch.value, ch.enabled_by_default, i),
        )


def _effective_price(catalog, override):
    """Override wins when set (0 is a valid override). Else the catalog price."""
    if override is not None:
        return float(override)
    return float(catalog) if catalog is not None else None


def _load_pack(cursor, pack_id: int) -> dict:
    cursor.execute(
        "SELECT id, name, description, created_at, updated_at FROM template_packs WHERE id = %s",
        (pack_id,),
    )
    pack = cursor.fetchone()
    if not pack:
        raise api_error(404, "Template pack not found", "TEMPLATE_PACK_NOT_FOUND")
    pack = dict(pack)

    cursor.execute(
        """
        SELECT id, name, sort_order
        FROM template_pack_categories
        WHERE pack_id = %s
        ORDER BY sort_order, id
        """,
        (pack_id,),
    )
    categories = [dict(r, items=[]) for r in cursor.fetchall()]
    by_id = {c["id"]: c for c in categories}

    if categories:
        cursor.execute(
            """
            SELECT i.id, i.category_id, i.product_id, p.name AS product_name,
                   p.unit_price AS catalog_price, i.pack_price_override,
                   i.default_qty, i.optional, i.sort_order
            FROM template_pack_items i
            JOIN template_pack_categories c ON c.id = i.category_id
            LEFT JOIN products p ON p.id = i.product_id
            WHERE c.pack_id = %s
            ORDER BY i.sort_order, i.id
            """,
            (pack_id,),
        )
        for row in cursor.fetchall():
            row = dict(row)
            row["unit_price"] = _effective_price(row["catalog_price"], row["pack_price_override"])
            category_id = row.pop("category_id")
            if category_id in by_id:
                by_id[category_id]["items"].append(row)

    pack["categories"] = categories

    cursor.execute(
        """
        SELECT id, name, type, value, enabled_by_default, sort_order
        FROM template_pack_charges
        WHERE pack_id = %s
        ORDER BY sort_order, id
        """,
        (pack_id,),
    )
    pack["charges"] = [dict(r) for r in cursor.fetchall()]
    return pack


# ============================================================
# LIST / GET (any authenticated user)
# ============================================================

def list_packs() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT p.id, p.name, p.description, p.updated_at,
                   (SELECT COUNT(*) FROM template_pack_categories c WHERE c.pack_id = p.id)
                       AS category_count,
                   (SELECT COUNT(*) FROM template_pack_items i
                       JOIN template_pack_categories c ON c.id = i.category_id
                       WHERE c.pack_id = p.id) AS item_count
            FROM template_packs p
            ORDER BY p.name, p.id
            """
        )
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        raise internal_error("template pack list", e)
    finally:
        if conn:
            conn.close()


def get_pack(pack_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        return _load_pack(cursor, pack_id)
    except Exception as e:
        if getattr(e, "code", None):
            raise
        raise internal_error("template pack get", e)
    finally:
        if conn:
            conn.close()


# ============================================================
# WRITE (admin only, enforced in router)
# ============================================================

def create_pack(data: PackIn) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        _check_products_exist(
            cursor,
            (item.product_id for cat in data.categories for item in cat.items),
        )
        cursor.execute(
            """
            INSERT INTO template_packs (name, description)
            VALUES (%s, %s)
            RETURNING id
            """,
            (data.name, data.description),
        )
        pack_id = cursor.fetchone()["id"]
        _insert_categories(cursor, pack_id, data.categories)
        _insert_charges(cursor, pack_id, data.charges)
        conn.commit()
        return _load_pack(cursor, pack_id)
    except Exception as e:
        if conn:
            conn.rollback()
        if getattr(e, "code", None):
            raise
        raise internal_error("template pack create", e)
    finally:
        if conn:
            conn.close()


def update_pack(pack_id: int, data: PackIn) -> dict:
    """Replace name, description, and the full category/item tree."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id FROM template_packs WHERE id = %s", (pack_id,))
        if not cursor.fetchone():
            raise api_error(404, "Template pack not found", "TEMPLATE_PACK_NOT_FOUND")
        _check_products_exist(
            cursor,
            (item.product_id for cat in data.categories for item in cat.items),
        )
        cursor.execute(
            """
            UPDATE template_packs
            SET name = %s, description = %s, updated_at = now()
            WHERE id = %s
            """,
            (data.name, data.description, pack_id),
        )
        # Categories cascade-delete their items.
        cursor.execute("DELETE FROM template_pack_categories WHERE pack_id = %s", (pack_id,))
        _insert_categories(cursor, pack_id, data.categories)
        cursor.execute("DELETE FROM template_pack_charges WHERE pack_id = %s", (pack_id,))
        _insert_charges(cursor, pack_id, data.charges)
        conn.commit()
        return _load_pack(cursor, pack_id)
    except Exception as e:
        if conn:
            conn.rollback()
        if getattr(e, "code", None):
            raise
        raise internal_error("template pack update", e)
    finally:
        if conn:
            conn.close()


def delete_pack(pack_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("DELETE FROM template_packs WHERE id = %s RETURNING id", (pack_id,))
        if not cursor.fetchone():
            conn.rollback()
            raise api_error(404, "Template pack not found", "TEMPLATE_PACK_NOT_FOUND")
        conn.commit()
        return {"message": "Template pack deleted", "id": pack_id}
    except Exception as e:
        if conn:
            conn.rollback()
        if getattr(e, "code", None):
            raise
        raise internal_error("template pack delete", e)
    finally:
        if conn:
            conn.close()
