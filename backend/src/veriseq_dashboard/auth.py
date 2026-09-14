from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_session
from .errors import DashboardError
from .models import AuthSession, DashboardUser, UserRole, as_utc, utcnow

SESSION_COOKIE = "veriseq_session"


def normalize_email(value: str) -> str:
    return value.strip().lower()


def require_session_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_dev_user_email: Annotated[str | None, Header()] = None,
) -> DashboardUser:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == _token_hash(raw_token),
                AuthSession.revoked_at.is_(None),
            )
        )
        now = utcnow()
        cutoff = now - timedelta(minutes=settings.session_idle_minutes)
        if (
            auth_session is not None
            and as_utc(auth_session.last_seen_at) >= cutoff
            and as_utc(auth_session.expires_at) > now
        ):
            user = session.get(DashboardUser, auth_session.user_id)
            if user is not None and user.is_active:
                auth_session.last_seen_at = utcnow()
                session.commit()
                return user
    if settings.app_env != "development" or not settings.development_auth_enabled:
        raise DashboardError(
            "AUTHENTICATION_REQUIRED",
            "Sign in to continue.",
        )
    if not x_dev_user_email:
        raise DashboardError(
            "AUTHENTICATION_REQUIRED",
            "Development user information is missing.",
        )
    user = session.scalar(
        select(DashboardUser).where(DashboardUser.email == normalize_email(x_dev_user_email))
    )
    if user is None or not user.is_active:
        raise DashboardError(
            "ACCESS_DENIED",
            "The user is inactive or does not have access.",
        )
    return user


def require_user(
    user: Annotated[DashboardUser, Depends(require_session_user)],
) -> DashboardUser:
    if user.must_change_password:
        raise DashboardError(
            "PASSWORD_CHANGE_REQUIRED",
            "Change your password to continue.",
        )
    return user


def create_auth_session(
    session: Session, user: DashboardUser, settings: Settings
) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_hex(32)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            csrf_token=csrf_token,
            auth_method="PASSWORD",
            expires_at=utcnow() + timedelta(hours=settings.session_max_hours),
        )
    )
    session.commit()
    return token, csrf_token


def csrf_token_for_request(session: Session, request: Request) -> str | None:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        return None
    auth_session = session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _token_hash(raw_token),
            AuthSession.revoked_at.is_(None),
        )
    )
    return auth_session.csrf_token if auth_session else None


def require_csrf(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[DashboardUser, Depends(require_user)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> DashboardUser:
    if (
        settings.app_env == "development"
        and settings.development_auth_enabled
        and not request.cookies.get(SESSION_COOKIE)
    ):
        return user
    expected = csrf_token_for_request(session, request)
    if not expected or not x_csrf_token or not secrets.compare_digest(expected, x_csrf_token):
        raise DashboardError(
            "CSRF_VALIDATION_FAILED", "Request security validation failed. Refresh the page."
        )
    return user


def revoke_auth_session(session: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(raw_token))
    )
    if auth_session is not None:
        auth_session.revoked_at = utcnow()
        session.commit()


def revoke_user_sessions(session: Session, user_id: str) -> int:
    sessions = session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    ).all()
    now = utcnow()
    for auth_session in sessions:
        auth_session.revoked_at = now
    return len(sessions)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_admin(user: Annotated[DashboardUser, Depends(require_user)]) -> DashboardUser:
    if user.role != UserRole.ADMIN:
        raise DashboardError("ADMIN_REQUIRED", "Administrator access is required.")
    return user


def require_admin_csrf(user: Annotated[DashboardUser, Depends(require_csrf)]) -> DashboardUser:
    if user.role != UserRole.ADMIN:
        raise DashboardError("ADMIN_REQUIRED", "Administrator access is required.")
    return user


CurrentUser = Annotated[DashboardUser, Depends(require_user)]
SessionUser = Annotated[DashboardUser, Depends(require_session_user)]
AdminUser = Annotated[DashboardUser, Depends(require_admin)]
CsrfUser = Annotated[DashboardUser, Depends(require_csrf)]
AdminCsrfUser = Annotated[DashboardUser, Depends(require_admin_csrf)]
