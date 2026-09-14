from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from veriseq_dashboard.config import Settings, get_settings
from veriseq_dashboard.db import Base, get_session
from veriseq_dashboard.main import app
from veriseq_dashboard.models import DashboardUser, UserRole


@pytest.fixture
def auth_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings = replace(
        get_settings(),
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        development_auth_enabled=False,
        allowed_email_domain="",
    )

    def session_override():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    initial_password = "Initial!Password123"
    password_hash = PasswordHash.recommended().hash(initial_password)
    with testing_session() as session:
        session.add(
            DashboardUser(
                email="admin@example.com",
                display_name="Administrator",
                role=UserRole.ADMIN,
                is_active=True,
                password_hash=password_hash,
                password_history=[password_hash],
                must_change_password=True,
            )
        )
        session.commit()
    with TestClient(app) as client:
        client.headers["X-Test-Initial-Password"] = initial_password
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def login_and_change_admin_password(client: TestClient) -> str:
    initial_password = client.headers.pop("X-Test-Initial-Password")
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": initial_password},
    )
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True
    session = client.get("/api/v1/session").json()
    csrf = session["csrf_token"]
    blocked = client.get("/api/v1/dashboard")
    assert blocked.status_code == 409
    changed = client.post(
        "/auth/password",
        headers={"X-CSRF-Token": csrf},
        json={"current_password": initial_password, "new_password": "New!SecurePassword456"},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/dashboard").status_code == 200
    return csrf


def test_first_login_requires_password_change(auth_client) -> None:
    client, _ = auth_client
    login_and_change_admin_password(client)


def test_default_domain_is_unrestricted(monkeypatch) -> None:
    monkeypatch.delenv("VERISEQ_ALLOWED_EMAIL_DOMAIN", raising=False)
    assert Settings.from_env().allowed_email_domain == ""
    monkeypatch.setenv("VERISEQ_ALLOWED_EMAIL_DOMAIN", "  LAB.EXAMPLE  ")
    assert Settings.from_env().allowed_email_domain == "lab.example"


def test_optional_laboratory_domain_restriction(auth_client) -> None:
    client, _ = auth_client
    csrf = login_and_change_admin_password(client)
    settings = app.dependency_overrides[get_settings]()
    app.dependency_overrides[get_settings] = lambda: replace(
        settings, allowed_email_domain="lab.example"
    )
    for email in ["outside@example.com", "operator@notlab.example", "operator@sub.lab.example"]:
        rejected = client.post(
            "/api/v1/users",
            headers={"X-CSRF-Token": csrf},
            json={"email": email, "role": "OPERATOR"},
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "USER_EMAIL_DOMAIN_INVALID"
    accepted = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "  Operator@LAB.EXAMPLE  ", "role": "OPERATOR"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["email"] == "operator@lab.example"


def test_admin_issues_temporary_password_and_unlocks_user(auth_client) -> None:
    client, testing_session = auth_client
    csrf = login_and_change_admin_password(client)
    invalid_email = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "not-an-email", "role": "OPERATOR"},
    )
    assert invalid_email.status_code == 409
    assert invalid_email.json()["error"]["code"] == "USER_EMAIL_INVALID"
    created = client.post(
        "/api/v1/users",
        headers={"X-CSRF-Token": csrf},
        json={"email": "operator@another-lab.example", "role": "OPERATOR"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert len(payload["temporary_password"]) == 18
    user_id = payload["id"]

    other = TestClient(app)
    for _ in range(5):
        failed = other.post(
            "/auth/login",
            json={"email": "operator@another-lab.example", "password": "wrong"},
        )
        assert failed.status_code == 401
        assert failed.json()["error"]["message"] == "Check your email or password."
    with testing_session() as session:
        user = session.scalar(select(DashboardUser).where(DashboardUser.id == user_id))
        assert user is not None and user.locked_until is not None

    unlocked = client.post(
        f"/api/v1/users/{user_id}/unlock",
        headers={"X-CSRF-Token": csrf},
    )
    assert unlocked.status_code == 200
    login = other.post(
        "/auth/login",
        json={"email": "operator@another-lab.example", "password": payload["temporary_password"]},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    other.close()
