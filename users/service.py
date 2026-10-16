from core.errors import api_error
import uuid
from typing import List, Optional
from psycopg2 import errors as pg_errors
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
# SUPERADMIN PROTECTION
# ============================================================

def _assert_can_manage(actor_role: Optional[str], target_role: Optional[str], new_role: Optional[str] = None) -> None:
    """
    Only a superadmin may act on a superadmin account or grant the superadmin role.
    Admins manage user and admin accounts only.
    """
    if actor_role == "superadmin":
        return
    if target_role == "superadmin" or new_role == "superadmin":
        raise api_error(403, "Only a superadmin can manage superadmin accounts", "SUPERADMIN_REQUIRED")


# ============================================================
# CREATE USER
# ============================================================

def create_user(username: str, password: str, email: str, full_name: Optional[str], role: str = "user",
                actor_role: Optional[str] = None) -> dict:
    conn = None
    try:
        _assert_can_manage(actor_role, None, role)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Case-insensitive uniqueness, matching the lower() unique indexes.
        cursor.execute("SELECT id FROM users WHERE lower(username) = lower(%s)", (username,))
        if cursor.fetchone():
            raise api_error(400, "Username already exists", "USERNAME_TAKEN")

        cursor.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (email,))
        if cursor.fetchone():
            raise api_error(400, "Email already exists", "EMAIL_TAKEN")

        password_hash = get_password_hash(password)

        # users.id has no DB default in production: the app generates the UUID.
        new_id = str(uuid.uuid4())
        try:
            cursor.execute("""
                INSERT INTO users (id, username, password_hash, email, full_name, role, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (new_id, username, password_hash, email, full_name, role, True))
        except pg_errors.UniqueViolation:
            raise api_error(400, "Username or email already exists", "USER_EXISTS")

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

def _assert_other_active_superadmin(cursor, exclude_user_id: str) -> None:
    """Raise 400 unless another active superadmin exists besides exclude_user_id."""
    cursor.execute(
        "SELECT count(*) AS n FROM users WHERE role = 'superadmin' AND is_active AND id <> %s",
        (exclude_user_id,),
    )
    if cursor.fetchone()["n"] == 0:
        raise api_error(400, "Cannot remove the last active superadmin", "LAST_SUPERADMIN")


def update_user(user_id: str, email: Optional[str], full_name: Optional[str],
                role: Optional[str], is_active: Optional[bool], actor_role: Optional[str] = None) -> dict:

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Ensure user exists
        cursor.execute("SELECT id, role, is_active FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if not target:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        _assert_can_manage(actor_role, target["role"], role)

        # Last-superadmin guard: deactivating or demoting the only active superadmin is refused.
        is_target_active_superadmin = target["role"] == "superadmin" and target["is_active"]
        demotes = role is not None and role != "superadmin"
        deactivates = is_active is False
        if is_target_active_superadmin and (demotes or deactivates):
            _assert_other_active_superadmin(cursor, user_id)

        updates = []
        params = []

        if email is not None:
            cursor.execute("SELECT id FROM users WHERE lower(email) = lower(%s) AND id != %s", (email, user_id))
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
            SET password_hash = %s
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

def reset_user_password(user_id: str, new_password: str, actor_role: Optional[str] = None) -> dict:
    """Admin reset. Sets a new password without the current one. Writes password_hash only."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id, role FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if not target:
            raise api_error(404, "User not found", "USER_NOT_FOUND")

        _assert_can_manage(actor_role, target["role"])

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (get_password_hash(new_password), user_id),
        )
        conn.commit()
        return {"message": "Password reset successfully"}

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()
        raise internal_error("Failed to reset password", e)

    finally:
        if conn:
            conn.close()


def delete_user(user_id: str, actor_role: Optional[str] = None) -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT role, is_active FROM users WHERE id = %s", (user_id,))
        target = cursor.fetchone()
        if target:
            _assert_can_manage(actor_role, target["role"])
        # Last-superadmin guard: deleting the only active superadmin is refused.
        if target and target["role"] == "superadmin" and target["is_active"]:
            _assert_other_active_superadmin(cursor, user_id)

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
