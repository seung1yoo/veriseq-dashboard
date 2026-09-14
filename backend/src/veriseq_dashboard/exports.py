from __future__ import annotations

import csv
import hashlib
import io
from calendar import monthrange
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .errors import SourceValidationError
from .models import (
    CatalogItem,
    CatalogVersion,
    GlcpExport,
    IngestionRevision,
    SampleApproval,
    SampleResult,
    SequencingRecord,
    SourceRun,
    ApprovalDecision,
    AuditEvent,
)


def build_glcp(
    session: Session,
    run_id: str,
    flowcell_id: str,
    sample_result_ids: list[str],
    actor: str,
    output_format: str = "glcp",
) -> tuple[str, str, GlcpExport]:
    if output_format not in {"glcp", "csv", "tsv"}:
        raise SourceValidationError("EXPORT_FORMAT_INVALID", "Choose glcp, csv, or tsv.")
    if not sample_result_ids:
        raise SourceValidationError(
            "GLCP_SAMPLE_REQUIRED", "Select at least one approved sample."
        )
    run = session.get(SourceRun, run_id)
    if run is None or run.run_start_date is None:
        raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
    revision = session.scalar(
        select(IngestionRevision).where(
            IngestionRevision.source_run_id == run.id, IngestionRevision.is_active.is_(True)
        )
    )
    if revision is None:
        raise SourceValidationError("RUN_NOT_INGESTED", "Only imported runs can be exported.")
    samples = session.scalars(
        select(SampleResult)
        .where(SampleResult.id.in_(sample_result_ids))
        .options(selectinload(SampleResult.approvals))
    ).all()
    if len(samples) != len(set(sample_result_ids)):
        raise SourceValidationError(
            "GLCP_SAMPLE_NOT_FOUND", "Some selected samples were not found in the current results."
        )
    if any(
        sample.ingestion_revision_id != revision.id or sample.flowcell_id != flowcell_id
        for sample in samples
    ):
        raise SourceValidationError(
            "GLCP_SCOPE_MISMATCH", "Select samples from one run and one flowcell."
        )
    sample_names = [sample.sample_id for sample in samples]
    if len(sample_names) != len(set(sample_names)):
        raise SourceValidationError(
            "GLCP_DUPLICATE_SAMPLE_ID", "Duplicate sample identifiers cannot be exported together."
        )
    approvals: dict[str, SampleApproval] = {}
    for sample in samples:
        approval = next((item for item in sample.approvals if item.is_active), None)
        if approval is None:
            raise SourceValidationError(
                "GLCP_SAMPLE_NOT_APPROVED", "Only approved samples can be exported."
            )
        if sample.approval_blocked or sample.operational_classification != "ACTUAL" or sample.qc_flag not in {"PASS", "WARNING"} or approval.decision not in {ApprovalDecision.NEGATIVE, ApprovalDecision.POSITIVE}:
            raise SourceValidationError("EXPORT_SAMPLE_NOT_REPORTABLE", "Only reportable, approved actual samples can be exported.")
        approvals[sample.id] = approval
    catalog = session.scalar(select(CatalogVersion).where(CatalogVersion.is_active.is_(True)))
    if catalog is None:
        raise SourceValidationError("CATALOG_NOT_FOUND", "No active catalog is available.")
    items = session.scalars(
        select(CatalogItem)
        .where(CatalogItem.catalog_version_id == catalog.id, CatalogItem.active.is_(True))
        .order_by(CatalogItem.output_order)
    ).all()
    sequencing = session.scalar(
        select(SequencingRecord).where(
            SequencingRecord.ingestion_revision_id == revision.id,
            SequencingRecord.flowcell_id == flowcell_id,
        )
    )
    if sequencing is None:
        raise SourceValidationError(
            "FLOWCELL_SEQUENCING_NOT_FOUND", "Flowcell sequencing information was not found."
        )
    previous = (
        session.scalar(
            select(func.max(GlcpExport.sequence_number)).where(
                GlcpExport.source_run_id == run.id, GlcpExport.flowcell_id == flowcell_id
            )
        )
        or 0
    )
    sequence_number = previous + 1
    study_name = f"{sequencing.pool_id}_{flowcell_id}_{run.run_start_date.strftime('%y%m%d')}_{sequence_number}"
    if not items:
        raise SourceValidationError("CATALOG_EMPTY", "The catalog has no active items.")
    active_ids = {item.item_id for item in items}
    if any(set(approval.selected_item_ids) - active_ids for approval in approvals.values()):
        raise SourceValidationError("EXPORT_CATALOG_MISMATCH", "An approved item is missing from the active catalog.")
    output = io.StringIO(newline="")
    delimiter = "," if output_format == "csv" else "\t"
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\n")
    if output_format == "glcp":
        output.write(f"# Study Name : {study_name}\n# Experiment Type : VERISEQ\n")
        writer.writerow(["sample_id", "gene_id", "rs_id", "allele_1_call", "allele_2_call"])
    else:
        writer.writerow(["sample_id", "run", "flowcell", "catalog_version", "item_id", "item_name", "item_result", "sample_decision", "approval_revision", "approved_by", "secondary_findings"])
    for sample in sorted(samples, key=lambda value: value.sample_id):
        approval = approvals[sample.id]
        positive_ids = set(approval.selected_item_ids)
        for item in items:
            if output_format == "glcp":
                writer.writerow([sample.sample_id, item.item_name, item.rs_id, "N", "O" if item.item_id in positive_ids else "N"])
            else:
                import json
                writer.writerow([sample.sample_id, sample.run_name, sample.flowcell_id, catalog.version,
                    item.item_id, item.item_name, "POSITIVE" if item.item_id in positive_ids else "NEGATIVE",
                    approval.decision.value, approval.revision_number, approval.approved_by,
                    json.dumps(approval.secondary_findings, ensure_ascii=False)])
    content = output.getvalue()
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    record = GlcpExport(
        source_run_id=run.id,
        flowcell_id=flowcell_id,
        pool_id=sequencing.pool_id,
        study_name=study_name,
        sequence_number=sequence_number,
        sample_ids=sorted(sample_names),
        checksum_sha256=checksum,
        generated_by=actor,
    )
    session.add(record)
    session.add(AuditEvent(actor=actor, action="RESULTS_EXPORTED", subject_type="RUN", subject_id=run.id,
        details={"format": output_format, "checksum_sha256": checksum, "sample_count": len(samples)}))
    session.commit()
    return f"{study_name}.{'csv' if output_format == 'csv' else 'tsv'}", content, record


