from __future__ import annotations

import secrets
import string
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    SESSION_COOKIE,
    CsrfUser,
    SessionUser,
    create_auth_session,
    csrf_token_for_request,
    normalize_email,
    revoke_auth_session,
    revoke_user_sessions,
)
from .config import Settings, get_settings
from .db import get_session
from .errors import DashboardError
from .models import AuditEvent, DashboardUser, as_utc, utcnow

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
PASSWORD_HASH = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = PASSWORD_HASH.hash("TimingOnly!Password123")
GENERIC_LOGIN_ERROR = "Check your email or password."


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=512)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)


def validate_password(password: str, email: str = "") -> list[str]:
    errors: list[str] = []
    if len(password) < 12:
        errors.append("At least 12 characters")
    if not any(character.isalpha() for character in password):
        errors.append("Include letters")
    if not any(character.isdigit() for character in password):
        errors.append("Include numbers")
    if not any(character in string.punctuation for character in password):
        errors.append("Include symbols")
    local_part = email.partition("@")[0].lower()
    if local_part and local_part in password.lower():
        errors.append("Must not contain your email username")
    return errors


def generate_temporary_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(18))
        if not validate_password(value):
            return value


def password_was_used(user: DashboardUser, password: str) -> bool:
    for password_hash in (user.password_history or [])[-5:]:
        try:
            if PASSWORD_HASH.verify(password, password_hash):
                return True
        except PwdlibError:
            continue
    return False


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="strict",
        max_age=settings.session_max_hours * 3600,
        path="/",
    )


@router.post("/auth/login")
def login(
    payload: LoginRequest, session: SessionDependency, settings: SettingsDependency
) -> Response:
    email = normalize_email(payload.email)
    user = session.scalar(select(DashboardUser).where(DashboardUser.email == email))
    now = utcnow()
    if user is not None and user.locked_until and as_utc(user.locked_until) > now:
        session.add(
            AuditEvent(
                actor=email,
                action="PASSWORD_LOGIN_REJECTED_LOCKED",
                subject_type="USER",
                subject_id=user.id,
                details={},
            )
        )
        session.commit()
        raise DashboardError("LOGIN_FAILED", GENERIC_LOGIN_ERROR)
    valid = False
    if user is None or not user.is_active or not user.password_hash:
        PASSWORD_HASH.verify(payload.password, DUMMY_PASSWORD_HASH)
    else:
        try:
            valid = PASSWORD_HASH.verify(payload.password, user.password_hash)
        except PwdlibError:
            valid = False
        if (
            valid
            and user.must_change_password
            and user.temporary_password_expires_at is not None
            and as_utc(user.temporary_password_expires_at) <= now
        ):
            valid = False
    if not valid:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.failed_login_attempts = 0
                user.locked_until = now + timedelta(minutes=30)
                revoke_user_sessions(session, user.id)
            session.add(
                AuditEvent(
                    actor=email,
                    action="PASSWORD_LOGIN_FAILED",
                    subject_type="USER",
                    subject_id=user.id,
                    details={},
                )
            )
            session.commit()
        else:
            session.add(
                AuditEvent(
                    actor=email,
                    action="PASSWORD_LOGIN_FAILED",
                    subject_type="AUTH",
                    subject_id=email,
                    details={},
                )
            )
            session.commit()
        raise DashboardError("LOGIN_FAILED", GENERIC_LOGIN_ERROR)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.first_login_at = user.first_login_at or now
    user.last_login_at = now
    session.add(
        AuditEvent(
            actor=email,
            action="PASSWORD_LOGIN_SUCCEEDED",
            subject_type="USER",
            subject_id=user.id,
            details={},
        )
    )
    token, csrf_token = create_auth_session(session, user, settings)
    response = JSONResponse(
        {
            "authenticated": True,
            "must_change_password": user.must_change_password,
            "csrf_token": csrf_token,
        }
    )
    _set_session_cookie(response, token, settings)
    return response


@router.post("/auth/password")
def change_password(
    payload: PasswordChangeRequest, request: Request, session: SessionDependency, user: SessionUser
) -> dict:
    expected_csrf = csrf_token_for_request(session, request)
    supplied_csrf = request.headers.get("X-CSRF-Token")
    if (
        not expected_csrf
        or not supplied_csrf
        or not secrets.compare_digest(expected_csrf, supplied_csrf)
    ):
        raise DashboardError(
            "CSRF_VALIDATION_FAILED", "Request security validation failed. Refresh the page."
        )
    try:
        current_valid = PASSWORD_HASH.verify(payload.current_password, user.password_hash)
    except PwdlibError:
        current_valid = False
    if not current_valid:
        raise DashboardError("CURRENT_PASSWORD_INVALID", "The current password is incorrect.")
    policy_errors = validate_password(payload.new_password, user.email)
    if policy_errors:
        raise DashboardError(
            "PASSWORD_POLICY_FAILED",
            "The new password does not meet the password policy.",
            details={"requirements": policy_errors},
        )
    if password_was_used(user, payload.new_password):
        raise DashboardError(
            "PASSWORD_REUSED", "The last five passwords cannot be reused."
        )
    new_hash = PASSWORD_HASH.hash(payload.new_password)
    user.password_hash = new_hash
    user.password_history = [*(user.password_history or [])[-4:], new_hash]
    user.must_change_password = False
    user.temporary_password_expires_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(
        AuditEvent(
            actor=user.email,
            action="PASSWORD_CHANGED",
            subject_type="USER",
            subject_id=user.id,
            details={},
        )
    )
    session.commit()
    return {"changed": True}


@router.post("/api/v1/logout")
def logout(request: Request, session: SessionDependency) -> Response:
    revoke_auth_session(session, request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/api/v1/sessions/revoke-all")
def revoke_my_sessions(session: SessionDependency, user: CsrfUser) -> dict:
    count = revoke_user_sessions(session, user.id)
    session.add(
        AuditEvent(
            actor=user.email,
            action="USER_SESSIONS_REVOKED",
            subject_type="USER",
            subject_id=user.id,
            details={"count": count},
        )
    )
    session.commit()
    return {"revoked": count}
