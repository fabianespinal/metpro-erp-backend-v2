from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from .service import (
    verify_password,
    create_access_token,
    get_password_hash,
    get_current_user_from_bearer,
    require_role
)
from database import get_db_connection
from psycopg2.extras import RealDictCursor

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

@router.post("/login", response_model=LoginResponse)
def login(credentials: LoginRequest):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT * FROM users WHERE username = %s", (credentials.username,))
        user = cursor.fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not user.get("is_active", True):
            raise HTTPException(status_code=401, detail="Account is disabled")

        if not verify_password(credentials.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")
    finally:
        if conn:
            conn.close()


# ============================
# REGISTER
# ============================

@router.post("/register")
def register(user_data: RegisterRequest):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute("SELECT id FROM users WHERE username = %s", (user_data.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists")

        cursor.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Email already exists")

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
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    finally:
        if conn:
            conn.close()


# ============================
# AUTHENTICATED USER INFO
# ============================

@router.get("/me")
def get_current_user(user = Depends(get_current_user_from_bearer)):
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
    user = Depends(get_current_user_from_bearer)
):
    username = user.get("sub")

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    db_user = cursor.fetchone()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(data.old_password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Old password incorrect")

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