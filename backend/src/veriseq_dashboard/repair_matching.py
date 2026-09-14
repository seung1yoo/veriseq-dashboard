"""Repair missing CNV candidates without changing existing approvals or candidates."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .matching import _match_interval
from .models import (
    AuditEvent,
    CatalogItem,
    CatalogVersion,
    Finding,
    IngestionRevision,
    MatchCandidate,
)
from .seed import catalog_chromosome


def repair_matching(session: Session) -> dict[str, int]:
    summary = {"catalog_updated": 0, "candidates_added": 0, "approved_findings_skipped": 0}
    items = session.scalars(select(CatalogItem)).all()
    for item in items:
        chromosome = catalog_chromosome(item.payload["match_definition"])
        if item.chromosome is None and chromosome is not None:
            item.chromosome = chromosome
            summary["catalog_updated"] += 1
    active = session.scalar(select(CatalogVersion).where(CatalogVersion.is_active.is_(True)))
    eligible = [item for item in items if active and item.catalog_version_id == active.id and item.active]
    findings = session.scalars(select(Finding).where(Finding.finding_type == "PARTIAL_CNV")).all()
    for finding in findings:
        revision = session.get(IngestionRevision, finding.sample.ingestion_revision_id)
        if not revision or not revision.is_active:
            continue
        if finding.sample.approvals:
            summary["approved_findings_skipped"] += 1
            continue
        existing = set(session.scalars(select(MatchCandidate.catalog_item_id).where(
            MatchCandidate.finding_id == finding.id
        )))
        pending = [item for item in eligible if item.id not in existing]
        before = len(session.new)
        _match_interval(session, finding, pending)
        summary["candidates_added"] += len(session.new) - before
    if summary["catalog_updated"] or summary["candidates_added"]:
        session.add(AuditEvent(actor="system:repair_matching", action="CNV_MATCHING_REPAIR",
                               subject_type="catalog", subject_id=active.id if active else "none",
                               details=summary.copy()))
    session.flush()
    return summary


def main() -> None:
    with SessionLocal.begin() as session:
        summary = repair_matching(session)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
