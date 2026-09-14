from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .auto_approval import approve_negatives
from .errors import SourceValidationError
from .matching import persist_findings_and_candidates
from .models import (
    AuditEvent,
    IngestionRevision,
    IngestionStatus,
    RawReportRow,
    RegionMetric,
    SampleMetric,
    SampleResult,
    SequencingRecord,
    SourceRun,
    utcnow,
)
from .preflight import PreflightBundle, validate_run
from .report_contract import FLOAT_METRIC_NAMES, INTEGER_METRIC_NAMES, SAMPLE_METRIC_NAMES
from .report_io import numeric_value, percent_value


def ingest_run(
    session: Session,
    source_root: Path,
    run_db_id: str,
    actor: str = "development",
) -> IngestionRevision:
    try:
        bundle = validate_run(session, source_root, run_db_id)
        run = session.get(SourceRun, run_db_id)
        if run is None:
            raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
        active = session.scalar(
            select(IngestionRevision).where(
                IngestionRevision.source_run_id == run.id,
                IngestionRevision.is_active.is_(True),
            )
        )
        if active and active.source_fingerprint == bundle.result.source_fingerprint:
            raise SourceValidationError(
                "RUN_REVISION_ALREADY_ACTIVE",
                "An identical run revision is already active.",
            )

        run.ingestion_status = IngestionStatus.RUNNING
        next_revision = (
            session.scalar(
                select(func.max(IngestionRevision.revision_number)).where(
                    IngestionRevision.source_run_id == run.id
                )
            )
            or 0
        ) + 1
        revision = IngestionRevision(
            source_run_id=run.id,
            revision_number=next_revision,
            is_active=False,
            source_fingerprint=bundle.result.source_fingerprint,
            code_version=os.environ.get("VERISEQ_CODE_VERSION"),
            flowcell_count=len(bundle.result.flowcell_ids),
            sample_count=bundle.result.sample_count,
            raw_row_count=sum(len(file.rows) for file in bundle.files),
            warnings=bundle.result.warnings,
        )
        session.add(revision)
        session.flush()
        _persist_raw_rows(session, revision, bundle)
        samples = _persist_samples(session, revision, run.run_name, bundle)
        _persist_supplementary(session, samples, bundle)
        persist_findings_and_candidates(session, samples, bundle)
        _persist_sequencing(session, revision, bundle)
        session.flush()

        session.execute(
            update(IngestionRevision)
            .where(
                IngestionRevision.source_run_id == run.id,
                IngestionRevision.id != revision.id,
            )
            .values(is_active=False)
        )
        approve_negatives(session, list(samples.values()))
        revision.is_active = True
        run.ingestion_status = IngestionStatus.READY
        run.flowcell_count = len(bundle.result.flowcell_ids)
        run.sample_count = bundle.result.sample_count
        run.last_ingested_at = utcnow()
        run.error_code = None
        run.error_message = None
        session.add(
            AuditEvent(
                actor=actor,
                action="RUN_REVISION_ACTIVATED",
                subject_type="RUN",
                subject_id=run.id,
                details={
                    "run_name": run.run_name,
                    "revision_number": next_revision,
                    "source_fingerprint": revision.source_fingerprint,
                    "sample_count": revision.sample_count,
                },
            )
        )
        session.commit()
        session.refresh(revision)
        return revision
    except Exception:
        session.rollback()
        raise


def _persist_raw_rows(
    session: Session, revision: IngestionRevision, bundle: PreflightBundle
) -> None:
    for file in bundle.files:
        for row_number, values in enumerate(file.rows, start=1):
            session.add(
                RawReportRow(
                    ingestion_revision_id=revision.id,
                    report_kind=file.report_kind,
                    source_path=file.relative_path,
                    source_row_number=row_number,
                    values=values,
                )
            )


