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
            raise api_error(401, "Invalid username or password", "INVALID_CREDENTIALS")

        if not user.get("is_active", True):
            raise api_error(401, "Account is disabled", "ACCOUNT_DISABLED")

        if not verify_password(credentials.password, user["password_hash"]):
            raise api_error(401, "Invalid username or password", "INVALID_CREDENTIALS")

        token_data = {
            "sub": user["username"],
            "user_id": user["id"],
            "role": user.get("role", "user")
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
        raise api_error(500, "Login temporarily unavailable", "LOGIN_UNAVAILABLE")
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

        cursor.execute("SELECT id FROM users WHERE username = %s", (user_data.username,))
        if cursor.fetchone():
            raise api_error(400, "Username already exists", "USERNAME_TAKEN")

        cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
        if cursor.fetchone():
            raise api_error(400, "Email already exists", "EMAIL_TAKEN")

        password_hash = get_password_hash(user_data.password)

        cursor.execute("""
            INSERT INTO users (username, password_hash, email, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
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
            "message": "User registered successfully",
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
        raise api_error(500, "Registration temporarily unavailable", "REGISTRATION_UNAVAILABLE")
    finally:
        if conn:
            conn.close()


# ============================
# AUTHENTICATED USER INFO
# ============================

@router.get("/me")
def get_current_user(user = Depends(require_auth)):
    return {
        "username": user.get("sub"),
        "user_id": user.get("user_id"),
        "role": user.get("role")
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
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    db_user = cursor.fetchone()

    if not db_user:
        raise api_error(404, "User not found", "USER_NOT_FOUND")

    if not verify_password(data.old_password, db_user["password_hash"]):
        raise api_error(401, "Old password incorrect", "PASSWORD_INCORRECT")

    new_hash = get_password_hash(data.new_password)

    cursor.execute(
        "UPDATE users SET password_hash = %s WHERE username = %s",
        (new_hash, username)
    )

    conn.commit()
    conn.close()

    return {"message": "Password updated successfully"}


# ============================
# ADMIN-ONLY TEST ROUTE
# ============================

@router.get("/admin-only")
def admin_only(user = Depends(require_role("admin"))):
    return {"message": "Admin access confirmed"}
