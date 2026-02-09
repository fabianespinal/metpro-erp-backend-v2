from typing import List, Optional
from fastapi import HTTPException
from database import get_db_connection
from psycopg2.extras import RealDictCursor


# ============================================================
# CREATE PROJECT
# ============================================================

def create_project(
    client_id: int,
    name: str,
    description: Optional[str],
    status: str,
    start_date: str,
    end_date: Optional[str],
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
    client_id: int,
    name: str,
    description: Optional[str],
    status: str,
    start_date: str,
    end_date: Optional[str],
    estimated_budget: Optional[float],
    notes: Optional[str]
) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Verify project exists
        cursor.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")

        # Validate client exists
        cursor.execute("SELECT 1 FROM clients WHERE id = %s", (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Client not found")

        cursor.execute("""
            UPDATE projects SET
                client_id = %s,
                name = %s,
                description = %s,
                status = %s,
                start_date = %s,
                end_date = %s,
                estimated_budget = %s,
                notes = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (
            client_id, name, description, status,
            start_date, end_date, estimated_budget, notes,
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