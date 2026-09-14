from __future__ import annotations

import json
import string
from datetime import timedelta
from pathlib import Path

from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import (
    CatalogItem,
    CatalogVersion,
    DashboardUser,
    ReferenceSeedVersion,
    UserRole,
    SampleResult,
    utcnow,
)


def catalog_chromosome(definition: dict) -> str | None:
    if definition.get("method") != "genomic_interval":
        return definition.get("chromosome")
    chromosomes = {region["chromosome"] for region in definition.get("regions", [])}
    return next(iter(chromosomes)) if len(chromosomes) == 1 else None


def initialize_database(
    session: Session,
    seed_root: Path,
    initial_admin_email: str = "",
    initial_admin_password: str = "",
) -> dict[str, int | str]:
    catalog_payload = _read_json(seed_root / "nipt_catalog.v1.json")
    reference_payload = _read_json(seed_root / "dashboard_reference.v1.json")
    _validate_catalog(catalog_payload)

    catalog_version_name = str(catalog_payload["catalog_version"])
    catalog_version = session.scalar(
        select(CatalogVersion).where(CatalogVersion.version == catalog_version_name)
    )
    if catalog_version is None and session.scalar(select(SampleResult.id).limit(1)):
        raise ValueError("Changing a catalog after ingestion requires a new installation or a reviewed re-evaluation migration")
    if catalog_version is not None:
        existing = session.scalars(select(CatalogItem).where(CatalogItem.catalog_version_id == catalog_version.id).order_by(CatalogItem.output_order)).all()
        if [item.payload for item in existing] != sorted(catalog_payload["items"], key=lambda item: item["output_order"]):
            raise ValueError("Catalog content changed without a new catalog_version")
    if catalog_version is None:
        session.execute(update(CatalogVersion).values(is_active=False))
        catalog_version = CatalogVersion(
            version=catalog_version_name,
            seed_version=str(catalog_payload["seed_version"]),
            is_active=True,
            source_payload={key: value for key, value in catalog_payload.items() if key != "items"},
        )
        session.add(catalog_version)
        session.flush()
        for item in catalog_payload["items"]:
            session.add(
                CatalogItem(
                    catalog_version_id=catalog_version.id,
                    item_id=item["item_id"],
                    item_name=item["display"]["item_name"],
                    category=item["classification"]["category"],
                    consequence=item["classification"].get("consequence"),
                    chromosome=catalog_chromosome(item["match_definition"]),
                    active=bool(item["active"]),
                    output_order=int(item["output_order"]),
                    marker_id=item["glcp"]["marker_id"],
                    rs_id=item["glcp"]["rs_id"],
                    payload=item,
                )
            )
    else:
        session.execute(update(CatalogVersion).values(is_active=False))
        catalog_version.is_active = True

    reference_seed_version = str(reference_payload["seed_version"])
    reference_version = session.scalar(
        select(ReferenceSeedVersion).where(
            ReferenceSeedVersion.seed_version == reference_seed_version
        )
    )
    if reference_version is None:
        session.execute(update(ReferenceSeedVersion).values(is_active=False))
        reference_version = ReferenceSeedVersion(
            seed_version=reference_seed_version,
            is_active=True,
            payload=reference_payload,
        )
        session.add(reference_version)
    else:
        session.execute(update(ReferenceSeedVersion).values(is_active=False))
        reference_version.is_active = True
    normalized_admin_email = initial_admin_email.strip().lower()
    if normalized_admin_email:
        administrator = session.scalar(
            select(DashboardUser).where(DashboardUser.email == normalized_admin_email)
        )
        if administrator is None:
            if not initial_admin_password:
                raise ValueError(
                    "VERISEQ_INITIAL_ADMIN_PASSWORD is required for the first administrator"
                )
            _validate_initial_password(initial_admin_password)
            password_hash = PasswordHash.recommended().hash(initial_admin_password)
            session.add(
                DashboardUser(
                    email=normalized_admin_email,
                    display_name="Dashboard administrator",
                    role=UserRole.ADMIN,
                    is_active=True,
                    password_hash=password_hash,
                    password_history=[password_hash],
                    must_change_password=True,
                    temporary_password_expires_at=utcnow() + timedelta(hours=24),
                )
            )
        elif not administrator.password_hash:
            if not initial_admin_password:
                raise ValueError(
                    "VERISEQ_INITIAL_ADMIN_PASSWORD is required to initialize the administrator password"
                )
            _validate_initial_password(initial_admin_password)
            password_hash = PasswordHash.recommended().hash(initial_admin_password)
            administrator.password_hash = password_hash
            administrator.password_history = [password_hash]
            administrator.must_change_password = True
            administrator.temporary_password_expires_at = utcnow() + timedelta(hours=24)
    session.commit()
    return {
        "catalog_version": catalog_version_name,
        "catalog_items": len(catalog_payload["items"]),
        "reference_seed_version": reference_seed_version,
    }


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Required database seed not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_catalog(payload: dict) -> None:
    items = payload.get("items", [])
    if not items or payload.get("item_count") != len(items):
        raise ValueError("Catalog item_count must match a nonempty items array")
    for item in items:
        if not item.get("item_id") or not item["display"].get("item_name"):
            raise ValueError("Catalog items require an ID and display name")
        definition = item["match_definition"]
        if definition.get("method") == "genomic_interval":
            if definition.get("assembly") != "GRCh37" or definition.get("coordinate_system") != "0-based-half-open":
                raise ValueError("Catalog intervals must use GRCh37, 0-based half-open coordinates")
            if not definition.get("regions"):
                raise ValueError("Catalog interval regions cannot be empty")
            for region in definition["regions"]:
                if (region.get("chromosome") not in {f"chr{i}" for i in range(1, 23)} | {"chrX", "chrY"}
                        or type(region.get("start")) is not int or type(region.get("end")) is not int
                        or not 0 <= region["start"] < region["end"]):
                    raise ValueError("Invalid catalog genomic interval")
        elif definition.get("method") != "categorical" or not definition.get("veriseq_tokens"):
            raise ValueError("Catalog matching must define categorical tokens or genomic intervals")
        if type(item.get("active")) is not bool or type(item.get("output_order")) is not int or item["output_order"] < 1:
            raise ValueError("Catalog items require a boolean active flag and positive integer output_order")
        if item["glcp"].get("normal_allele") != "N" or item["glcp"].get("risk_allele") != "O":
            raise ValueError("GLCP currently supports N/O result codes")
    for field in ("item_id", "output_order"):
        values = [item[field] for item in items]
        if len(values) != len(set(values)):
            raise ValueError(f"Catalog seed contains duplicate {field}")
    for field in ("marker_id", "rs_id"):
        values = [item["glcp"][field] for item in items]
        if len(values) != len(set(values)):
            raise ValueError(f"Catalog seed contains duplicate {field}")


def _validate_initial_password(password: str) -> None:
    if (
        len(password) < 12
        or not any(character.isalpha() for character in password)
        or not any(character.isdigit() for character in password)
        or not any(character in string.punctuation for character in password)
    ):
        raise ValueError(
            "VERISEQ_INITIAL_ADMIN_PASSWORD must be at least 12 characters and include letters, numbers, and symbols"
        )


def main() -> None:
    settings = get_settings()
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        result = initialize_database(
            session,
            settings.seed_root,
            initial_admin_email=settings.initial_admin_email,
            initial_admin_password=settings.initial_admin_password,
        )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
