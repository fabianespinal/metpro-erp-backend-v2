from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class UserBase(BaseModel):
    username: str
    email: str
    full_name: str
    role: str = 'user'

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class User(UserBase):
    id: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class UserPasswordReset(BaseModel):
    new_password: str
