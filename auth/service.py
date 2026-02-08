import os
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, ExpiredSignatureError, jwt
from fastapi import HTTPException, Header

# JWT Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "metpro-erp-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password hashing setup
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    """Verify a plain password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Hash a password"""
    return pwd_context.hash(password)

def create_access_token(data: dict):
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(
    authorization: str = Header(None),
    token: str = None
):
    """Verify JWT token from Authorization header or query string"""
    # Get token from Authorization: Bearer <token> header or from query param
    if authorization:
        try:
            scheme, token = authorization.split()
            if scheme.lower() != 'bearer':
                raise HTTPException(
                    status_code=401,
                    detail='Invalid authorization scheme'
                )
        except ValueError:
            raise HTTPException(
                status_code=401,
                detail='Invalid authorization header format'
            )
    elif token:
        # token provided via query string (e.g. iframe)
        pass
    else:
        raise HTTPException(
            status_code=401,
            detail='Missing authorization token'
        )

    if not token:
        raise HTTPException(
            status_code=401,
            detail='Token is empty'
        )

    # Decode and validate JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail='Token expired'
        )
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail='Invalid token'
        )
