from core.errors import api_error
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from .service import (
    verify_password,
    create_access_token,
    get_password_hash,
    require_auth,
    require_role
)
from database import get_db_connection
from core.rate_limit import login_rate_limit
from psycopg2.extras import RealDictCursor
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# ============================
# MODELS
# ============================

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str
    full_name: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ============================
# CORS PREFLIGHT FIX
# ============================

@router.options("/login")
def login_options():
    return {"message": "OK"}


# ============================
# LOGIN
# ============================

@router.post("/login", response_model=LoginResponse, dependencies=[Depends(login_rate_limit)])
def login(credentials: LoginRequest):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM users WHERE username = %s", (credentials.username,))
        user = cursor.fetchone()

        if not user:
            raise api_error(401, "Usuario o contraseña incorrectos", "INVALID_CREDENTIALS")

        if not user.get("is_active", True):
            raise api_error(401, "La cuenta está deshabilitada", "ACCOUNT_DISABLED")

        if not verify_password(credentials.password, user["password_hash"]):
            raise api_error(401, "Usuario o contraseña incorrectos", "INVALID_CREDENTIALS")

        token_data = {
            "sub": user["username"],
            "user_id": user["id"],
            "role": user.get("role", "user"),
            "name": user.get("full_name"),  # may be None; frontend falls back to username
        }

        access_token = create_access_token(token_data)

        return LoginResponse(
            access_token=access_token,
            username=user["username"]
        )

    except HTTPException:
        raise
    except Exception:
        # Full detail goes to server logs only. Never return driver or DSN errors to the client.
        logger.exception("Login failed due to an internal error")
        raise api_error(500, "El inicio de sesión no está disponible temporalmente", "LOGIN_UNAVAILABLE")
    finally:
        if conn:
            conn.close()


# ============================
# REGISTER
# ============================

@router.post("/register")
def register(user_data: RegisterRequest, _admin: dict = Depends(require_role("admin"))):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id FROM users WHERE lower(username) = lower(%s)", (user_data.username,))
        if cursor.fetchone():
            raise api_error(400, "El nombre de usuario ya existe", "USERNAME_TAKEN")

        cursor.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (user_data.email,))
        if cursor.fetchone():
            raise api_error(400, "El correo ya existe", "EMAIL_TAKEN")

        password_hash = get_password_hash(user_data.password)

        cursor.execute("""
            INSERT INTO users (id, username, password_hash, email, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            str(uuid.uuid4()),
            user_data.username,
            password_hash,
            user_data.email,
            user_data.full_name,
            "user",
            True
        ))

        new_user = cursor.fetchone()
        conn.commit()

        return {
            "message": "Usuario registrado correctamente",
            "user_id": new_user["id"],
            "username": user_data.username
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Registration failed due to an internal error")
        raise api_error(500, "El registro no está disponible temporalmente", "REGISTRATION_UNAVAILABLE")
    finally:
        if conn:
            conn.close()


# ============================
# AUTHENTICATED USER INFO
# ============================

@router.get("/me")
def get_current_user(user = Depends(require_auth)):
    """
    Current user: username, user_id, role, name.
    role is the DB role (require_auth). name is read from users.full_name so an
    edited name shows without a new login; it falls back to the token claim.
    """
    name = user.get("name")
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT full_name FROM users WHERE username = %s", (user.get("sub"),))
        row = cursor.fetchone()
        if row and row.get("full_name"):
            name = row["full_name"]
    except Exception:
        logger.exception("auth/me: full_name lookup failed; using token claim")
    finally:
        if conn:
            conn.close()
    return {
        "username": user.get("sub"),
        "user_id": user.get("user_id"),
        "role": user.get("role"),
        "name": name,
    }


# ============================
# CHANGE PASSWORD
# ============================

@router.post("/change-password")
def change_password(
    data: ChangePasswordRequest,
    user = Depends(require_auth)
):
    username = user.get("sub")

    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        db_user = cursor.fetchone()

        if not db_user:
            raise api_error(404, "Usuario no encontrado", "USER_NOT_FOUND")

        if not verify_password(data.old_password, db_user["password_hash"]):
            raise api_error(401, "La contraseña anterior es incorrecta", "PASSWORD_INCORRECT")

        new_hash = get_password_hash(data.new_password)

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE username = %s",
            (new_hash, username)
        )
        conn.commit()
        return {"message": "Contraseña actualizada correctamente"}
    except Exception:
        conn.rollback()
        raise
    finally:
        # Always returned/closed, including the 404 and 401 paths (was leaked).
        conn.close()


# ============================
# ADMIN-ONLY TEST ROUTE
# ============================

@router.get("/admin-only")
def admin_only(user = Depends(require_role("admin"))):
    return {"message": "Acceso de administrador confirmado"}
