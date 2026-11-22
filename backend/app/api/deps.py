"""Shared FastAPI dependencies: DB session, settings, authentication and RBAC."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.db.session import get_db
from app.domains.customers.enums import STAFF_ROLES, UserRole
from app.models import User
from app.schemas.common import PageParams
from app.services.support import Actor

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def client_ip(request: Request) -> str | None:
    # Behind the ingress, the first X-Forwarded-For hop is the client.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def get_current_user(db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_token(token, "access")
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token subject") from exc
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("You do not have permission to perform this action")
        return user

    return checker


# Readonly users may view staff resources but not change them.
StaffReader = Annotated[User, Depends(require_roles(*STAFF_ROLES, UserRole.READONLY))]
Staff = Annotated[User, Depends(require_roles(*STAFF_ROLES))]
Admin = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
CustomerUser = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]


def actor_for(request: Request, user: User | None = None) -> Actor:
    return Actor(user=user, ip=client_ip(request), user_agent=request.headers.get("user-agent"))


def page_params(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200)) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Pagination = Annotated[PageParams, Depends(page_params)]
