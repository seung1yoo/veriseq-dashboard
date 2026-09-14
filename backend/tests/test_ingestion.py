from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_md5, write_valid_run
from sqlalchemy import func, select

from veriseq_dashboard.discovery import scan_source_root
from veriseq_dashboard.errors import SourceValidationError
from veriseq_dashboard.exports import build_glcp
from veriseq_dashboard.ingestion import ingest_run
from veriseq_dashboard.jobs import claim_next_job, enqueue_import, process_job
from veriseq_dashboard.models import (
    ApprovalDecision,
    IngestionJob,
    IngestionRevision,
    JobStatus,
    MatchCandidate,
    MatchKind,
    RawReportRow,
    SampleApproval,
    SampleResult,
    SourceRun,
    SourceStatus,
)
from veriseq_dashboard.preflight import validate_run
from veriseq_dashboard.seed import initialize_database


def test_scan_preflight_and_ingest_valid_run(session, source_root: Path) -> None:
    write_valid_run(source_root)

    summary = scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))

    assert summary.discovered == 1
    assert run is not None
    assert run.source_status == SourceStatus.READY
    preflight = validate_run(session, source_root, run.id).result
    assert preflight.flowcell_ids == ["FC001"]
    assert preflight.sample_count == 1
    assert preflight.validated_file_count == 10

    revision = ingest_run(session, source_root, run.id)

    assert revision.is_active is True
    assert revision.revision_number == 1
    assert session.scalar(select(func.count()).select_from(SampleResult)) == 1
    assert session.scalar(select(func.count()).select_from(RawReportRow)) == 12
    sample = session.scalar(select(SampleResult))
    assert sample is not None
    assert sample.ff_raw == "12%"
    assert sample.ff_numeric == pytest.approx(0.12)
    assert sample.approval_blocked is False


def test_md5_mismatch_stops_preflight(session, source_root: Path) -> None:
    run_dir = write_valid_run(source_root)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    assert run is not None
    nipt = next(run_dir.glob("*_nipt_report_*.tab"))
    nipt.write_text(nipt.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    scan_source_root(session, source_root)

    with pytest.raises(SourceValidationError) as error:
        validate_run(session, source_root, run.id)

    assert error.value.code == "REPORT_MD5_MISMATCH"


def test_failed_new_revision_keeps_previous_active_revision(session, source_root: Path) -> None:
    run_dir = write_valid_run(source_root)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    assert run is not None
    first = ingest_run(session, source_root, run.id)

    nipt = next(run_dir.glob("*_nipt_report_*.tab"))
    text = nipt.read_text(encoding="utf-8").replace("\tff\n", "\n")
    nipt.write_text(text, encoding="utf-8")
    write_md5(nipt)
    scan_source_root(session, source_root)
    job, created = enqueue_import(session, run.id, "tester@example.com")
    assert created is True
    claimed = claim_next_job(session, "test-worker")
    assert claimed is not None and claimed.id == job.id

    with pytest.raises(SourceValidationError):
        process_job(session, job.id, source_root)

    session.expire_all()
    active = session.scalars(
        select(IngestionRevision).where(IngestionRevision.is_active.is_(True))
    ).all()
    failed_job = session.get(IngestionJob, job.id)
    assert [revision.id for revision in active] == [first.id]
    assert failed_job is not None
    assert failed_job.status == JobStatus.FAILED
    assert session.scalar(select(func.count()).select_from(IngestionRevision)) == 1


def test_unchanged_active_revision_is_not_queued(session, source_root: Path) -> None:
    write_valid_run(source_root)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    assert run is not None
    revision = ingest_run(session, source_root, run.id)

    with pytest.raises(SourceValidationError) as error:
        enqueue_import(
            session,
            run.id,
            "tester@example.com",
            validated_source_fingerprint=revision.source_fingerprint,
        )

    assert error.value.code == "RUN_REVISION_ALREADY_ACTIVE"
    assert session.scalar(select(func.count()).select_from(IngestionJob)) == 0


def test_symlinked_run_is_ignored(session, source_root: Path, tmp_path: Path) -> None:
    real_run = write_valid_run(tmp_path / "outside")
    (source_root / real_run.name).symlink_to(real_run, target_is_directory=True)

    summary = scan_source_root(session, source_root)

    assert summary.discovered == 0
    assert session.scalar(select(func.count()).select_from(SourceRun)) == 0


def test_categorical_matching_and_glcp_export(session, source_root: Path) -> None:
    seed_root = Path(__file__).resolve().parents[2] / "database" / "seed"
    initialize_database(session, seed_root)
    run_dir = write_valid_run(source_root)
    nipt = next(run_dir.glob("*_nipt_report_*.tab"))
    content = nipt.read_text(encoding="utf-8").replace(
        "NO ANOMALY DETECTED\tNO ANOMALY DETECTED\tPASS",
        "ANOMALY DETECTED\tDETECTED: +21\tPASS",
    )
    nipt.write_text(content, encoding="utf-8")
    write_md5(nipt)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    assert run is not None
    ingest_run(session, source_root, run.id)
    sample = session.scalar(select(SampleResult))
    candidate = session.scalar(
        select(MatchCandidate).where(MatchCandidate.match_kind == MatchKind.EXACT)
    )
    assert sample is not None and candidate is not None
    item_id = candidate.catalog_item.item_id
    session.add(
        SampleApproval(
            sample_result_id=sample.id,
            revision_number=1,
            decision=ApprovalDecision.POSITIVE,
            comment="Verification comment",
            selected_item_ids=[item_id],
            approved_by="tester@example.com",
        )
    )
    session.commit()

    filename, output, record = build_glcp(
        session, run.id, sample.flowcell_id, [sample.id], "tester@example.com"
    )

    assert filename.endswith("_1.tsv")
    assert output.count("\n") == 261
    assert "\tN\tO\n" in output
    assert record.sequence_number == 1
