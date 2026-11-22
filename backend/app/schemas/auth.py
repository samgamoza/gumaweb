from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domains.customers.enums import UserRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class UserRead(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    phone: str | None
    role: UserRole
    is_active: bool
    is_email_verified: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str | None = Field(None, max_length=200)
    role: UserRole = UserRole.OPERATOR


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None
