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
from app.domains.billing.entitlements import Feature
from app.domains.customers.enums import STAFF_ROLES, UserRole
from app.domains.integrations.webhooks import API_KEY_PREFIX
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


def get_current_user(request: Request, db: DbSession,
                     token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    if not token:
        raise AuthenticationError("Not authenticated")
    if token.startswith(API_KEY_PREFIX):
        return _api_key_user(request, db, token)
    payload = decode_token(token, "access")
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token subject") from exc
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive")
    return user


def _api_key_user(request: Request, db: Session, token: str) -> User:
    """Integrations: a customer API key acts as its owner, limited to that business's
    customer endpoints (staff routes reject the customer role) and optionally read-only."""
    from app.services.entitlements import require_feature
    from app.services.integration_service import IntegrationService

    key = IntegrationService(db, get_settings()).authenticate(token)
    if key is None:
        raise AuthenticationError("Invalid or revoked API key")
    require_feature(db, key.business_id, Feature.INTEGRATIONS)  # downgrades disable keys
    if key.read_only and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise PermissionDeniedError("This API key is read-only")
    user = db.get(User, key.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("API key owner is inactive")
    request.state.api_key_id = key.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def human_only(request: Request, _user: CurrentUser) -> None:
    """Sensitive operations (billing, credentials, API key/webhook management) need a login session.
    Depends on CurrentUser so authentication (which marks API-key requests) always runs first."""
    if getattr(request.state, "api_key_id", None):
        raise PermissionDeniedError("This action requires signing in; API keys cannot perform it")


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
