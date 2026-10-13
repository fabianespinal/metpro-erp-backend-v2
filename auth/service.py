import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, ExpiredSignatureError, jwt
from passlib.context import CryptContext

# =========================
# JWT / SECURITY CONFIG
# =========================

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# OAuth2 bearer token (standard FastAPI pattern)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

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
# TOKEN VERIFICATION (HEADER OR QUERY)
# =========================

def verify_token(
    authorization: str = Header(None),
):
    """
    Verify JWT token from the Authorization header (Bearer <token>).
    Query-string tokens are not accepted.
    Returns the decoded payload if valid.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization token"
        )

    try:
        scheme, token = authorization.split()
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header format"
        )

    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization scheme"
        )

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token is empty"
        )

    # Decode and validate JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired"
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )


# =========================
# STANDARD BEARER TOKEN FLOW
# =========================

def get_current_user_from_bearer(
    token: str = Depends(oauth2_scheme)
) -> dict:
    """
    Get current user payload from standard Bearer token (Authorization header).
    Use this in typical protected routes.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired"
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )


def require_role(required_role: str):
    """
    Dependency factory for role-based access control.
    Example:
        @router.get("/admin-only")
        def admin_only(user = Depends(require_role("admin"))):
            ...
    """
    def wrapper(user: dict = Depends(get_current_user_from_bearer)):
        role = user.get("role")
        if role != required_role:
            raise HTTPException(
                status_code=403,
                detail="Insufficient permissions"
            )
        return user

    return wrapper
