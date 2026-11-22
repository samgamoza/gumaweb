from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession, actor_for, client_ip
from app.core.rate_limit import get_rate_limiter
from app.models import User
from app.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenPair, UserRead
from app.schemas.common import Message
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])

LOGIN_LIMIT = 20  # attempts per IP per 15 minutes


def _login(db, request: Request, email: str, password: str) -> TokenPair:
    get_rate_limiter().check("login", client_ip(request) or "unknown", LOGIN_LIMIT, window_seconds=900)
    return AuthService(db).authenticate(email, password, actor_for(request))


@router.post("/login", response_model=TokenPair, summary="Log in with email and password")
def login(body: LoginRequest, request: Request, db: DbSession) -> TokenPair:
    return _login(db, request, body.email, body.password)


@router.post("/token", response_model=TokenPair, summary="OAuth2 password flow (Swagger UI)")
def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession) -> TokenPair:
    return _login(db, request, form.username, form.password)


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, db: DbSession) -> TokenPair:
    return AuthService(db).refresh(body.refresh_token)


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user


@router.post("/change-password", response_model=Message)
def change_password(body: ChangePasswordRequest, request: Request, user: CurrentUser, db: DbSession) -> Message:
    AuthService(db).change_password(user, body.current_password, body.new_password, actor_for(request, user))
    return Message(message="Password updated")
