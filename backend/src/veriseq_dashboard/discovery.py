from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .errors import SourceValidationError
from .models import IngestionStatus, SourceFile, SourceRun, SourceStatus, utcnow
from .report_contract import ALL_REQUIRED_REPORT_KINDS, RUN_NAME_PATTERN, classify_file


@dataclass(frozen=True)
class ScanSummary:
    discovered: int = 0
    changed: int = 0
    unchanged: int = 0
    invalid: int = 0
    missing: int = 0


def discover_run_directories(source_root: Path) -> list[Path]:
    root = source_root.resolve()
    if not root.is_dir():
        raise SourceValidationError(
            "SOURCE_ROOT_UNAVAILABLE",
            "The VeriSeq source directory is not readable.",
            retryable=True,
            details={"source_root": root.as_posix()},
        )
    return sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and RUN_NAME_PATTERN.match(path.name)
    )


def scan_source_root(session: Session, source_root: Path) -> ScanSummary:
    root = source_root.resolve()
    run_dirs = discover_run_directories(root)
    existing = {
        row.relative_path: row
        for row in session.scalars(
            select(SourceRun)
            .where(SourceRun.source_root == root.as_posix())
            .options(selectinload(SourceRun.files))
        )
    }
    counts = {"discovered": 0, "changed": 0, "unchanged": 0, "invalid": 0}
    seen: set[str] = set()
    now = utcnow()

    for run_dir in run_dirs:
        relative = run_dir.relative_to(root).as_posix()
        seen.add(relative)
        row = existing.get(relative)
        is_new = row is None
        if row is None:
            row = SourceRun(
                source_root=root.as_posix(),
                relative_path=relative,
                run_name=run_dir.name,
                run_start_date=_run_date(run_dir.name),
            )
            session.add(row)
            session.flush()

        inventory = inventory_run(root, run_dir)
        previous = {
            file.relative_path: (file.report_kind, file.size_bytes, file.modified_ns)
            for file in row.files
        }
        current = {
            item["relative_path"]: (
                item["report_kind"],
                item["size_bytes"],
                item["modified_ns"],
            )
            for item in inventory
        }
        changed = previous != current
        row.files.clear()
        session.flush()
        row.files.extend(SourceFile(**item) for item in inventory)
        row.file_count = len(inventory)
        row.last_seen_at = now
        row.source_fingerprint = inventory_fingerprint(inventory)
        missing_kinds = sorted(
            ALL_REQUIRED_REPORT_KINDS - {item["report_kind"] for item in inventory}
        )
        if missing_kinds:
            row.source_status = SourceStatus.INVALID
            row.error_code = "RUN_REQUIRED_REPORTS_MISSING"
            row.error_message = "Required result files are not ready."
            counts["invalid"] += 1
        else:
            row.source_status = SourceStatus.READY
            row.error_code = None
            row.error_message = None
            if is_new:
                counts["discovered"] += 1
            elif changed:
                counts["changed"] += 1
            else:
                counts["unchanged"] += 1
        if changed and not is_new and row.ingestion_status == IngestionStatus.READY:
            row.ingestion_status = IngestionStatus.STALE

    missing_count = 0
    for relative, row in existing.items():
        if relative not in seen:
            row.source_status = SourceStatus.MISSING
            row.ingestion_status = IngestionStatus.STALE
            row.error_code = "RUN_DIRECTORY_MISSING"
            row.error_message = "The run directory was not found during the latest scan."
            missing_count += 1
    session.commit()
    return ScanSummary(**counts, missing=missing_count)


def inventory_fingerprint(inventory: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(inventory, key=lambda value: str(value["relative_path"])):
        digest.update(
            f"{item['relative_path']}\0{item['report_kind']}\0{item['size_bytes']}\0{item['modified_ns']}\n".encode()
        )
    return digest.hexdigest()


def load_run_with_files(session: Session, run_db_id: str) -> SourceRun:
    row = session.scalar(
        select(SourceRun).where(SourceRun.id == run_db_id).options(selectinload(SourceRun.files))
    )
    if row is None:
        raise SourceValidationError("RUN_NOT_FOUND", "Run not found.")
    return row


def inventory_run(root: Path, run_dir: Path) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.name == ".DS_Store":
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise SourceValidationError(
                "SOURCE_PATH_ESCAPE",
                "Files outside the configured source directory cannot be read.",
                details={"file": path.as_posix()},
            ) from exc
        stat = path.stat()
        inventory.append(
            {
                "relative_path": path.relative_to(run_dir).as_posix(),
                "report_kind": classify_file(path),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        )
    return inventory


def _run_date(run_name: str) -> date | None:
    match = RUN_NAME_PATTERN.match(run_name)
    if not match:
        return None
    return date.fromisoformat(match.group("date"))
