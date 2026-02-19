from typing import List, Optional
from fastapi import HTTPException
import csv
import io
from datetime import datetime
from backend.database import get_db_connection
from psycopg2.extras import RealDictCursor


# ============================================================
# CREATE CLIENT
# ============================================================

def create_client(company_name: str, contact_name: Optional[str], email: Optional[str],
                  phone: Optional[str], address: Optional[str], tax_id: Optional[str],
                  notes: Optional[str]) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            INSERT INTO clients
            (company_name, contact_name, email, phone, address, tax_id, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (company_name, contact_name, email, phone, address, tax_id, notes))

        new_id = cursor.fetchone()["id"]
        conn.commit()

        cursor.execute("SELECT * FROM clients WHERE id = %s", (new_id,))
        return cursor.fetchone()

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if conn:
            conn.close()


# ============================================================
# GET ALL CLIENTS
# ============================================================

def get_all_clients() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM clients ORDER BY company_name")
        return cursor.fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# GET CLIENT BY ID
# ============================================================

def get_client_by_id(client_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Client not found")

        return row

    finally:
        if conn:
            conn.close()


# ============================================================
# UPDATE CLIENT
# ============================================================

def update_client(client_id: int, company_name: str, contact_name: Optional[str],
                  email: Optional[str], phone: Optional[str], address: Optional[str],
                  tax_id: Optional[str], notes: Optional[str]) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check existence
        cursor.execute("SELECT id FROM clients WHERE id = %s", (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Client with ID {client_id} not found")

        # Validate email
        if email and "@" not in email:
            raise HTTPException(status_code=400, detail="Invalid email format")

        # Duplicate email
        if email:
            cursor.execute(
                "SELECT id FROM clients WHERE email = %s AND id != %s",
                (email, client_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"Email {email} is already in use by another client"
                )

        # Duplicate tax_id
        if tax_id:
            cursor.execute(
                "SELECT id FROM clients WHERE tax_id = %s AND id != %s",
                (tax_id, client_id)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"Tax ID {tax_id} is already in use by another client"
                )

        # Update
        cursor.execute("""
            UPDATE clients
            SET
                company_name = %s,
                contact_name = %s,
                email = %s,
                phone = %s,
                address = %s,
                tax_id = %s,
                notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (company_name, contact_name, email, phone, address, tax_id, notes, client_id))

        conn.commit()

        cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update client: {str(e)}")

    finally:
        if conn:
            conn.close()


# ============================================================
# DELETE CLIENT
# ============================================================

def delete_client(client_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Client not found")

        conn.commit()
        return {"message": "Client deleted successfully"}

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

async def import_clients_from_csv(file_content: bytes, filename: str, skip_duplicates: bool, current_user: dict) -> dict:
    conn = None
    errors = []

    try:
        # Decode CSV
        try:
            csv_text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

        rows = list(csv.DictReader(io.StringIO(csv_text)))

        if not rows:
            raise HTTPException(status_code=400, detail="CSV file is empty")

        if "company_name" not in rows[0]:
            raise HTTPException(status_code=400, detail="Missing required column: company_name")

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        inserted = updated = skipped = 0

        for idx, row in enumerate(rows, start=2):
            company = row.get("company_name", "").strip()
            if not company:
                errors.append(f"Row {idx}: Skipped (empty company_name)")
                skipped += 1
                continue

            email = row.get("email", "").strip()
            if email and "@" not in email:
                errors.append(f"Row {idx} ({company}): Invalid email format")
                skipped += 1
                continue

            # Check duplicates
            existing_id = None

            if row.get("tax_id"):
                cursor.execute("SELECT id FROM clients WHERE tax_id = %s", (row["tax_id"].strip(),))
                result = cursor.fetchone()
                if result:
                    existing_id = result["id"]

            if not existing_id and email:
                cursor.execute("SELECT id FROM clients WHERE email = %s", (email,))
                result = cursor.fetchone()
                if result:
                    existing_id = result["id"]

            # Duplicate handling
            if existing_id:
                if skip_duplicates:
                    errors.append(f"Row {idx} ({company}): Skipped (duplicate found)")
                    skipped += 1
                else:
                    cursor.execute("""
                        UPDATE clients
                        SET contact_name = %s, phone = %s, address = %s, notes = %s
                        WHERE id = %s
                    """, (
                        row.get("contact_name", "").strip(),
                        row.get("phone", "").strip(),
                        row.get("address", "").strip(),
                        row.get("notes", "").strip(),
                        existing_id
                    ))
                    updated += 1
                continue

            # Insert new client
            try:
                cursor.execute("""
                    INSERT INTO clients
                    (company_name, contact_name, email, phone, address, tax_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    company,
                    row.get("contact_name", "").strip(),
                    email,
                    row.get("phone", "").strip(),
                    row.get("address", "").strip(),
                    row.get("tax_id", "").strip(),
                    row.get("notes", "").strip()
                ))
                inserted += 1

            except Exception as e:
                errors.append(f"Row {idx} ({company}): {str(e)[:80]}")
                skipped += 1

        conn.commit()

        return {
            "success": True,
            "summary": {
                "filename": filename,
                "total_rows": len(rows),
                "processed": inserted + updated + skipped,
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "errors_count": len(errors)
            },
            "errors": errors,
            "audit_log": {
                "uploaded_by": current_user.get("sub", "unknown"),
                "timestamp": datetime.now().isoformat(),
                "action": "skip_duplicates" if skip_duplicates else "overwrite_existing"
            }
        }

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        errors.append(f"System error: {str(e)[:100]}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)[:100]}")

    finally:
        if conn:
            conn.close()
