from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from veriseq_dashboard import models  # noqa: F401
from veriseq_dashboard.db import Base


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    Base.metadata.drop_all(engine)


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    return root


def write_valid_run(root: Path, run_name: str = "2026-09-01_DEMO") -> Path:
    run = root / run_name
    logs = run / "ProcessLogs"
    logs.mkdir(parents=True)
    prefix = f"{run_name}_A_PT0001_FC001"
    reports = {
        run / f"{prefix}_nipt_report_20260902_010000.tab": (
            "batch_name\tsample_barcode\tsample_type\tsex_chrom\tscreen_type\tflowcell\tclass_sx\tclass_auto\tanomaly_description\tqc_flag\tqc_reason\tff\n"
            f"{run_name}\tSAMPLE-001\tSingleton\tyes\tbasic\tFC001\tNO ANOMALY DETECTED - XX\tNO ANOMALY DETECTED\tNO ANOMALY DETECTED\tPASS\tNONE\t12%\n"
        ),
        run / f"{prefix}_supplementary_report_20260902_010100.tab": (
            "flowcell\tbatch_name\tsample_barcode\tregion\tmetric_name\tmetric_value\n"
            f"FC001\t{run_name}\tSAMPLE-001\tNA\tfetal_fraction\t0.1234\n"
            f"FC001\t{run_name}\tSAMPLE-001\tchr21\tchromosome\tchr21\n"
            f"FC001\t{run_name}\tSAMPLE-001\tchr21\tregion_classification\tNO ANOMALY DETECTED\n"
            "# footer ignored\n"
        ),
        logs / f"{prefix}_sequencing_report_20260902_000000.tab": (
            "batch_name\tpool_barcode\tflowcell\tsequencing_status\tqc_status\tqc_reason\tcluster_density\tpct_q30\tpct_pf\tphasing\tprephasing\tpredicted_aligned_reads\n"
            f"{run_name}\tPT0001\tFC001\tcompleted\tpass\t\t200000\t90\t80\t0.002\t0.001\t10000000\n"
        ),
        logs / f"{run_name}_PT0001_pool_report_20260901_230000.tab": (
            f"batch_name\tsample_barcode\tpool_barcode\n{run_name}\tSAMPLE-001\tPT0001\n"
        ),
        logs / f"{run_name}_batch_initiation_report_20260901_090000.tab": (
            f"batch_name\tsample_barcode\n{run_name}\tSAMPLE-001\n"
        ),
        logs / f"{run_name}_library_labware_report_20260901_120000.tab": (
            f"batch_name\tlabware\n{run_name}\tPLATE-01\n"
        ),
        logs / f"{run_name}_library_process_log.tab": (
            f"batch_name\tprocess\toperator\n{run_name}\tLIBRARY:complete\toperator\n"
        ),
        logs / f"{run_name}_library_quant_report_20260901_120000.tab": (
            f"batch_name\tquant_id\n{run_name}\tQ1\n"
        ),
        logs / f"{run_name}_library_reagent_report_20260901_120000.tab": (
            f"batch_name\treagent\n{run_name}\tR1\n"
        ),
        logs / f"{run_name}_library_sample_report_20260901_120000.tab": (
            f"batch_name\tsample_barcode\n{run_name}\tSAMPLE-001\n"
        ),
    }
    for path, content in reports.items():
        path.write_text(content, encoding="utf-8")
        write_md5(path)
    return run


def write_md5(path: Path) -> None:
    digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    path.with_name(f"{path.name}.MD5").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
