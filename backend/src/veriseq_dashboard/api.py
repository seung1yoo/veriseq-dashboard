from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .auth import (
    AdminCsrfUser,
    AdminUser,
    CsrfUser,
    CurrentUser,
    SessionUser,
    csrf_token_for_request,
    normalize_email,
    revoke_user_sessions,
)
from .auth_routes import PASSWORD_HASH, generate_temporary_password
from .config import Settings, get_settings
from .db import get_session
from .discovery import scan_source_root
from .errors import SourceValidationError
from .exports import build_glcp, build_monthly_qc
from .jobs import enqueue_import
from .models import (
    ApprovalDecision,
    AuditEvent,
    DashboardUser,
    Finding,
    IngestionJob,
    IngestionRevision,
    MatchCandidate,
    MatchKind,
    RegionMetric,
    SampleApproval,
    SampleMetric,
    SampleResult,
    SequencingRecord,
    SourceRun,
    UserRole,
    as_utc,
)
from .preflight import validate_run

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.OPERATOR


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    comment: str = Field(min_length=1, max_length=2000)
    selected_item_ids: list[str] = Field(default_factory=list)
    secondary_findings: list[dict] = Field(default_factory=list)


class GlcpRequest(BaseModel):
    run_id: str
    flowcell_id: str
    sample_result_ids: list[str]


@router.get("/health")
def health(session: SessionDependency, settings: SettingsDependency) -> dict:
    session.execute(select(1))
    return {
        "status": "ok",
        "database": "ok",
        "source_root": {
            "path": settings.source_root.as_posix(),
            "readable": settings.source_root.is_dir(),
        },
    }


@router.get("/session")
def get_current_session(request: Request, session: SessionDependency, user: SessionUser) -> dict:
    csrf_token = csrf_token_for_request(session, request)
    return {
        "authenticated": True,
        "user": _user_summary(user),
        "auth_method": "session" if csrf_token else "development",
        "csrf_token": csrf_token,
        "must_change_password": user.must_change_password,
    }


@router.get("/users")
def list_users(session: SessionDependency, _: AdminUser) -> dict:
    users = session.scalars(select(DashboardUser).order_by(DashboardUser.email)).all()
    return {"items": [_user_summary(user) for user in users], "total": len(users)}


@router.get("/dashboard")
def dashboard_summary(session: SessionDependency, _: CurrentUser) -> dict:
    runs = session.scalars(select(SourceRun)).all()
    active_ids = select(IngestionRevision.id).where(IngestionRevision.is_active.is_(True))
    samples = session.scalars(
        select(SampleResult)
        .where(
            SampleResult.ingestion_revision_id.in_(active_ids),
            SampleResult.operational_classification == "ACTUAL",
        )
        .options(selectinload(SampleResult.approvals))
    ).all()
    pending = sum(1 for sample in samples if not any(item.is_active for item in sample.approvals))
    blocked = sum(1 for sample in samples if sample.approval_blocked)
    return {
        "runs_total": len(runs),
        "runs_ready_to_import": sum(
            1
            for run in runs
            if run.source_status.value == "READY" and run.ingestion_status.value != "READY"
        ),
        "runs_failed": sum(1 for run in runs if run.ingestion_status.value == "FAILED"),
        "actual_samples": len(samples),
        "approval_pending": pending,
        "approval_blocked": blocked,
        "recent_runs": [
            _run_summary(run)
            for run in sorted(
                runs, key=lambda value: value.run_start_date or date.min, reverse=True
            )[:5]
        ],
    }


@router.get("/system/health")
def system_health(session: SessionDependency, settings: SettingsDependency, _: AdminUser) -> dict:
    session.execute(select(1))
    latest_job = session.scalar(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(1)
    )
    return {
        "web": "OK",
        "database": "OK",
        "source_mount": "OK" if settings.source_root.is_dir() else "UNAVAILABLE",
        "source_path": settings.source_root.as_posix(),
        "worker_last_job": _job_summary(latest_job) if latest_job else None,
        "authentication": "DEVELOPMENT" if settings.development_auth_enabled else "PASSWORD",
    }


