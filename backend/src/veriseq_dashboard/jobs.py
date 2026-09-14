from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import DashboardError, SourceValidationError
from .ingestion import ingest_run
from .models import (
    IngestionJob,
    IngestionRevision,
    IngestionStatus,
    JobStage,
    JobStatus,
    SourceRun,
    SourceStatus,
    utcnow,
)


def enqueue_import(
    session: Session,
    run_db_id: str,
    requested_by: str,
    validated_source_fingerprint: str | None = None,
) -> tuple[IngestionJob, bool]:
    run = session.get(SourceRun, run_db_id)
    if run is None:
        raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
    if run.source_status != SourceStatus.READY:
        raise SourceValidationError(
            "RUN_SOURCE_NOT_READY",
            "Cannot import until required result files are ready.",
        )
    if validated_source_fingerprint is not None:
        active_revision = session.scalar(
            select(IngestionRevision).where(
                IngestionRevision.source_run_id == run.id,
                IngestionRevision.is_active.is_(True),
            )
        )
        if (
            active_revision is not None
            and active_revision.source_fingerprint == validated_source_fingerprint
        ):
            raise SourceValidationError(
                "RUN_REVISION_ALREADY_ACTIVE",
                "An identical run revision is already active.",
            )
    existing = session.scalar(
        select(IngestionJob).where(
            IngestionJob.source_run_id == run.id,
            IngestionJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if existing is not None:
        return existing, False
    job = IngestionJob(
        source_run_id=run.id,
        requested_by=requested_by,
        active_key=run.id,
        source_fingerprint=run.source_fingerprint or "",
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(IngestionJob).where(
                IngestionJob.source_run_id == run.id,
                IngestionJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if existing is None:
            raise
        return existing, False
    session.refresh(job)
    return job, True


def claim_next_job(session: Session, worker_id: str) -> IngestionJob | None:
    job = session.scalar(
        select(IngestionJob)
        .where(IngestionJob.status == JobStatus.QUEUED)
        .order_by(IngestionJob.created_at, IngestionJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        session.rollback()
        return None
    now = utcnow()
    job.status = JobStatus.RUNNING
    job.stage = JobStage.VALIDATING_SOURCE
    job.worker_id = worker_id
    job.started_at = now
    job.heartbeat_at = now
    job.error_code = None
    job.error_message = None
    session.commit()
    session.refresh(job)
    return job


def process_job(session: Session, job_id: str, source_root: Path) -> None:
    job = session.get(IngestionJob, job_id)
    if job is None or job.status != JobStatus.RUNNING:
        raise ValueError("Ingestion job is not running")
    run_id = job.source_run_id
    actor = job.requested_by
    try:
        job.stage = JobStage.LOADING_REPORTS
        job.heartbeat_at = utcnow()
        session.commit()
        ingest_run(session, source_root, run_id, actor=actor)
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise RuntimeError("Ingestion job disappeared")
        job.status = JobStatus.SUCCEEDED
        job.stage = JobStage.COMPLETE
        job.active_key = None
        job.heartbeat_at = utcnow()
        job.completed_at = utcnow()
        session.commit()
    except Exception as exc:
        session.rollback()
        failed_job = session.get(IngestionJob, job_id)
        run = session.get(SourceRun, run_id)
        if failed_job is not None:
            failed_job.status = JobStatus.FAILED
            failed_job.stage = JobStage.FAILED
            failed_job.active_key = None
            failed_job.error_code = exc.code if isinstance(exc, DashboardError) else "IMPORT_FAILED"
            failed_job.error_message = str(exc)
            failed_job.heartbeat_at = utcnow()
            failed_job.completed_at = utcnow()
        preserve_ready_run = (
            isinstance(exc, DashboardError) and exc.code == "RUN_REVISION_ALREADY_ACTIVE"
        )
        if run is not None and not preserve_ready_run:
            run.ingestion_status = IngestionStatus.FAILED
            run.error_code = failed_job.error_code if failed_job else "IMPORT_FAILED"
            run.error_message = str(exc)
        session.commit()
        raise


def recover_interrupted_jobs(session: Session, lease_seconds: int) -> int:
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    jobs = session.scalars(
        select(IngestionJob).where(
            IngestionJob.status == JobStatus.RUNNING,
            IngestionJob.heartbeat_at < cutoff,
        )
    ).all()
    for job in jobs:
        job.status = JobStatus.FAILED
        job.stage = JobStage.FAILED
        job.active_key = None
        job.error_code = "INTERRUPTED"
        job.error_message = "The job failed because the worker heartbeat stopped."
        job.completed_at = utcnow()
        run = session.get(SourceRun, job.source_run_id)
        if run is not None:
            run.ingestion_status = IngestionStatus.FAILED
    session.commit()
    return len(jobs)
