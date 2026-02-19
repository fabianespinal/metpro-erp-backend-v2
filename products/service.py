from typing import List
from fastapi import HTTPException
import csv
import io
from backend.database import get_db_connection
from psycopg2.extras import RealDictCursor


# ============================================================
# CREATE PRODUCT
# ============================================================

def create_product(name: str, description: str, unit_price: float) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            INSERT INTO products (name, description, unit_price)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (name, description, unit_price))

        new_id = cursor.fetchone()["id"]
        conn.commit()

        cursor.execute("SELECT * FROM products WHERE id = %s", (new_id,))
        return cursor.fetchone()

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

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

        cursor.execute("SELECT * FROM products ORDER BY name")
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
            raise HTTPException(status_code=404, detail="Product not found")

        return row

    finally:
        if conn:
            conn.close()


# ============================================================
# UPDATE PRODUCT
# ============================================================

def update_product(product_id: int, name: str, description: str, unit_price: float) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id FROM products WHERE id = %s", (product_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Product not found")

        cursor.execute("""
            UPDATE products
            SET name = %s, description = %s, unit_price = %s
            WHERE id = %s
        """, (name, description, unit_price, product_id))

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
        raise HTTPException(status_code=500, detail=f"Failed to update product: {str(e)}")

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

        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")

        conn.commit()
        return {"message": "Product deleted successfully"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

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
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

        rows = list(csv.DictReader(io.StringIO(csv_text)))

        if not rows:
            raise HTTPException(status_code=400, detail="CSV file is empty")

        required_cols = ["name", "unit_price"]
        if not all(col in rows[0] for col in required_cols):
            raise HTTPException(
                status_code=400,
                detail=f"Missing required columns: {required_cols}"
            )

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        imported = 0
        skipped = 0

        for row in rows:
            name = row.get("name", "").strip()
            if not name:
                skipped += 1
                continue

            try:
                unit_price = float(row.get("unit_price", 0))
            except ValueError:
                skipped += 1
                continue

            description = row.get("description", "").strip()

            # Check if product exists
            cursor.execute("SELECT id FROM products WHERE name = %s", (name,))
            existing = cursor.fetchone()

            if existing:
                # Update existing
                cursor.execute("""
                    UPDATE products
                    SET description = %s, unit_price = %s
                    WHERE name = %s
                """, (description, unit_price, name))

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
            "skipped": skipped,
            "total": len(rows)
        }

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

    finally:
        if conn:
            conn.close()