@router.get("/jobs")
def list_jobs(
    session: SessionDependency, _: CurrentUser, limit: int = Query(default=20, ge=1, le=100)
) -> dict:
    jobs = session.scalars(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(limit)
    ).all()
    return {"items": [_job_summary(job) for job in jobs], "total": len(jobs)}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreate,
    session: SessionDependency,
    administrator: AdminCsrfUser,
    settings: SettingsDependency,
) -> dict:
    email = normalize_email(payload.email)
    if not EMAIL_PATTERN.match(email):
        raise SourceValidationError("USER_EMAIL_INVALID", "Enter a valid email address.")
    if settings.allowed_email_domain and not email.endswith(f"@{settings.allowed_email_domain}"):
        raise SourceValidationError(
            "USER_EMAIL_DOMAIN_INVALID", "Email must belong to the configured laboratory domain."
        )
    if session.scalar(select(DashboardUser).where(DashboardUser.email == email)) is not None:
        raise SourceValidationError("USER_EMAIL_ALREADY_EXISTS", "This user is already registered.")
    temporary_password = generate_temporary_password()
    password_hash = PASSWORD_HASH.hash(temporary_password)
    user = DashboardUser(
        email=email,
        display_name=payload.display_name,
        role=payload.role,
        is_active=True,
        password_hash=password_hash,
        password_history=[password_hash],
        must_change_password=True,
        temporary_password_expires_at=datetime.now(ZoneInfo("UTC"))
        + timedelta(hours=settings.temporary_password_hours),
    )
    session.add(user)
    session.flush()
    session.add(
        AuditEvent(
            actor=administrator.email,
            action="USER_ALLOWLIST_CREATED",
            subject_type="USER",
            subject_id=user.id,
            details={"email": user.email, "role": user.role.value},
        )
    )
    session.commit()
    session.refresh(user)
    return {**_user_summary(user), "temporary_password": temporary_password}


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdate,
    session: SessionDependency,
    administrator: AdminCsrfUser,
) -> dict:
    user = session.get(DashboardUser, user_id)
    if user is None:
        raise SourceValidationError("USER_NOT_FOUND", "User not found.")
    before = _user_summary(user)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.role is not None:
        if user.id == administrator.id and payload.role != UserRole.ADMIN:
            raise SourceValidationError(
                "SELF_ROLE_CHANGE_BLOCKED", "You cannot remove your own administrator role."
            )
        if (
            user.role == UserRole.ADMIN
            and payload.role != UserRole.ADMIN
            and _active_admin_count(session) <= 1
        ):
            raise SourceValidationError(
                "LAST_ADMIN_REQUIRED", "The last administrator role cannot be removed."
            )
        user.role = payload.role
    if payload.is_active is not None:
        if user.id == administrator.id and not payload.is_active:
            raise SourceValidationError(
                "SELF_DEACTIVATION_BLOCKED", "You cannot deactivate your own account."
            )
        if (
            user.role == UserRole.ADMIN
            and not payload.is_active
            and _active_admin_count(session) <= 1
        ):
            raise SourceValidationError(
                "LAST_ADMIN_REQUIRED", "The last administrator cannot be deactivated."
            )
        user.is_active = payload.is_active
        if not user.is_active:
            revoke_user_sessions(session, user.id)
    session.add(
        AuditEvent(
            actor=administrator.email,
            action="USER_ALLOWLIST_UPDATED",
            subject_type="USER",
            subject_id=user.id,
            details={"before": before, "after": _user_summary(user)},
        )
    )
    session.commit()
    session.refresh(user)
    return _user_summary(user)


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: str,
    session: SessionDependency,
    administrator: AdminCsrfUser,
    settings: SettingsDependency,
) -> dict:
    user = session.get(DashboardUser, user_id)
    if user is None:
        raise SourceValidationError("USER_NOT_FOUND", "User not found.")
    temporary_password = generate_temporary_password()
    password_hash = PASSWORD_HASH.hash(temporary_password)
    user.password_hash = password_hash
    user.password_history = [*(user.password_history or [])[-4:], password_hash]
    user.must_change_password = True
    user.temporary_password_expires_at = datetime.now(ZoneInfo("UTC")) + timedelta(
        hours=settings.temporary_password_hours
    )
    user.failed_login_attempts = 0
    user.locked_until = None
    revoked = revoke_user_sessions(session, user.id)
    session.add(
        AuditEvent(
            actor=administrator.email,
            action="USER_PASSWORD_RESET",
            subject_type="USER",
            subject_id=user.id,
            details={"revoked_sessions": revoked},
        )
    )
    session.commit()
    return {"user": _user_summary(user), "temporary_password": temporary_password}


