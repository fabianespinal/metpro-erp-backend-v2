from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from .service import verify_password, create_access_token, get_password_hash
from config.database import get_db_connection

router = APIRouter(prefix='/auth', tags=['authentication'])

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

@router.post('/login', response_model=LoginResponse)
def login(credentials: LoginRequest):
    """Authenticate user and return JWT token"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get user by username
        cursor.execute('SELECT * FROM users WHERE username = ?', (credentials.username,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=401,
                detail='Invalid username or password'
            )
        
        user = dict(user)
        
        # Check if user is active
        if not user.get('is_active', 1):
            raise HTTPException(
                status_code=401,
                detail='Account is disabled'
            )
        
        # Verify password
        if not verify_password(credentials.password, user['password_hash']):
            raise HTTPException(
                status_code=401,
                detail='Invalid username or password'
            )
        
        # Create access token
        token_data = {
            'sub': user['username'],
            'user_id': user['id'],
            'role': user.get('role', 'user')
        }
        access_token = create_access_token(token_data)
        
        return LoginResponse(
            access_token=access_token,
            username=user['username']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Login failed: {str(e)}')
    finally:
        if conn:
            conn.close()

@router.post('/register')
def register(user_data: RegisterRequest):
    """Register a new user"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if username already exists
        cursor.execute('SELECT id FROM users WHERE username = ?', (user_data.username,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail='Username already exists'
            )
        
        # Check if email already exists
        cursor.execute('SELECT id FROM users WHERE email = ?', (user_data.email,))
        if cursor.fetchone():
            raise HTTPException(
                status_code=400,
                detail='Email already exists'
            )
        
        # Hash password
        password_hash = get_password_hash(user_data.password)
        
        # Insert user
        cursor.execute('''
            INSERT INTO users (username, password_hash, email, full_name, role, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            user_data.username,
            password_hash,
            user_data.email,
            user_data.full_name,
            'user',  # Default role
            1  # Active by default
        ))
        
        user_id = cursor.lastrowid
        conn.commit()
        
        return {
            'message': 'User registered successfully',
            'user_id': user_id,
            'username': user_data.username
        }
        
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=f'Registration failed: {str(e)}')
    finally:
        if conn:
            conn.close()

@router.get('/me')
def get_current_user(current_user: dict = None):
    """Get current authenticated user info"""
    # This would use the verify_token dependency in practice
    # For now, return placeholder
    return {
        'username': current_user.get('sub') if current_user else 'unknown',
        'role': current_user.get('role') if current_user else 'user'
    }
