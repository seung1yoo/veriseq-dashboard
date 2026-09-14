"""Conservative, auditable automatic approval of explicit VeriSeq negative results."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import ApprovalDecision, AuditEvent, IngestionRevision, SampleApproval, SampleResult

AUTO_ACTOR = "system:auto-negative:v1"
NORMAL = "NO ANOMALY DETECTED"


def eligible(sample: SampleResult) -> bool:
    normalize = lambda value: (value or "").strip().upper()
    if (sample.operational_classification != "ACTUAL" or sample.approval_blocked
            or normalize(sample.qc_flag) != "PASS"
            or normalize(sample.qc_reason) not in {"", "NONE"}
            or normalize(sample.class_auto) != NORMAL
            or normalize(sample.anomaly_description) != NORMAL
            or normalize(sample.class_sx) not in {NORMAL, NORMAL + " - XX", NORMAL + " - XY"}
            or sample.findings or sample.approvals):
        return False
    counts = [m for m in sample.metrics if m.metric_name == "number_of_cnv_events"]
    if len(counts) != 1 or counts[0].numeric_value != 0:
        return False
    return all(normalize(m.raw_value) in {NORMAL, NORMAL + " - XX", NORMAL + " - XY"}
               for m in sample.regions
               if m.metric_name == "region_classification")


def approve_negatives(session: Session, samples: list[SampleResult], dry_run: bool = False) -> int:
    count = 0
    for sample in samples:
        if not eligible(sample):
            continue
        count += 1
        if dry_run:
            continue
        approval = SampleApproval(sample_result_id=sample.id, revision_number=1,
                                  decision=ApprovalDecision.NEGATIVE,
                                  comment="Automatically approved: explicit VeriSeq negative result, QC PASS, zero CNV events, and no detected findings (v1).",
                                  selected_item_ids=[], secondary_findings=[], approved_by=AUTO_ACTOR)
        sample.approvals.append(approval)
        session.add(AuditEvent(actor=AUTO_ACTOR, action="SAMPLE_AUTO_APPROVED",
                              subject_type="SAMPLE", subject_id=sample.id,
                              details={"policy": "auto-negative-v1", "decision": "NEGATIVE",
                                       "approval_revision": 1}))
    session.flush()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with SessionLocal.begin() as session:
        samples = session.scalars(select(SampleResult).join(IngestionRevision).where(
            IngestionRevision.is_active.is_(True)).with_for_update(of=SampleResult)).all()
        count = approve_negatives(session, samples, dry_run=not args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "eligible_samples": count}))


if __name__ == '__main__':
    main()
