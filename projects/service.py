from typing import List, Optional
from datetime import date
from fastapi import HTTPException
from backend.database import get_db_connection
from psycopg2.extras import RealDictCursor

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
    notes: Optional[str]
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Validate client exists
        cursor.execute("SELECT 1 FROM clients WHERE id = %s", (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Client not found")

        # Validate date range if both dates provided
        if start_date and end_date and end_date < start_date:
            raise HTTPException(status_code=400, detail="End date must be after start date")

        # Insert project
        cursor.execute("""
            INSERT INTO projects
            (client_id, name, description, status, start_date, end_date, estimated_budget, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            client_id, name, description, status,
            start_date, end_date, estimated_budget, notes
        ))

        new_id = cursor.fetchone()["id"]
        conn.commit()

        cursor.execute("SELECT * FROM projects WHERE id = %s", (new_id,))
        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Create failed: {str(e)}")

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

        query = """
            SELECT p.*, c.company_name AS client_name
            FROM projects p
            JOIN clients c ON p.client_id = c.id
            WHERE 1=1
        """
        params = []

        if client_id:
            query += " AND p.client_id = %s"
            params.append(client_id)

        if status:
            query += " AND p.status = %s"
            params.append(status)

        query += " ORDER BY p.created_at DESC"

        cursor.execute(query, params)
        return cursor.fetchall()

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

        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Project not found")

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
    notes: Optional[str] = None
) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch current project
        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        current_project = cursor.fetchone()
        if not current_project:
            raise HTTPException(status_code=404, detail="Project not found")

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

        # Validate client if changed
        if client_id is not None:
            cursor.execute("SELECT 1 FROM clients WHERE id = %s", (final_client_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Client not found")

        # Validate date range
        if final_start_date and final_end_date and final_end_date < final_start_date:
            raise HTTPException(status_code=400, detail="End date must be after start date")

        # Validate name is not empty
        if final_name is None or final_name.strip() == "":
            raise HTTPException(status_code=400, detail="Name cannot be empty")

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
            project_id
        ))

        conn.commit()

        cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

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
            raise HTTPException(status_code=404, detail="Project not found")

        conn.commit()
        return {"message": "Project deleted successfully"}

    except HTTPException:
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

    finally:
        if conn:
            conn.close()
