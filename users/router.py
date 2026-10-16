from core.errors import api_error
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Path

from auth.service import require_role, require_auth
from .models import User, UserCreate, UserUpdate, UserPasswordUpdate
from . import service

router = APIRouter(prefix='/users', tags=['users'])

USER_ID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
UserId = Annotated[str, Path(pattern=USER_ID_PATTERN)]


def _assert_self_or_admin(user_id: str, current_user: dict) -> None:
    """
    Allow admins for any user. Allow non-admins only for their own record.
    The JWT carries username ('sub') and role, not user id, so ownership is
    checked by comparing the target user's username.
    Unknown user ids return 403 for non-admins to avoid revealing which ids exist.
    """
    if current_user.get("role") in ("admin", "superadmin"):
        return
    try:
        target = service.get_user_by_id(user_id)
    except HTTPException:
        raise api_error(403, "Insufficient permissions", "INSUFFICIENT_PERMISSIONS")
    if target.get("username") != current_user.get("sub"):
        raise api_error(403, "Insufficient permissions", "INSUFFICIENT_PERMISSIONS")


# ============================================================
# ADMIN ONLY
# ============================================================

@router.get('/', response_model=List[User])
def get_users(_admin: dict = Depends(require_role("admin"))):
    """List all users. Admin only."""
    users = service.get_all_users()
    return [User(**u) for u in users]


@router.get('/username/{username}', response_model=User)
def get_user_by_username(username: str, _admin: dict = Depends(require_role("admin"))):
    """Get user by username. Admin only."""
    result = service.get_user_by_username(username)
    return User(**result)


@router.post('/', response_model=User)
def create_user(user: UserCreate, _admin: dict = Depends(require_role("admin"))):
    """Create new user. Admin only."""
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
    user_id: UserId,
    user_update: UserUpdate,
    _admin: dict = Depends(require_role("admin")),
):
    """Update user (email, name, role, active flag). Admin only."""
    result = service.update_user(
        user_id,
        user_update.email,
        user_update.full_name,
        user_update.role,
        user_update.is_active
    )
    return User(**result)


@router.delete('/{user_id}')
def delete_user(user_id: UserId, _admin: dict = Depends(require_role("admin"))):
    """Delete user. Admin only."""
    return service.delete_user(user_id)


# ============================================================
# SELF OR ADMIN
# ============================================================

@router.get('/{user_id}', response_model=User)
def get_user(user_id: UserId, current_user: dict = Depends(require_auth)):
    """Get user by ID. Admin, or the user themselves."""
    _assert_self_or_admin(user_id, current_user)
    result = service.get_user_by_id(user_id)
    return User(**result)


@router.patch('/{user_id}/password')
def update_password(
    user_id: UserId,
    password_update: UserPasswordUpdate,
    current_user: dict = Depends(require_auth),
):
    """Change password. Admin, or the user themselves (current password still required)."""
    _assert_self_or_admin(user_id, current_user)
    return service.update_user_password(
        user_id,
        password_update.current_password,
        password_update.new_password
    )
