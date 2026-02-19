from fastapi import APIRouter, Depends
from typing import List
from .models import User, UserCreate, UserUpdate, UserPasswordUpdate
from . import service
from backend.auth.service import verify_token

router = APIRouter(prefix='/users', tags=['users'])

@router.get('/', response_model=List[User])
def get_users(current_user: dict = Depends(verify_token)):
    """Get all users (admin only in production)"""
    users = service.get_all_users()
    return [User(**u) for u in users]

@router.get('/{user_id}', response_model=User)
def get_user(user_id: int, current_user: dict = Depends(verify_token)):
    """Get user by ID"""
    result = service.get_user_by_id(user_id)
    return User(**result)

@router.get('/username/{username}', response_model=User)
def get_user_by_username(username: str, current_user: dict = Depends(verify_token)):
    """Get user by username"""
    result = service.get_user_by_username(username)
    return User(**result)

@router.post('/', response_model=User)
def create_user(user: UserCreate, current_user: dict = Depends(verify_token)):
    """Create new user (admin only)"""
    result = service.create_user(
        user.username,
        user.password,
        user.email,
        user.full_name,
        user.role
    )
    return User(**result)

@router.put('/{user_id}', response_model=User)
def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update user"""
    result = service.update_user(
        user_id,
        user_update.email,
        user_update.full_name,
        user_update.role,
        user_update.is_active
    )
    return User(**result)

@router.patch('/{user_id}/password')
def update_password(
    user_id: int,
    password_update: UserPasswordUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update user password"""
    return service.update_user_password(
        user_id,
        password_update.current_password,
        password_update.new_password
    )

@router.delete('/{user_id}')
def delete_user(user_id: int, current_user: dict = Depends(verify_token)):
    """Delete user (admin only)"""
    return service.delete_user(user_id)
