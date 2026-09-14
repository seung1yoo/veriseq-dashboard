from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .discovery import inventory_fingerprint, inventory_run, load_run_with_files
from .errors import SourceValidationError
from .models import SourceStatus
from .report_contract import (
    FLOWCELL_LEVEL_REPORT_KINDS,
    NIPT_REQUIRED_COLUMNS,
    OFFICIAL_QC_FLAGS,
    RUN_LEVEL_REPORT_KINDS,
    SEQUENCING_REQUIRED_COLUMNS,
    SUPPLEMENTARY_REQUIRED_COLUMNS,
    classify_file,
)
from .report_io import read_tab_rows, require_columns

MD5_PATTERN = re.compile(r"\b([0-9a-fA-F]{32})\b")


@dataclass(frozen=True)
class ValidatedFile:
    relative_path: str
    report_kind: str
    expected_md5: str
    actual_md5: str
    headers: list[str]
    rows: list[dict[str, str]]


@dataclass(frozen=True)
class PreflightResult:
    run_db_id: str
    run_name: str
    source_fingerprint: str
    flowcell_ids: list[str]
    sample_count: int
    report_counts: dict[str, int]
    validated_file_count: int
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightBundle:
    result: PreflightResult
    files: list[ValidatedFile]


def validate_run(session: Session, source_root: Path, run_db_id: str) -> PreflightBundle:
    run = load_run_with_files(session, run_db_id)
    root = source_root.resolve()
    if run.source_root != root.as_posix():
        raise SourceValidationError(
            "RUN_SOURCE_ROOT_MISMATCH",
            "The selected run is outside the current source directory.",
        )
    if run.source_status != SourceStatus.READY:
        raise SourceValidationError(
            "RUN_SOURCE_NOT_READY",
            "Cannot import until required result files are ready.",
            details={"source_status": run.source_status.value},
        )

    run_dir = root / run.relative_path
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise SourceValidationError(
            "RUN_DIRECTORY_UNAVAILABLE",
            "The run directory is unreadable or is a symbolic link.",
        )
    resolved_run = run_dir.resolve()
    try:
        resolved_run.relative_to(root)
    except ValueError as exc:
        raise SourceValidationError(
            "SOURCE_PATH_ESCAPE",
            "The run directory points outside the allowed source directory.",
        ) from exc

    current_inventory = inventory_run(root, run_dir)
    current_inventory_fingerprint = inventory_fingerprint(current_inventory)
    if current_inventory_fingerprint != run.source_fingerprint:
        raise SourceValidationError(
            "RUN_SOURCE_CHANGED_AFTER_SCAN",
            "Run files changed since the last scan. Refresh the list.",
            retryable=True,
        )

    tab_files = [
        run_dir / str(item["relative_path"])
        for item in current_inventory
        if str(item["relative_path"]).lower().endswith(".tab")
    ]
    all_relative_lower = {
        str(item["relative_path"]).lower(): run_dir / str(item["relative_path"])
        for item in current_inventory
    }
    validated: list[ValidatedFile] = []
    checksum_digest = hashlib.sha256()
    for path in tab_files:
        relative = path.relative_to(run_dir).as_posix()
        md5_path = all_relative_lower.get(f"{relative}.md5".lower())
        if md5_path is None:
            raise SourceValidationError(
                "REPORT_MD5_FILE_MISSING",
                f"MD5 file missing: {relative}",
                details={"file": relative},
            )
        expected_md5 = _read_expected_md5(md5_path)
        actual_md5 = _file_md5(path)
        if expected_md5 != actual_md5:
            raise SourceValidationError(
                "REPORT_MD5_MISMATCH",
                f"MD5 checksum mismatch: {relative}",
                details={
                    "file": relative,
                    "expected_md5": expected_md5,
                    "actual_md5": actual_md5,
                },
            )
        kind = classify_file(path)
        headers, rows = read_tab_rows(path)
        if kind == "nipt_report":
            require_columns(path, headers, NIPT_REQUIRED_COLUMNS)
        elif kind == "supplementary_report":
            require_columns(path, headers, SUPPLEMENTARY_REQUIRED_COLUMNS)
        elif kind == "process_sequencing_report":
            require_columns(path, headers, SEQUENCING_REQUIRED_COLUMNS)
        validated.append(ValidatedFile(relative, kind, expected_md5, actual_md5, headers, rows))
        checksum_digest.update(f"{relative}\0{actual_md5}\n".encode())

    report_counts = Counter(item.report_kind for item in validated)
    nipt_files = [item for item in validated if item.report_kind == "nipt_report"]
    flowcell_ids = sorted(
        {row["flowcell"] for item in nipt_files for row in item.rows if row["flowcell"]}
    )
    if len(flowcell_ids) not in {1, 2}:
        raise SourceValidationError(
            "RUN_FLOWCELL_COUNT_INVALID",
            "A run must have exactly one or two flowcells.",
            details={"flowcell_ids": flowcell_ids},
        )
    _validate_report_counts(report_counts, len(flowcell_ids))

    sample_keys: list[tuple[str, str]] = []
    nipt_rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    warnings: list[dict[str, Any]] = []
    for item in nipt_files:
        for row in item.rows:
            key = (row["flowcell"], row["sample_barcode"])
            if key in sample_keys:
                raise SourceValidationError(
                    "NIPT_SAMPLE_DUPLICATED_IN_FLOWCELL",
                    "Duplicate sample identifiers within a flowcell.",
                    details={"flowcell": key[0], "sample_id": key[1]},
                )
            sample_keys.append(key)
            nipt_rows_by_key[key] = row
            qc_flag = row["qc_flag"].strip().upper()
            if qc_flag not in OFFICIAL_QC_FLAGS:
                warnings.append(
                    {
                        "code": "UNKNOWN_QC_FLAG",
                        "flowcell": key[0],
                        "sample_id": key[1],
                        "raw_value": row["qc_flag"],
                        "blocks_approval": True,
                    }
                )

    supplementary_keys = {
        (row["flowcell"], row["sample_barcode"])
        for item in validated
        if item.report_kind == "supplementary_report"
        for row in item.rows
        if row["sample_barcode"] not in {"", "NA"}
    }
    report_flowcells = {
        kind: {
            row["flowcell"]
            for item in validated
            if item.report_kind == kind
            for row in item.rows
            if row.get("flowcell")
        }
        for kind in ("supplementary_report", "process_sequencing_report")
    }
    flowcell_set = set(flowcell_ids)
    mismatched_flowcells = {
        kind: sorted(values) for kind, values in report_flowcells.items() if values != flowcell_set
    }
    if mismatched_flowcells:
        raise SourceValidationError(
            "RUN_FLOWCELL_LINK_MISMATCH",
            "Flowcell identifiers differ between reports.",
            details={
                "nipt_report": flowcell_ids,
                "mismatched_reports": mismatched_flowcells,
            },
        )
    for flowcell, sample_id in sample_keys:
        nipt_row = nipt_rows_by_key[(flowcell, sample_id)]
        is_reportable_actual = nipt_row["sample_type"] in {"Singleton", "Twin"} and nipt_row[
            "qc_flag"
        ].strip().upper() in {"PASS", "WARNING"}
        if is_reportable_actual and (flowcell, sample_id) not in supplementary_keys:
            warnings.append(
                {
                    "code": "SUPPLEMENTARY_SAMPLE_NOT_LINKED",
                    "flowcell": flowcell,
                    "sample_id": sample_id,
                    "blocks_approval": True,
                }
            )
    for flowcell, sample_id in sorted(supplementary_keys - set(sample_keys)):
        warnings.append(
            {
                "code": "SUPPLEMENTARY_SAMPLE_NOT_IN_NIPT_REPORT",
                "flowcell": flowcell,
                "sample_id": sample_id,
                "blocks_approval": True,
            }
        )

    return PreflightBundle(
        result=PreflightResult(
            run_db_id=run.id,
            run_name=run.run_name,
            source_fingerprint=checksum_digest.hexdigest(),
            flowcell_ids=flowcell_ids,
            sample_count=len(sample_keys),
            report_counts=dict(sorted(report_counts.items())),
            validated_file_count=len(validated),
            warnings=warnings,
        ),
        files=validated,
    )


def _validate_report_counts(report_counts: Counter[str], flowcell_count: int) -> None:
    invalid: dict[str, dict[str, int]] = {}
    for kind in sorted(RUN_LEVEL_REPORT_KINDS):
        actual = report_counts[kind]
        if actual != 1:
            invalid[kind] = {"expected": 1, "actual": actual}
    for kind in sorted(FLOWCELL_LEVEL_REPORT_KINDS):
        actual = report_counts[kind]
        if actual != flowcell_count:
            invalid[kind] = {"expected": flowcell_count, "actual": actual}
    if invalid:
        raise SourceValidationError(
            "RUN_REPORT_COUNT_INVALID",
            "Required report counts do not match the run or flowcell scope.",
            details={"report_counts": invalid},
        )


def _read_expected_md5(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig", errors="strict")
    match = MD5_PATTERN.search(content)
    if not match:
        raise SourceValidationError(
            "REPORT_MD5_FORMAT_INVALID",
            f"Invalid MD5 file format: {path.name}",
            details={"file": path.name},
        )
    return match.group(1).lower()


def _file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
