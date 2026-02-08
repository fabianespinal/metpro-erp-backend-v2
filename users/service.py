from typing import List, Optional
from fastapi import HTTPException
from config.database import get_db_connection
from auth.service import get_password_hash, verify_password

def get_all_users() -> List[dict]:
    """Get all users"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            ORDER BY created_at DESC
        ''')
        return [dict(row) for row in cursor.fetchall()]
    finally:
        if conn:
            conn.close()

def get_user_by_id(user_id: int) -> dict:
    """Get user by ID"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users WHERE id = ?
        ''', (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        return dict(user)
    finally:
        if conn:
            conn.close()

def get_user_by_username(username: str) -> dict:
    """Get user by username"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users WHERE username = ?
        ''', (username,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        return dict(user)
    finally:
        if conn:
            conn.close()

def create_user(username: str, password: str, email: str, full_name: str, role: str = 'user') -> dict:
    """Create new user"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if username exists
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail='Username already exists')
        
        # Check if email exists
        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail='Email already exists')
        
        # Hash password
        password_hash = get_password_hash(password)
        
        # Insert user
        cursor.execute('''
            INSERT INTO users (username, password_hash, email, full_name, role, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, password_hash, email, full_name, role, 1))
        
        user_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute('''
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users WHERE id = ?
        ''', (user_id,))
        return dict(cursor.fetchone())
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to create user: {str(e)}')
    finally:
        if conn:
            conn.close()

def update_user(user_id: int, email: Optional[str], full_name: Optional[str], 
                role: Optional[str], is_active: Optional[bool]) -> dict:
    """Update user"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check user exists
        cursor.execute('SELECT id FROM users WHERE id = ?', (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail='User not found')
        
        # Build update query dynamically
        updates = []
        params = []
        
        if email is not None:
            # Check email uniqueness
            cursor.execute('SELECT id FROM users WHERE email = ? AND id != ?', (email, user_id))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail='Email already exists')
            updates.append('email = ?')
            params.append(email)
        
        if full_name is not None:
            updates.append('full_name = ?')
            params.append(full_name)
        
        if role is not None:
            updates.append('role = ?')
            params.append(role)
        
        if is_active is not None:
            updates.append('is_active = ?')
            params.append(1 if is_active else 0)
        
        if not updates:
            raise HTTPException(status_code=400, detail='No fields to update')
        
        updates.append('updated_at = CURRENT_TIMESTAMP')
        params.append(user_id)
        
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()
        
        cursor.execute('''
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users WHERE id = ?
        ''', (user_id,))
        return dict(cursor.fetchone())
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to update user: {str(e)}')
    finally:
        if conn:
            conn.close()

def update_user_password(user_id: int, current_password: str, new_password: str) -> dict:
    """Update user password"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current password hash
        cursor.execute('SELECT password_hash FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail='User not found')
        
        # Verify current password
        if not verify_password(current_password, user['password_hash']):
            raise HTTPException(status_code=400, detail='Current password is incorrect')
        
        # Hash new password
        new_password_hash = get_password_hash(new_password)
        
        # Update password
        cursor.execute('''
            UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (new_password_hash, user_id))
        
        conn.commit()
        
        return {'message': 'Password updated successfully'}
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to update password: {str(e)}')
    finally:
        if conn:
            conn.close()

def delete_user(user_id: int) -> dict:
    """Delete user"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail='User not found')
        
        conn.commit()
        return {'message': 'User deleted successfully'}
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Failed to delete user: {str(e)}')
    finally:
        if conn:
            conn.close()
