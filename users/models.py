from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["user", "admin", "superadmin"]

# Server-side password rule. The frontend enforces the same minimum.
MIN_PASSWORD_LENGTH = 8


class User(BaseModel):
    """User as returned by the API. full_name and email may be NULL in the DB."""
    id: str
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "user"
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    email: str = Field(min_length=3)
    full_name: Optional[str] = None
    role: Role = "user"


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class UserPasswordReset(BaseModel):
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)
