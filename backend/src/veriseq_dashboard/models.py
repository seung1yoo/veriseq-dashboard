from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class SourceStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    INVALID = "INVALID"
    MISSING = "MISSING"


class IngestionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class JobStage(str, enum.Enum):
    QUEUED = "QUEUED"
    VALIDATING_SOURCE = "VALIDATING_SOURCE"
    LOADING_REPORTS = "LOADING_REPORTS"
    PERSISTING = "PERSISTING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class UserRole(str, enum.Enum):
    OPERATOR = "OPERATOR"
    ADMIN = "ADMIN"


class ApprovalDecision(str, enum.Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    FAIL = "FAIL"
    RETEST = "RETEST"


class MatchKind(str, enum.Enum):
    EXACT = "EXACT"
    REFERENCE = "REFERENCE"


class DashboardUser(Base):
    __tablename__ = "dashboard_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.OPERATOR, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, default="")
    password_history: Mapped[list[str]] = mapped_column(JSON, default=list)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    temporary_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("dashboard_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    auth_method: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[DashboardUser] = relationship()


class SourceRun(Base):
    __tablename__ = "source_runs"
    __table_args__ = (UniqueConstraint("source_root", "relative_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_root: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(Text)
    run_name: Mapped[str] = mapped_column(String(255), index=True)
    run_start_date: Mapped[date | None] = mapped_column(Date, index=True)
    source_status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus), default=SourceStatus.DISCOVERED, index=True
    )
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus), default=IngestionStatus.PENDING, index=True
    )
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    flowcell_count: Mapped[int | None] = mapped_column(Integer)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    files: Mapped[list[SourceFile]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    revisions: Mapped[list[IngestionRevision]] = relationship(back_populates="run")
    jobs: Mapped[list[IngestionJob]] = relationship(back_populates="run")


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("source_run_id", "relative_path"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("source_runs.id"), index=True)
    relative_path: Mapped[str] = mapped_column(Text)
    report_kind: Mapped[str] = mapped_column(String(80), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    modified_ns: Mapped[int] = mapped_column(BigInteger)
    run: Mapped[SourceRun] = relationship(back_populates="files")


class IngestionRevision(Base):
    __tablename__ = "ingestion_revisions"
    __table_args__ = (UniqueConstraint("source_run_id", "revision_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("source_runs.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    code_version: Mapped[str | None] = mapped_column(String(64))
    flowcell_count: Mapped[int] = mapped_column(Integer)
    sample_count: Mapped[int] = mapped_column(Integer)
    raw_row_count: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[SourceRun] = relationship(back_populates="revisions")
    raw_rows: Mapped[list[RawReportRow]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )
    samples: Mapped[list[SampleResult]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )
    sequencing_records: Mapped[list[SequencingRecord]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class RawReportRow(Base):
    __tablename__ = "raw_report_rows"
    __table_args__ = (
        UniqueConstraint("ingestion_revision_id", "source_path", "source_row_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ingestion_revision_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_revisions.id"), index=True
    )
    report_kind: Mapped[str] = mapped_column(String(80), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    source_row_number: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict[str, str]] = mapped_column(JSON)
    revision: Mapped[IngestionRevision] = relationship(back_populates="raw_rows")


class SampleResult(Base):
    __tablename__ = "sample_results"
    __table_args__ = (UniqueConstraint("ingestion_revision_id", "flowcell_id", "sample_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ingestion_revision_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_revisions.id"), index=True
    )
    run_name: Mapped[str] = mapped_column(String(255), index=True)
    flowcell_id: Mapped[str] = mapped_column(String(80), index=True)
    sample_id: Mapped[str] = mapped_column(String(255), index=True)
    batch_name: Mapped[str] = mapped_column(String(255), index=True)
    sample_type: Mapped[str] = mapped_column(String(80), index=True)
    operational_classification: Mapped[str] = mapped_column(String(40), index=True)
    screen_type: Mapped[str] = mapped_column(String(80))
    sex_chrom: Mapped[str] = mapped_column(String(40))
    class_sx: Mapped[str] = mapped_column(String(160))
    class_auto: Mapped[str] = mapped_column(String(160))
    anomaly_description: Mapped[str] = mapped_column(Text)
    qc_flag: Mapped[str] = mapped_column(String(80), index=True)
    qc_reason: Mapped[str] = mapped_column(Text)
    ff_raw: Mapped[str] = mapped_column(String(80))
    ff_numeric: Mapped[float | None] = mapped_column(Float)
    official_qc_outcome: Mapped[str] = mapped_column(String(80), index=True)
    approval_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    source_path: Mapped[str] = mapped_column(Text)
    source_row_number: Mapped[int] = mapped_column(Integer)

    revision: Mapped[IngestionRevision] = relationship(back_populates="samples")
    metrics: Mapped[list[SampleMetric]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )
    regions: Mapped[list[RegionMetric]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )
    findings: Mapped[list[Finding]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[SampleApproval]] = relationship(
        back_populates="sample", cascade="all, delete-orphan"
    )


class SampleMetric(Base):
    __tablename__ = "sample_metrics"
    __table_args__ = (UniqueConstraint("sample_result_id", "metric_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sample_result_id: Mapped[str] = mapped_column(ForeignKey("sample_results.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(80), index=True)
    raw_value: Mapped[str] = mapped_column(Text)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str | None] = mapped_column(Text)
    sample: Mapped[SampleResult] = relationship(back_populates="metrics")


class RegionMetric(Base):
    __tablename__ = "region_metrics"
    __table_args__ = (UniqueConstraint("sample_result_id", "region", "metric_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sample_result_id: Mapped[str] = mapped_column(ForeignKey("sample_results.id"), index=True)
    region: Mapped[str] = mapped_column(String(120), index=True)
    metric_name: Mapped[str] = mapped_column(String(80), index=True)
    raw_value: Mapped[str] = mapped_column(Text)
    numeric_value: Mapped[float | None] = mapped_column(Float)
    text_value: Mapped[str | None] = mapped_column(Text)
    sample: Mapped[SampleResult] = relationship(back_populates="regions")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sample_result_id: Mapped[str] = mapped_column(ForeignKey("sample_results.id"), index=True)
    finding_type: Mapped[str] = mapped_column(String(40), index=True)
    raw_classification: Mapped[str] = mapped_column(Text)
    chromosome: Mapped[str | None] = mapped_column(String(40), index=True)
    consequence: Mapped[str | None] = mapped_column(String(40), index=True)
    region: Mapped[str | None] = mapped_column(String(120))
    start_zero_based: Mapped[int | None] = mapped_column(BigInteger)
    end_exclusive: Mapped[int | None] = mapped_column(BigInteger)
    sample: Mapped[SampleResult] = relationship(back_populates="findings")
    candidates: Mapped[list[MatchCandidate]] = relationship(
        back_populates="finding", cascade="all, delete-orphan"
    )


class MatchCandidate(Base):
    __tablename__ = "match_candidates"
    __table_args__ = (UniqueConstraint("finding_id", "catalog_item_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    catalog_item_id: Mapped[str] = mapped_column(ForeignKey("catalog_items.id"), index=True)
    match_kind: Mapped[MatchKind] = mapped_column(Enum(MatchKind), index=True)
    overlap_bp: Mapped[int | None] = mapped_column(BigInteger)
    result_overlap_ratio: Mapped[float | None] = mapped_column(Float)
    item_overlap_ratio: Mapped[float | None] = mapped_column(Float)
    finding: Mapped[Finding] = relationship(back_populates="candidates")
    catalog_item: Mapped[CatalogItem] = relationship()


class SampleApproval(Base):
    __tablename__ = "sample_approvals"
    __table_args__ = (UniqueConstraint("sample_result_id", "revision_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sample_result_id: Mapped[str] = mapped_column(ForeignKey("sample_results.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    decision: Mapped[ApprovalDecision] = mapped_column(Enum(ApprovalDecision), index=True)
    comment: Mapped[str] = mapped_column(Text)
    selected_item_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    secondary_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    approved_by: Mapped[str] = mapped_column(String(255))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sample: Mapped[SampleResult] = relationship(back_populates="approvals")


class GlcpExport(Base):
    __tablename__ = "glcp_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("source_runs.id"), index=True)
    flowcell_id: Mapped[str] = mapped_column(String(80), index=True)
    pool_id: Mapped[str] = mapped_column(String(80))
    study_name: Mapped[str] = mapped_column(String(255), unique=True)
    sequence_number: Mapped[int] = mapped_column(Integer)
    sample_ids: Mapped[list[str]] = mapped_column(JSON)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    generated_by: Mapped[str] = mapped_column(String(255))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SequencingRecord(Base):
    __tablename__ = "sequencing_records"
    __table_args__ = (UniqueConstraint("ingestion_revision_id", "flowcell_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ingestion_revision_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_revisions.id"), index=True
    )
    flowcell_id: Mapped[str] = mapped_column(String(80), index=True)
    pool_id: Mapped[str] = mapped_column(String(80), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    values: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[IngestionRevision] = relationship(back_populates="sequencing_records")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_run_id: Mapped[str] = mapped_column(ForeignKey("source_runs.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(255), default="development")
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED, index=True)
    stage: Mapped[JobStage] = mapped_column(Enum(JobStage), default=JobStage.QUEUED)
    active_key: Mapped[str | None] = mapped_column(String(36), unique=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    worker_id: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run: Mapped[SourceRun] = relationship(back_populates="jobs")


class CatalogVersion(Base):
    __tablename__ = "catalog_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(80), unique=True)
    seed_version: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list[CatalogItem]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (UniqueConstraint("catalog_version_id", "item_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    catalog_version_id: Mapped[str] = mapped_column(ForeignKey("catalog_versions.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(120), index=True)
    item_name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(120), index=True)
    consequence: Mapped[str | None] = mapped_column(String(40), index=True)
    chromosome: Mapped[str | None] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    output_order: Mapped[int] = mapped_column(Integer)
    marker_id: Mapped[str] = mapped_column(String(120))
    rs_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    version: Mapped[CatalogVersion] = relationship(back_populates="items")


class ReferenceSeedVersion(Base):
    __tablename__ = "reference_seed_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    seed_version: Mapped[str] = mapped_column(String(80), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
