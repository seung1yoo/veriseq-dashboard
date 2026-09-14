from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from .errors import SourceValidationError


def read_tab_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(_non_comment_lines(handle), delimiter="\t")
            if reader.fieldnames is None:
                raise SourceValidationError(
                    "REPORT_HEADER_MISSING",
                    f"Report header not found: {path.name}",
                    details={"file": path.name},
                )
            headers = [str(value) for value in reader.fieldnames]
            rows = []
            for row in reader:
                if None in row:
                    raise SourceValidationError(
                        "REPORT_COLUMN_COUNT_MISMATCH",
                        f"Report column count mismatch: {path.name}",
                        details={"file": path.name, "row": reader.line_num},
                    )
                rows.append({header: str(row.get(header, "")) for header in headers})
            return headers, rows
    except UnicodeDecodeError as exc:
        raise SourceValidationError(
            "REPORT_ENCODING_INVALID",
            f"Cannot read the report as UTF-8: {path.name}",
            details={"file": path.name},
        ) from exc


def require_columns(path: Path, headers: list[str], required: set[str]) -> None:
    missing = sorted(required - set(headers))
    if missing:
        raise SourceValidationError(
            "REPORT_REQUIRED_COLUMNS_MISSING",
            f"Required columns are missing: {path.name}",
            details={"file": path.name, "missing_columns": missing},
        )


def _non_comment_lines(handle: Iterator[str]) -> Iterator[str]:
    for line in handle:
        if line.lstrip().startswith("#"):
            continue
        yield line


def numeric_value(metric_name: str, raw_value: str) -> float | None:
    if raw_value in {"", "NA", "NOT TESTED"}:
        return None
    try:
        if metric_name in {"number_of_cnv_events", "non_excluded_sites", "start_base", "end_base"}:
            return float(int(raw_value))
        return float(raw_value)
    except ValueError:
        return None


def percent_value(raw_value: str) -> float | None:
    value = raw_value.strip()
    if not value or value.startswith("<"):
        return None
    if value.endswith("%"):
        value = value[:-1]
        try:
            return float(value) / 100
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None
