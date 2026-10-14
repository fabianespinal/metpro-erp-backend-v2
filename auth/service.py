from core.errors import api_error
from core.rate_limit import enforce_user_limit
from core.request_log import mark_authenticated
import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Header
from jose import JWTError, ExpiredSignatureError, jwt
from passlib.context import CryptContext

# =========================
# JWT / SECURITY CONFIG
# =========================

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
# When true, every authenticated request checks users.is_active.
ENFORCE_ACTIVE_CHECK = os.environ.get("ENFORCE_ACTIVE_CHECK", "true").lower() == "true"

# Password hashing setup
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


# =========================
# PASSWORD HELPERS
# =========================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


# =========================
# TOKEN CREATION
# =========================

def create_access_token(data: dict) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# =========================
# UNIFIED TOKEN VALIDATION
# =========================
# Every protected route reaches this function through require_auth.
# Keep it the only place a JWT is accepted.

_REQUIRED_CLAIMS = {"require_sub": True, "require_exp": True}


def _validate_access_token(token: str) -> dict:
    """
    Validate a bearer JWT and return its payload.

    Rules, in order:
      1. Token must be non-empty.
      2. Signature must verify with HS256 only (algorithms pinned).
      3. Token must be unexpired and carry an "exp" claim.
      4. Token must carry a non-empty string "sub" claim.
      5. The user named in "sub" must exist and be active (see _assert_user_active).
    """
    if not token:
        raise api_error(401, "Token is empty", "TOKEN_EMPTY")

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options=_REQUIRED_CLAIMS,
        )
    except ExpiredSignatureError:
        raise api_error(401, "Token expired", "TOKEN_EXPIRED")
    except JWTError:
        raise api_error(401, "Invalid token", "TOKEN_INVALID")

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise api_error(401, "Invalid token", "TOKEN_INVALID")

    _assert_user_active(sub)
    return payload


# =========================
# TOKEN VERIFICATION (HEADER OR QUERY)
# =========================

def _assert_user_active(username) -> None:
    """
    Reject tokens whose user was deactivated or deleted after the token was issued.
    Runs on every authenticated request when ENFORCE_ACTIVE_CHECK is true.
    """
    if not ENFORCE_ACTIVE_CHECK:
        return
    if not username:
        raise api_error(401, "Invalid token", "TOKEN_INVALID")
    from database import get_db_connection
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT is_active FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise api_error(401, "User not found", "USER_NOT_FOUND")
    active = row["is_active"] if isinstance(row, dict) else row[0]
    if not active:
        raise api_error(401, "Account disabled", "ACCOUNT_DISABLED")


def require_auth(authorization: str = Header(None)) -> dict:
    """
    The single authentication dependency for every protected route.
    Reads "Authorization: Bearer <token>", then validates it through
    _validate_access_token. Returns the decoded payload.
    """
    if not authorization:
        raise api_error(401, "Missing authorization token", "TOKEN_MISSING")

    try:
        scheme, token = authorization.split()
    except ValueError:
        raise api_error(401, "Invalid authorization header format", "AUTH_HEADER_INVALID")

    if scheme.lower() != "bearer":
        raise api_error(401, "Invalid authorization scheme", "AUTH_SCHEME_INVALID")

    if not token:
        raise api_error(401, "Token is empty", "TOKEN_EMPTY")

    payload = _validate_access_token(token)
    mark_authenticated(payload["sub"])
    enforce_user_limit(payload["sub"])
    return payload


def require_role(required_role: str):
    """
    Dependency factory for role-based access control.
    Example:
        @router.get("/admin-only")
        def admin_only(user = Depends(require_role("admin"))):
            ...
    """
    def wrapper(user: dict = Depends(require_auth)):
        role = user.get("role")
        if role != required_role:
            raise api_error(403, "Insufficient permissions", "INSUFFICIENT_PERMISSIONS")
        return user

    return wrapper
