from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    source_root: Path
    seed_root: Path
    display_timezone: str
    cors_origins: str
    worker_poll_seconds: float
    worker_lease_seconds: int
    initial_admin_email: str
    initial_admin_password: str
    allowed_email_domain: str
    development_auth_enabled: bool
    public_base_url: str
    session_idle_minutes: int
    session_max_hours: int
    temporary_password_hours: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_env=os.environ.get("VERISEQ_APP_ENV", "development"),
            database_url=os.environ.get(
                "VERISEQ_DATABASE_URL", "sqlite:///./var/veriseq-dashboard.db"
            ),
            source_root=Path(os.environ.get("VERISEQ_SOURCE_ROOT", "/veriseq_output")),
            seed_root=Path(os.environ.get("VERISEQ_SEED_ROOT", "database/seed")),
            display_timezone=os.environ.get("VERISEQ_DISPLAY_TIMEZONE", "Asia/Seoul"),
            cors_origins=os.environ.get(
                "VERISEQ_CORS_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            ),
            worker_poll_seconds=max(0.2, float(os.environ.get("VERISEQ_WORKER_POLL_SECONDS", "2"))),
            worker_lease_seconds=max(
                30, int(os.environ.get("VERISEQ_WORKER_LEASE_SECONDS", "300"))
            ),
            initial_admin_email=os.environ.get("VERISEQ_INITIAL_ADMIN_EMAIL", "").strip().lower(),
            initial_admin_password=os.environ.get("VERISEQ_INITIAL_ADMIN_PASSWORD", ""),
            allowed_email_domain=os.environ.get("VERISEQ_ALLOWED_EMAIL_DOMAIN", "")
            .strip()
            .lower(),
            development_auth_enabled=(
                os.environ.get("VERISEQ_DEVELOPMENT_AUTH_ENABLED", "false").lower()
                in {"1", "true", "yes"}
            ),
            public_base_url=os.environ.get(
                "VERISEQ_PUBLIC_BASE_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            session_idle_minutes=max(5, int(os.environ.get("VERISEQ_SESSION_IDLE_MINUTES", "30"))),
            session_max_hours=max(1, int(os.environ.get("VERISEQ_SESSION_MAX_HOURS", "12"))),
            temporary_password_hours=max(
                1, int(os.environ.get("VERISEQ_TEMPORARY_PASSWORD_HOURS", "24"))
            ),
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