@router.post("/users/{user_id}/unlock")
def unlock_user(user_id: str, session: SessionDependency, administrator: AdminCsrfUser) -> dict:
    user = session.get(DashboardUser, user_id)
    if user is None:
        raise SourceValidationError("USER_NOT_FOUND", "User not found.")
    user.failed_login_attempts = 0
    user.locked_until = None
    session.add(
        AuditEvent(
            actor=administrator.email,
            action="USER_UNLOCKED",
            subject_type="USER",
            subject_id=user.id,
            details={},
        )
    )
    session.commit()
    return _user_summary(user)


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(user_id: str, session: SessionDependency, administrator: AdminCsrfUser) -> dict:
    user = session.get(DashboardUser, user_id)
    if user is None:
        raise SourceValidationError("USER_NOT_FOUND", "User not found.")
    revoked = revoke_user_sessions(session, user.id)
    session.add(
        AuditEvent(
            actor=administrator.email,
            action="ADMIN_REVOKED_USER_SESSIONS",
            subject_type="USER",
            subject_id=user.id,
            details={"count": revoked},
        )
    )
    session.commit()
    return {"revoked": revoked}


@router.post("/source/scan")
def scan_source(session: SessionDependency, settings: SettingsDependency, _: CsrfUser) -> dict:
    return scan_source_root(session, settings.source_root).__dict__


