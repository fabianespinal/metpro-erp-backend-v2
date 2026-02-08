from typing import List, Optional
from fastapi import HTTPException
from config.database import get_db_connection

def create_project(client_id: int, name: str, description: Optional[str], status: str,
                   start_date: str, end_date: Optional[str], estimated_budget: Optional[float],
                   notes: Optional[str]) -> dict:
    """Create new project"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Validate client exists
        cursor.execute('SELECT 1 FROM clients WHERE id = ?', (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Client not found')
        
        # Insert project
        cursor.execute('''
            INSERT INTO projects 
            (client_id, name, description, status, start_date, end_date, estimated_budget, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (client_id, name, description, status, start_date, end_date, estimated_budget, notes))
        
        project_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        return dict(cursor.fetchone())
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Create failed: {str(e)}')
    finally:
        if conn:
            conn.close()

def get_all_projects(client_id: Optional[int] = None, status: Optional[str] = None) -> List[dict]:
    """List projects with optional filters"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT p.*, c.company_name as client_name
            FROM projects p
            JOIN clients c ON p.client_id = c.id
            WHERE 1=1
        '''
        params = []
        
        if client_id:
            query += ' AND p.client_id = ?'
            params.append(client_id)
        if status:
            query += ' AND p.status = ?'
            params.append(status)
        
        query += ' ORDER BY p.created_at DESC'
        cursor.execute(query, params)
        
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()

def get_project_by_id(project_id: int) -> dict:
    """Get single project"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Project not found')
        return dict(row)
    finally:
        if conn:
            conn.close()

def update_project(project_id: int, client_id: int, name: str, description: Optional[str],
                   status: str, start_date: str, end_date: Optional[str],
                   estimated_budget: Optional[float], notes: Optional[str]) -> dict:
    """Update project"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Verify project exists
        cursor.execute('SELECT 1 FROM projects WHERE id = ?', (project_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Project not found')
        
        # Validate client exists
        cursor.execute('SELECT 1 FROM clients WHERE id = ?', (client_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='Client not found')
        
        cursor.execute('''
            UPDATE projects SET
                client_id = ?,
                name = ?,
                description = ?,
                status = ?,
                start_date = ?,
                end_date = ?,
                estimated_budget = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (client_id, name, description, status, start_date, end_date, 
              estimated_budget, notes, project_id))
        
        conn.commit()
        
        cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
        return dict(cursor.fetchone())
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Update failed: {str(e)}')
    finally:
        if conn:
            conn.close()

def delete_project(project_id: int) -> dict:
    """Delete project"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='Project not found')
        conn.commit()
        return {'message': 'Project deleted successfully'}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Delete failed: {str(e)}')
    finally:
        if conn:
            conn.close()
