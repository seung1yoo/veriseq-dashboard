from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from veriseq_dashboard.models import (
    CatalogItem,
    CatalogVersion,
    DashboardUser,
    ReferenceSeedVersion,
    UserRole,
)
from veriseq_dashboard.seed import initialize_database


def test_seed_initializes_all_catalog_items_and_is_idempotent(session) -> None:
    seed_root = Path(__file__).resolve().parents[2] / "database" / "seed"

    first = initialize_database(session, seed_root, "Admin@Example.com", "Initial!Password123")
    second = initialize_database(session, seed_root, "admin@example.com", "unused")

    assert first["catalog_items"] == 258
    assert second == first
    assert session.scalar(select(func.count()).select_from(CatalogItem)) == 258
    assert (
        session.scalar(
            select(func.count())
            .select_from(CatalogVersion)
            .where(CatalogVersion.is_active.is_(True))
        )
        == 1
    )
    administrator = session.scalar(select(DashboardUser))
    assert administrator is not None
    assert administrator.email == "admin@example.com"
    assert administrator.role == UserRole.ADMIN
    assert administrator.must_change_password is True
    assert (
        session.scalar(
            select(func.count())
            .select_from(ReferenceSeedVersion)
            .where(ReferenceSeedVersion.is_active.is_(True))
        )
        == 1
    )