def _persist_samples(
    session: Session,
    revision: IngestionRevision,
    run_name: str,
    bundle: PreflightBundle,
) -> dict[tuple[str, str], SampleResult]:
    samples: dict[tuple[str, str], SampleResult] = {}
    run_has_blocking_warning = any(
        warning.get("blocks_approval") for warning in bundle.result.warnings
    )
    nipt_files = [file for file in bundle.files if file.report_kind == "nipt_report"]
    for file in nipt_files:
        for row_number, row in enumerate(file.rows, start=1):
            sample_type = row["sample_type"]
            qc_flag = row["qc_flag"].strip().upper()
            operational_classification = _sample_classification(sample_type)
            approval_blocked = (
                run_has_blocking_warning
                or operational_classification == "OTHER_UNCLASSIFIED"
                or qc_flag
                not in {
                    "PASS",
                    "WARNING",
                    "FAIL",
                    "CANCELLED",
                    "INVALIDATED",
                    "NTC_PASS",
                }
            )
            sample = SampleResult(
                ingestion_revision_id=revision.id,
                run_name=run_name,
                flowcell_id=row["flowcell"],
                sample_id=row["sample_barcode"],
                batch_name=row["batch_name"],
                sample_type=sample_type,
                operational_classification=operational_classification,
                screen_type=row["screen_type"],
                sex_chrom=row["sex_chrom"],
                class_sx=row["class_sx"],
                class_auto=row["class_auto"],
                anomaly_description=row["anomaly_description"],
                qc_flag=row["qc_flag"],
                qc_reason=row["qc_reason"],
                ff_raw=row["ff"],
                ff_numeric=percent_value(row["ff"]),
                official_qc_outcome=_official_qc_outcome(qc_flag),
                approval_blocked=approval_blocked,
                source_path=file.relative_path,
                source_row_number=row_number,
            )
            session.add(sample)
            session.flush()
            samples[(sample.flowcell_id, sample.sample_id)] = sample
    return samples


def _persist_supplementary(
    session: Session,
    samples: dict[tuple[str, str], SampleResult],
    bundle: PreflightBundle,
) -> None:
    for file in bundle.files:
        if file.report_kind != "supplementary_report":
            continue
        for row in file.rows:
            sample = samples.get((row["flowcell"], row["sample_barcode"]))
            if sample is None:
                continue
            metric_name = row["metric_name"]
            raw_value = row["metric_value"]
            number = (
                numeric_value(metric_name, raw_value)
                if metric_name in INTEGER_METRIC_NAMES | FLOAT_METRIC_NAMES
                else None
            )
            text = None if number is not None or raw_value in {"", "NA"} else raw_value
            if row["region"] == "NA" and metric_name in SAMPLE_METRIC_NAMES:
                session.add(
                    SampleMetric(
                        sample_result_id=sample.id,
                        metric_name=metric_name,
                        raw_value=raw_value,
                        numeric_value=number,
                        text_value=text,
                    )
                )
            elif row["region"] not in {"", "NA"}:
                session.add(
                    RegionMetric(
                        sample_result_id=sample.id,
                        region=row["region"],
                        metric_name=metric_name,
                        raw_value=raw_value,
                        numeric_value=number,
                        text_value=text,
                    )
                )


def _persist_sequencing(
    session: Session, revision: IngestionRevision, bundle: PreflightBundle
) -> None:
    numeric_fields = {
        "cluster_density",
        "pct_q30",
        "pct_pf",
        "phasing",
        "prephasing",
        "predicted_aligned_reads",
    }
    for file in bundle.files:
        if file.report_kind != "process_sequencing_report":
            continue
        for row in file.rows:
            values: dict[str, Any] = dict(row)
            values["numeric"] = {
                field: numeric_value(field, row.get(field, "")) for field in numeric_fields
            }
            session.add(
                SequencingRecord(
                    ingestion_revision_id=revision.id,
                    flowcell_id=row["flowcell"],
                    pool_id=row["pool_barcode"],
                    source_path=file.relative_path,
                    values=values,
                )
            )


def _sample_classification(sample_type: str) -> str:
    return {
        "Singleton": "ACTUAL",
        "Twin": "ACTUAL",
        "Control": "CONTROL",
        "NTC": "NTC",
    }.get(sample_type, "OTHER_UNCLASSIFIED")


def _official_qc_outcome(qc_flag: str) -> str:
    return {
        "PASS": "REPORTABLE_PASS",
        "WARNING": "REPORTABLE_WARNING",
        "FAIL": "NON_REPORTABLE_FAIL",
        "CANCELLED": "NON_REPORTABLE_CANCELLED",
        "INVALIDATED": "NON_REPORTABLE_INVALIDATED",
        "NTC_PASS": "CONTROL_NTC_PASS",
    }.get(qc_flag, "OTHER")
