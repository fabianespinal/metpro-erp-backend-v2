from core.errors import api_error
from typing import List, Optional
from datetime import date
from fastapi import HTTPException
from database import get_db_connection
from core.errors import internal_error
from psycopg2.extras import RealDictCursor
import logging
from core.numbering import quote_label

logger = logging.getLogger(__name__)

# Projects joined with client and the invoice of their originating quote.
PROJECT_SELECT = """
    SELECT p.*, c.company_name AS client_name,
           inv.id AS invoice_id, inv.invoice_number AS invoice_number
    FROM projects p
    JOIN clients c ON p.client_id = c.id
    LEFT JOIN invoices inv ON inv.quote_id = p.quote_id AND p.quote_id IS NOT NULL
"""


def project_label(project_id) -> str:
    return f"P-{int(project_id):04d}"


def _enrich(row):
    """Add the display numbers: P-0001, Q-10002."""
    if row is None:
        return None
    d = dict(row)
    d["project_number"] = project_label(d["id"])
    d["quote_label"] = quote_label(d["quote_number"]) if d.get("quote_number") else None
    return d


def fetch_project(cursor, project_id: int):
    cursor.execute(PROJECT_SELECT + " WHERE p.id = %s", (project_id,))
    return _enrich(cursor.fetchone())


def create_project_from_quote(cursor, quote_id: str):
    """
    Create the project for an approved quote, in the caller's transaction.
    Idempotent: one project per quote (unique index), a second call is a no-op.
    Returns the new project id, or None when one already exists.
    """
    cursor.execute("""
        SELECT q.quote_id, q.quote_number, q.client_id, q.project_name,
               c.address AS client_address
        FROM quotes q LEFT JOIN clients c ON c.id = q.client_id
        WHERE q.quote_id = %s
    """, (quote_id,))
    q = cursor.fetchone()
    if not q:
        return None

    cursor.execute(
        "SELECT product_name FROM quote_items WHERE quote_id = %s ORDER BY id LIMIT 3", (quote_id,)
    )
    names = [r["product_name"] for r in cursor.fetchall() if r.get("product_name")]
    description = ", ".join(names)[:200] or None
    label = quote_label(q["quote_number"]) if q.get("quote_number") else "sin número"
    name = (q.get("project_name") or "").strip() or f"Proyecto {label}"

    cursor.execute("""
        INSERT INTO projects
            (client_id, name, description, status, start_date, job_site_address, quote_id, quote_number)
        VALUES (%s, %s, %s, 'pending', CURRENT_DATE, %s, %s, %s)
        ON CONFLICT (quote_id) WHERE quote_id IS NOT NULL DO NOTHING
        RETURNING id
    """, (q["client_id"], name, description, q.get("client_address"), q["quote_id"], q.get("quote_number")))
    row = cursor.fetchone()
    return row["id"] if row else None