def build_monthly_qc(
    session: Session, year: int | None, month: int | None
) -> tuple[str, str, int]:
    active_ids = select(IngestionRevision.id).where(IngestionRevision.is_active.is_(True))
    statement = select(SampleResult).where(
            SampleResult.ingestion_revision_id.in_(active_ids),
            SampleResult.operational_classification == "ACTUAL",
        )
    if year is not None and month is not None:
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        statement = statement.where(
            SampleResult.run_name.in_(
                select(SourceRun.run_name).where(SourceRun.run_start_date.between(start, end))
            )
        )
    samples = session.scalars(
        statement
        .options(selectinload(SampleResult.metrics))
        .order_by(SampleResult.run_name, SampleResult.sample_id)
    ).all()
    output = io.StringIO(newline="")
    fields = [
        "sample_id",
        "run",
        "flowcell",
        "run_start_date",
        "sample_type",
        "qc_flag",
        "qc_reason",
        "official_qc_outcome",
        "fetal_fraction",
        "frag_size_dist",
        "non_excluded_sites",
        "cluster_density",
        "pct_q30",
        "pct_pf",
        "phasing",
        "prephasing",
        "predicted_aligned_reads",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    run_dates = dict(session.execute(select(SourceRun.run_name, SourceRun.run_start_date)).all())
    sequencing_cache: dict[tuple[str, str], dict] = {}
    for sample in samples:
        key = (sample.ingestion_revision_id, sample.flowcell_id)
        if key not in sequencing_cache:
            sequencing = session.scalar(
                select(SequencingRecord).where(
                    SequencingRecord.ingestion_revision_id == key[0],
                    SequencingRecord.flowcell_id == key[1],
                )
            )
            sequencing_cache[key] = sequencing.values.get("numeric", {}) if sequencing else {}
        metrics = {metric.metric_name: metric.raw_value for metric in sample.metrics}
        numeric = sequencing_cache[key]
        writer.writerow(
            {
                "sample_id": sample.sample_id,
                "run": sample.run_name,
                "flowcell": sample.flowcell_id,
                "run_start_date": run_dates.get(sample.run_name),
                "sample_type": sample.sample_type,
                "qc_flag": sample.qc_flag,
                "qc_reason": sample.qc_reason,
                "official_qc_outcome": sample.official_qc_outcome,
                "fetal_fraction": metrics.get("fetal_fraction", ""),
                "frag_size_dist": metrics.get("frag_size_dist", ""),
                "non_excluded_sites": metrics.get("non_excluded_sites", ""),
                **{name: numeric.get(name) for name in fields[-6:]},
            }
        )
    period_label = f"{year:04d}-{month:02d}" if year is not None and month is not None else "all"
    return f"veriseq_qc_{period_label}.csv", output.getvalue(), len(samples)
