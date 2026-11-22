from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError, ValidationFailedError
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.domains.audit.actions import AuditAction
from app.domains.customers.enums import UserRole
from app.models import User
from app.repositories.repositories import UserRepository
from app.schemas.auth import TokenPair, UserCreate, UserUpdate
from app.services.support import Actor, audit


def issue_tokens(user: User) -> TokenPair:
    settings = get_settings()
    claims = {"role": user.role.value}
    return TokenPair(
        access_token=create_token(str(user.id), "access", claims),
        refresh_token=create_token(str(user.id), "refresh"),
        expires_in=settings.access_token_expire_minutes * 60,
    )


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def authenticate(self, email: str, password: str, actor: Actor) -> TokenPair:
        user = self.users.by_email(email)
        if (
            user is None
            or not user.password_hash
            or not verify_password(password, user.password_hash)
            or not user.is_active
        ):
            audit(self.db, actor, AuditAction.LOGIN_FAILED, "user", user.id if user else None,
                  {"email": email.lower()})
            self.db.commit()
            raise AuthenticationError("Invalid email or password")
        user.last_login_at = datetime.now(UTC)
        audit(self.db, Actor(user=user, ip=actor.ip), AuditAction.LOGIN_SUCCEEDED, "user", user.id)
        self.db.commit()
        return issue_tokens(user)

    def refresh(self, refresh_token: str) -> TokenPair:
        payload = decode_token(refresh_token, "refresh")
        user = self.users.get(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("User not found or inactive")
        return issue_tokens(user)

    def change_password(self, user: User, current: str, new: str, actor: Actor) -> None:
        if not user.password_hash or not verify_password(current, user.password_hash):
            raise ValidationFailedError("Current password is incorrect")
        user.password_hash = hash_password(new)
        audit(self.db, actor, AuditAction.PASSWORD_CHANGED, "user", user.id)
        self.db.commit()

    def create_user(self, data: UserCreate, actor: Actor) -> User:
        if self.users.by_email(data.email):
            raise ConflictError("A user with this email already exists")
        user = self.users.add(
            User(
                email=data.email.lower(),
                password_hash=hash_password(data.password),
                full_name=data.full_name,
                role=data.role,
                is_email_verified=True,
            )
        )
        audit(self.db, actor, AuditAction.USER_CREATED, "user", user.id, {"role": data.role.value})
        self.db.commit()
        return user

    def update_user(self, user: User, data: UserUpdate, actor: Actor) -> User:
        changes = data.model_dump(exclude_unset=True)
        if actor.user and actor.user.id == user.id and (
            changes.get("is_active") is False or changes.get("role", user.role) != user.role
        ):
            raise ValidationFailedError("You cannot deactivate or change the role of your own account")
        for field, value in changes.items():
            setattr(user, field, value)
        audit(self.db, actor, AuditAction.USER_UPDATED, "user", user.id,
              {k: str(v) for k, v in changes.items()})
        self.db.commit()
        return user

    def ensure_admin(self, email: str, password: str) -> User:
        """Idempotent bootstrap of the first administrator."""
        user = self.users.by_email(email)
        if user is None:
            user = self.users.add(
                User(email=email.lower(), password_hash=hash_password(password), full_name="Administrator",
                     role=UserRole.ADMIN, is_email_verified=True)
            )
            self.db.commit()
        return user