# ============================================================
# CREATE PROJECT
# ============================================================
def create_project(
    client_id: int,
    name: str,
    description: Optional[str],
    status: str,
    start_date: date,  # NOT NULL per Supabase
    end_date: Optional[date],
    estimated_budget: Optional[float],
    notes: Optional[str],
    job_site_address: Optional[str] = None
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Validate client exists
        cursor.execute("SELECT 1 FROM clients WHERE id = %s", (client_id,))
        if not cursor.fetchone():
            raise api_error(404, "Client not found", "CLIENT_NOT_FOUND")

        # Validate date range if both dates provided
        if start_date and end_date and end_date < start_date:
            raise api_error(400, "End date must be after start date", "DATE_RANGE_INVALID")

        # Insert project
        cursor.execute("""
            INSERT INTO projects
            (client_id, name, description, status, start_date, end_date, estimated_budget, notes, job_site_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            client_id, name, description, status,
            start_date, end_date, estimated_budget, notes, job_site_address
        ))

        new_id = cursor.fetchone()["id"]
        conn.commit()

        return fetch_project(cursor, new_id)

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Create failed", e)

    finally:
        if conn:
            conn.close()

# ============================================================
# GET ALL PROJECTS (WITH FILTERS)
# ============================================================
def get_all_projects(client_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        query = PROJECT_SELECT + " WHERE 1=1"
        params = []

        if client_id:
            query += " AND p.client_id = %s"
            params.append(client_id)

        if status:
            query += " AND p.status = %s"
            params.append(status)

        query += " ORDER BY p.created_at DESC"

        cursor.execute(query, params)
        return [_enrich(r) for r in cursor.fetchall()]

    finally:
        if conn:
            conn.close()

# ============================================================
# GET PROJECT BY ID
# ============================================================
def get_project_by_id(project_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        row = fetch_project(cursor, project_id)

        if not row:
            raise api_error(404, "Project not found", "PROJECT_NOT_FOUND")

        return row

    finally:
        if conn:
            conn.close()

# ============================================================
# UPDATE PROJECT
# ============================================================
def update_project(
    project_id: int,
    client_id: Optional[int] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    estimated_budget: Optional[float] = None,
    notes: Optional[str] = None,
    job_site_address: Optional[str] = None
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch current project
        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        current_project = cursor.fetchone()
        if not current_project:
            raise api_error(404, "Project not found", "PROJECT_NOT_FOUND")

        # -----------------------------
        # Normalization helpers
        # -----------------------------
        def norm_str(v):
            """Convert empty string or whitespace to None"""
            if v is None:
                return None
            if isinstance(v, str) and v.strip() == "":
                return None
            return v

        def norm_float(v, current):
            """Handle empty string, None, or invalid float"""
            if v is None or v == "":
                return current
            try:
                return float(v)
            except (ValueError, TypeError):
                return current

        def norm_date(v, current):
            """Handle None or invalid date"""
            if v is None:
                return current
            return v

        # -----------------------------
        # Final values (safe merging)
        # -----------------------------
        final_client_id = client_id if client_id is not None else current_project["client_id"]
        final_name = name if name is not None else current_project["name"]
        final_description = norm_str(description) if description is not None else current_project["description"]
        final_status = status if status is not None else current_project["status"]
        final_start_date = norm_date(start_date, current_project["start_date"])
        final_end_date = norm_date(end_date, current_project["end_date"])
        final_estimated_budget = norm_float(estimated_budget, current_project["estimated_budget"])
        final_notes = norm_str(notes) if notes is not None else current_project["notes"]
        final_address = norm_str(job_site_address) if job_site_address is not None else current_project["job_site_address"]

        # Validate client if changed
        if client_id is not None:
            cursor.execute("SELECT 1 FROM clients WHERE id = %s", (final_client_id,))
            if not cursor.fetchone():
                raise api_error(404, "Client not found", "CLIENT_NOT_FOUND")

        # Validate date range
        if final_start_date and final_end_date and final_end_date < final_start_date:
            raise api_error(400, "End date must be after start date", "DATE_RANGE_INVALID")

        # Validate name is not empty
        if final_name is None or final_name.strip() == "":
            raise api_error(400, "Name cannot be empty", "NAME_REQUIRED")

        # -----------------------------
        # Perform update
        # -----------------------------
        cursor.execute("""
            UPDATE projects SET
                client_id = %s,
                name = %s,
                description = %s,
                status = %s,
                start_date = %s,
                end_date = %s,  -- FIXED: removed space typo
                estimated_budget = %s,
                notes = %s,
                job_site_address = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            final_client_id,
            final_name,
            final_description,
            final_status,
            final_start_date,
            final_end_date,
            final_estimated_budget,
            final_notes,
            final_address,
            project_id
        ))

        conn.commit()

        return fetch_project(cursor, project_id)

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Update failed", e)

    finally:
        if conn:
            conn.close()

# ============================================================
# DELETE PROJECT
# ============================================================
def delete_project(project_id: int) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        if cursor.rowcount == 0:
            raise api_error(404, "Project not found", "PROJECT_NOT_FOUND")

        conn.commit()
        return {"message": "Project deleted successfully"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Delete failed", e)

    finally:
        if conn:
            conn.close()
