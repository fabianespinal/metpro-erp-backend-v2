from core.errors import api_error
from typing import List, Optional
from fastapi import HTTPException
from database import get_db_connection
from core.errors import internal_error
from auth.service import get_password_hash, verify_password
from psycopg2.extras import RealDictCursor


# ============================================================
# GET ALL USERS
# ============================================================

def get_all_users() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            ORDER BY created_at DESC
        """)

        return cursor.fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# GET USER BY ID
# ============================================================

def get_user_by_id(user_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            WHERE id = %s
        """, (user_id,))

        user = cursor.fetchone()
        if not user:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        return user

    finally:
        if conn:
            conn.close()


# ============================================================
# GET USER BY USERNAME
# ============================================================

def get_user_by_username(username: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            WHERE username = %s
        """, (username,))

        user = cursor.fetchone()
        if not user:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        return user

    finally:
        if conn:
            conn.close()


# ============================================================
# CREATE USER
# ============================================================

def create_user(username: str, password: str, email: str, full_name: str, role: str = "user") -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Check username
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            raise api_error(400, "Username already exists", "USERNAME_TAKEN")

        # Check email
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            raise api_error(400, "Email already exists", "EMAIL_TAKEN")

        password_hash = get_password_hash(password)

        cursor.execute("""
            INSERT INTO users (username, password_hash, email, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (username, password_hash, email, full_name, role, True))

        new_user = cursor.fetchone()
        conn.commit()

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            WHERE id = %s
        """, (new_user["id"],))

        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to create user", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# UPDATE USER
# ============================================================

def update_user(user_id: str, email: Optional[str], full_name: Optional[str],
                role: Optional[str], is_active: Optional[bool]) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Ensure user exists
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        updates = []
        params = []

        if email is not None:
            cursor.execute("SELECT id FROM users WHERE email = %s AND id != %s", (email, user_id))
            if cursor.fetchone():
                raise api_error(400, "Email already exists", "EMAIL_TAKEN")
            updates.append("email = %s")
            params.append(email)

        if full_name is not None:
            updates.append("full_name = %s")
            params.append(full_name)

        if role is not None:
            updates.append("role = %s")
            params.append(role)

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        if not updates:
            raise api_error(400, "No fields to update", "NO_FIELDS_TO_UPDATE")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)

        query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s"
        cursor.execute(query, params)

        conn.commit()

        cursor.execute("""
            SELECT id, username, email, full_name, role, is_active, created_at
            FROM users
            WHERE id = %s
        """, (user_id,))

        return cursor.fetchone()

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to update user", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# UPDATE USER PASSWORD
# ============================================================

def update_user_password(user_id: str, current_password: str, new_password: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        if not user:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        if not verify_password(current_password, user["password_hash"]):
            raise api_error(400, "Current password is incorrect", "PASSWORD_INCORRECT")

        new_hash = get_password_hash(new_password)

        cursor.execute("""
            UPDATE users
            SET password_hash = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (new_hash, user_id))

        conn.commit()

        return {"message": "Password updated successfully"}

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to update password", e)

    finally:
        if conn:
            conn.close()


# ============================================================
# DELETE USER
# ============================================================

def delete_user(user_id: str) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))

        if cursor.rowcount == 0:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        conn.commit()
        return {"message": "User deleted successfully"}

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to delete user", e)

    finally:
        if conn:
            conn.close()