@router.get("/runs")
def list_runs(
    session: SessionDependency,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    total = session.scalar(select(func.count()).select_from(SourceRun)) or 0
    rows = session.scalars(
        select(SourceRun)
        .order_by(SourceRun.run_start_date.desc(), SourceRun.run_name.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_run_summary(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "filters": {},
    }


@router.get("/runs/{run_db_id}")
def get_run(run_db_id: str, session: SessionDependency, _: CurrentUser) -> dict:
    row = session.scalar(
        select(SourceRun)
        .where(SourceRun.id == run_db_id)
        .options(selectinload(SourceRun.files), selectinload(SourceRun.revisions))
    )
    if row is None:
        raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
    active = next((revision for revision in row.revisions if revision.is_active), None)
    qc_counts: dict[str, int] = {}
    sample_type_counts: dict[str, int] = {}
    if active is not None:
        qc_counts = {
            str(flag): count
            for flag, count in session.execute(
                select(SampleResult.qc_flag, func.count())
                .where(SampleResult.ingestion_revision_id == active.id)
                .group_by(SampleResult.qc_flag)
            ).all()
        }
        sample_type_counts = {
            str(kind): count
            for kind, count in session.execute(
                select(SampleResult.operational_classification, func.count())
                .where(SampleResult.ingestion_revision_id == active.id)
                .group_by(SampleResult.operational_classification)
            ).all()
        }
    return {
        **_run_summary(row),
        "files": [
            {
                "relative_path": file.relative_path,
                "report_kind": file.report_kind,
                "size_bytes": file.size_bytes,
            }
            for file in sorted(row.files, key=lambda item: item.relative_path)
        ],
        "active_revision": _revision_summary(active) if active else None,
        "revision_count": len(row.revisions),
        "qc_counts": qc_counts,
        "sample_type_counts": sample_type_counts,
    }


@router.get("/runs/{run_db_id}/samples")
def list_run_samples(
    run_db_id: str,
    session: SessionDependency,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    revision = _active_revision_for_run(session, run_db_id)
    statement = (
        select(SampleResult)
        .where(SampleResult.ingestion_revision_id == revision.id)
        .options(selectinload(SampleResult.approvals))
    )
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    samples = session.scalars(
        statement.order_by(SampleResult.flowcell_id, SampleResult.sample_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_sample_summary(sample) for sample in samples],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/samples")
def list_samples(
    session: SessionDependency,
    _: CurrentUser,
    q: str | None = Query(default=None, max_length=255),
    sample_type: str | None = Query(default=None, max_length=80),
    qc_flag: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    active_revision_ids = select(IngestionRevision.id).where(IngestionRevision.is_active.is_(True))
    statement = (
        select(SampleResult)
        .where(SampleResult.ingestion_revision_id.in_(active_revision_ids))
        .options(selectinload(SampleResult.approvals))
    )
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                SampleResult.sample_id.ilike(term),
                SampleResult.run_name.ilike(term),
                SampleResult.anomaly_description.ilike(term),
            )
        )
    if sample_type:
        statement = statement.where(SampleResult.sample_type == sample_type)
    if qc_flag:
        statement = statement.where(SampleResult.qc_flag == qc_flag)
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    samples = session.scalars(
        statement.order_by(SampleResult.run_name.desc(), SampleResult.sample_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [_sample_summary(sample) for sample in samples],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/samples/{sample_result_id}")
def get_sample(sample_result_id: str, session: SessionDependency, _: CurrentUser) -> dict:
    sample = session.scalar(
        select(SampleResult)
        .where(SampleResult.id == sample_result_id)
        .options(
            selectinload(SampleResult.metrics),
            selectinload(SampleResult.regions),
            selectinload(SampleResult.findings)
            .selectinload(Finding.candidates)
            .selectinload(MatchCandidate.catalog_item),
            selectinload(SampleResult.approvals),
        )
    )
    if sample is None:
        raise SourceValidationError("SAMPLE_NOT_FOUND", "Sample not found.")
    revision = session.get(IngestionRevision, sample.ingestion_revision_id)
    if revision is None or not revision.is_active:
        raise SourceValidationError(
            "SAMPLE_NOT_FOUND", "Sample not found in the active results."
        )
    sequencing = session.scalar(
        select(SequencingRecord).where(
            SequencingRecord.ingestion_revision_id == revision.id,
            SequencingRecord.flowcell_id == sample.flowcell_id,
        )
    )
    return {
        **_sample_summary(sample),
        "screen_type": sample.screen_type,
        "sex_chrom": sample.sex_chrom,
        "class_sx": sample.class_sx,
        "class_auto": sample.class_auto,
        "qc_reason": sample.qc_reason,
        "ff_raw": sample.ff_raw,
        "ff_numeric": sample.ff_numeric,
        "official_qc_outcome": sample.official_qc_outcome,
        "approval_blocked": sample.approval_blocked,
        "revision": _revision_summary(revision),
        "metrics": [
            _metric_summary(metric)
            for metric in sorted(sample.metrics, key=lambda x: x.metric_name)
        ],
        "regions": [
            _region_summary(metric)
            for metric in sorted(sample.regions, key=lambda x: (x.region, x.metric_name))
        ],
        "sequencing": sequencing.values if sequencing else None,
        "findings": [_finding_summary(finding) for finding in sample.findings],
        "active_approval": next(
            (_approval_summary(approval) for approval in sample.approvals if approval.is_active),
            None,
        ),
    }


@router.post("/samples/{sample_result_id}/approvals", status_code=201)
def approve_sample(
    sample_result_id: str,
    payload: ApprovalRequest,
    session: SessionDependency,
    user: CsrfUser,
) -> dict:
    sample = session.scalar(
        select(SampleResult)
        .where(SampleResult.id == sample_result_id)
        .options(
            selectinload(SampleResult.findings)
            .selectinload(Finding.candidates)
            .selectinload(MatchCandidate.catalog_item),
            selectinload(SampleResult.approvals),
        )
    )
    if sample is None or sample.operational_classification != "ACTUAL":
        raise SourceValidationError("SAMPLE_NOT_APPROVABLE", "Only actual samples can be approved.")
    if sample.approval_blocked:
        raise SourceValidationError(
            "SAMPLE_APPROVAL_BLOCKED", "Resolve data warnings before approval."
        )
    qc_flag = sample.qc_flag.strip().upper()
    if payload.decision in {
        ApprovalDecision.NEGATIVE,
        ApprovalDecision.POSITIVE,
    } and qc_flag not in {"PASS", "WARNING"}:
        raise SourceValidationError(
            "QC_NOT_REPORTABLE", "Only PASS or WARNING results can be approved as negative or positive."
        )
    if payload.decision == ApprovalDecision.FAIL and qc_flag != "FAIL":
        raise SourceValidationError(
            "FAIL_DECISION_MISMATCH", "Only samples with QC FAIL can be approved as failed."
        )
    selectable_ids = {
        candidate.catalog_item.item_id
        for finding in sample.findings
        for candidate in finding.candidates
        if candidate.match_kind == MatchKind.EXACT
    }
    selected = set(payload.selected_item_ids)
    if not selected.issubset(selectable_ids):
        raise SourceValidationError(
            "MATCH_SELECTION_INVALID", "Selected items must be eligible matching candidates."
        )
    if (
        payload.decision == ApprovalDecision.POSITIVE
        and not selected
        and not payload.secondary_findings
    ):
        raise SourceValidationError(
            "POSITIVE_FINDING_REQUIRED",
            "Positive approval requires a selected item or secondary finding.",
        )
    if payload.decision != ApprovalDecision.POSITIVE and (selected or payload.secondary_findings):
        raise SourceValidationError(
            "FINDING_NOT_ALLOWED", "Findings can only be selected for positive approval."
        )
    for approval in sample.approvals:
        approval.is_active = False
    revision_number = (
        max((approval.revision_number for approval in sample.approvals), default=0) + 1
    )
    approval = SampleApproval(
        sample_result_id=sample.id,
        revision_number=revision_number,
        is_active=True,
        decision=payload.decision,
        comment=payload.comment.strip(),
        selected_item_ids=sorted(selected),
        secondary_findings=payload.secondary_findings,
        approved_by=user.email,
    )
    session.add(approval)
    session.flush()
    session.add(
        AuditEvent(
            actor=user.email,
            action="SAMPLE_APPROVED",
            subject_type="SAMPLE",
            subject_id=sample.id,
            details={
                "approval_revision": revision_number,
                "decision": payload.decision.value,
                "selected_item_ids": sorted(selected),
            },
        )
    )
    session.commit()
    session.refresh(approval)
    return _approval_summary(approval)


@router.get("/qc/overview")
def qc_overview(
    session: SessionDependency,
    _: CurrentUser,
    settings: SettingsDependency,
    period: str = Query(default="all", pattern="^(all|month)$"),
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
) -> dict:
    active_revision_ids = select(IngestionRevision.id).where(IngestionRevision.is_active.is_(True))
    statement = (
        select(SampleResult)
        .where(
            SampleResult.ingestion_revision_id.in_(active_revision_ids),
            SampleResult.operational_classification == "ACTUAL",
        )
        .options(selectinload(SampleResult.metrics))
    )
    if period == "month":
        today = datetime.now(ZoneInfo(settings.display_timezone)).date()
        selected_year = year or today.year
        selected_month = month or today.month
        month_start = date(selected_year, selected_month, 1)
        if selected_month == 12:
            month_end = date(selected_year + 1, 1, 1)
        else:
            month_end = date(selected_year, selected_month + 1, 1)
        statement = statement.where(
            SampleResult.run_name.in_(
                select(SourceRun.run_name).where(
                    SourceRun.run_start_date >= month_start,
                    SourceRun.run_start_date < month_end,
                )
            )
        )
    samples = session.scalars(statement).all()
    qc_counts: dict[str, int] = {}
    positive_counts = {"positive": 0, "trisomy": 0, "monosomy": 0, "deletion": 0, "duplication": 0}
    sample_metric_names = ["fetal_fraction", "frag_size_dist", "non_excluded_sites"]
    metric_points: dict[str, list[dict[str, object]]] = {name: [] for name in sample_metric_names}
    ncv_points: list[dict[str, object]] = []
    for sample in samples:
        qc_counts[sample.qc_flag] = qc_counts.get(sample.qc_flag, 0) + 1
        evidence = f"{sample.anomaly_description} {sample.class_auto} {sample.class_sx}".lower()
        categories = {
            "trisomy": "trisomy" in evidence or re.search(r"(^|\s)\+\s?\d+", evidence),
            "monosomy": "monosomy" in evidence or re.search(r"(^|\s)-\s?\d+", evidence),
            "deletion": "deletion" in evidence or " del" in evidence,
            "duplication": "duplication" in evidence or " dup" in evidence,
        }
        if any(categories.values()):
            positive_counts["positive"] += 1
        for category, matched in categories.items():
            if matched:
                positive_counts[category] += 1
        metrics = {metric.metric_name: metric for metric in sample.metrics}
        for name in sample_metric_names:
            metric = metrics.get(name)
            if metric is not None and metric.numeric_value is not None:
                metric_points[name].append(
                    {"sample_result_id": sample.id, "value": metric.numeric_value}
                )
        ncv_x = metrics.get("NCV_X")
        ncv_y = metrics.get("NCV_Y")
        if ncv_x and ncv_y and ncv_x.numeric_value is not None and ncv_y.numeric_value is not None:
            ncv_points.append(
                {
                    "sample_result_id": sample.id,
                    "x": ncv_x.numeric_value,
                    "y": ncv_y.numeric_value,
                    "class_sx": sample.class_sx,
                }
            )
    denominator = len(samples)
    distributions = {
        name: {
            **_distribution([float(point["value"]) for point in points]),
            "missing_n": denominator - len(points),
            "points": points,
        }
        for name, points in metric_points.items()
    }
    return {
        "period": period,
        "year": year,
        "month": month,
        "population": "Actual sample in active Run revisions",
        "denominator": denominator,
        "qc_counts": qc_counts,
        "positive": {
            **positive_counts,
            "rate": positive_counts["positive"] / denominator if denominator else None,
        },
        "sample_distributions": distributions,
        "ncv_scatter": ncv_points,
    }


@router.post("/exports/glcp")
def export_glcp(payload: GlcpRequest, session: SessionDependency, user: CsrfUser) -> Response:
    filename, content, record = build_glcp(
        session,
        payload.run_id,
        payload.flowcell_id,
        payload.sample_result_ids,
        user.email,
    )
    return Response(
        content=content,
        media_type="text/tab-separated-values; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": record.checksum_sha256,
        },
    )


@router.post("/exports/results")
def export_results(payload: GlcpRequest, session: SessionDependency, user: CsrfUser,
                   format: str = Query(default="csv", pattern="^(csv|tsv)$")) -> Response:
    filename, content, record = build_glcp(session, payload.run_id, payload.flowcell_id,
                                          payload.sample_result_ids, user.email, format)
    return Response(content=content,
        media_type="text/csv" if format == "csv" else "text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-SHA256": record.checksum_sha256})


@router.get("/exports/monthly-qc")
def export_monthly_qc(
    session: SessionDependency,
    user: CurrentUser,
    year: int | None = Query(default=None, ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
) -> Response:
    if (year is None) != (month is None):
        raise SourceValidationError("QC_PERIOD_INVALID", "Select both year and month.")
    filename, content, row_count = build_monthly_qc(session, year, month)
    subject_id = f"{year:04d}-{month:02d}" if year is not None and month is not None else "ALL"
    session.add(
        AuditEvent(
            actor=user.email,
            action="MONTHLY_QC_EXPORTED",
            subject_type="MONTH",
            subject_id=subject_id,
            details={"row_count": row_count, "filename": filename},
        )
    )
    session.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{run_db_id}/import-preflight")
def import_preflight(
    run_db_id: str, session: SessionDependency, settings: SettingsDependency, _: CurrentUser
) -> dict:
    return validate_run(session, settings.source_root, run_db_id).result.public_dict()


@router.post("/runs/{run_db_id}/imports", status_code=202)
def create_import(
    run_db_id: str,
    session: SessionDependency,
    settings: SettingsDependency,
    user: CsrfUser,
) -> dict:
    preflight = validate_run(session, settings.source_root, run_db_id).result
    job, created = enqueue_import(
        session,
        run_db_id,
        user.email,
        validated_source_fingerprint=preflight.source_fingerprint,
    )
    return {**_job_summary(job), "created": created}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, session: SessionDependency, _: CurrentUser) -> dict:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise SourceValidationError("JOB_NOT_FOUND", "Job not found.")
    return _job_summary(job)


def _run_summary(row: SourceRun) -> dict:
    return {
        "id": row.id,
        "run_name": row.run_name,
        "run_start_date": row.run_start_date,
        "source_status": row.source_status.value,
        "ingestion_status": row.ingestion_status.value,
        "file_count": row.file_count,
        "flowcell_count": row.flowcell_count,
        "sample_count": row.sample_count,
        "error": (
            {"code": row.error_code, "message": row.error_message} if row.error_code else None
        ),
        "last_seen_at": row.last_seen_at,
        "last_ingested_at": row.last_ingested_at,
    }


def _revision_summary(row: IngestionRevision) -> dict:
    return {
        "id": row.id,
        "revision_number": row.revision_number,
        "source_fingerprint": row.source_fingerprint,
        "flowcell_count": row.flowcell_count,
        "sample_count": row.sample_count,
        "raw_row_count": row.raw_row_count,
        "warnings": row.warnings,
        "created_at": row.created_at,
    }


def _job_summary(job: IngestionJob) -> dict:
    return {
        "id": job.id,
        "run_id": job.source_run_id,
        "status": job.status.value,
        "stage": job.stage.value,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "error": (
            {"code": job.error_code, "message": job.error_message} if job.error_code else None
        ),
    }


def _active_revision_for_run(session: Session, run_db_id: str) -> IngestionRevision:
    run = session.get(SourceRun, run_db_id)
    if run is None:
        raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
    revision = session.scalar(
        select(IngestionRevision).where(
            IngestionRevision.source_run_id == run_db_id,
            IngestionRevision.is_active.is_(True),
        )
    )
    if revision is None:
        raise SourceValidationError("RUN_NOT_INGESTED", "The run has not finished importing.")
    return revision


def _sample_summary(sample: SampleResult) -> dict:
    active_approval = next((approval for approval in sample.approvals if approval.is_active), None)
    return {
        "id": sample.id,
        "run_name": sample.run_name,
        "flowcell_id": sample.flowcell_id,
        "sample_id": sample.sample_id,
        "batch_name": sample.batch_name,
        "sample_type": sample.sample_type,
        "screen_type": sample.screen_type,
        "sex_chrom": sample.sex_chrom,
        "operational_classification": sample.operational_classification,
        "qc_flag": sample.qc_flag,
        "qc_reason": sample.qc_reason,
        "ff_raw": sample.ff_raw,
        "anomaly_description": sample.anomaly_description,
        "class_sx": sample.class_sx,
        "class_auto": sample.class_auto,
        "approval_blocked": sample.approval_blocked,
        "approval": _approval_summary(active_approval) if active_approval else None,
    }


def _metric_summary(metric: SampleMetric) -> dict:
    return {
        "metric_name": metric.metric_name,
        "raw_value": metric.raw_value,
        "numeric_value": metric.numeric_value,
        "text_value": metric.text_value,
    }


def _region_summary(metric: RegionMetric) -> dict:
    return {"region": metric.region, **_metric_summary(metric)}


def _finding_summary(finding: Finding) -> dict:
    return {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "raw_classification": finding.raw_classification,
        "chromosome": finding.chromosome,
        "consequence": finding.consequence,
        "region": finding.region,
        "start_zero_based": finding.start_zero_based,
        "end_exclusive": finding.end_exclusive,
        "candidates": [
            {
                "item_id": candidate.catalog_item.item_id,
                "item_name": candidate.catalog_item.item_name,
                "match_kind": candidate.match_kind.value,
                "overlap_bp": candidate.overlap_bp,
                "result_overlap_ratio": candidate.result_overlap_ratio,
                "item_overlap_ratio": candidate.item_overlap_ratio,
            }
            for candidate in finding.candidates
        ],
    }


def _approval_summary(approval: SampleApproval) -> dict:
    return {
        "id": approval.id,
        "revision_number": approval.revision_number,
        "decision": approval.decision.value,
        "comment": approval.comment,
        "selected_item_ids": approval.selected_item_ids,
        "secondary_findings": approval.secondary_findings,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at,
    }


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "n": 0,
            "missing_n": 0,
            "min": None,
            "q1": None,
            "median": None,
            "q3": None,
            "max": None,
        }

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {
        "n": len(ordered),
        "missing_n": 0,
        "min": ordered[0],
        "q1": percentile(0.25),
        "median": percentile(0.5),
        "q3": percentile(0.75),
        "max": ordered[-1],
    }


def _user_summary(user: DashboardUser) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.value,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "locked": bool(
            user.locked_until and as_utc(user.locked_until) > datetime.now(ZoneInfo("UTC"))
        ),
        "locked_until": user.locked_until,
        "first_login_at": user.first_login_at,
        "last_login_at": user.last_login_at,
        "created_at": user.created_at,
    }


def _active_admin_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(DashboardUser)
            .where(
                DashboardUser.role == UserRole.ADMIN,
                DashboardUser.is_active.is_(True),
            )
        )
        or 0
    )
