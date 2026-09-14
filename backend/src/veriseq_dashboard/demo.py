"""Deterministic invented reports; never reads clinical source data."""
from __future__ import annotations
import hashlib
from pathlib import Path

def write_demo_run(root: Path, run_name: str = "2000-01-01_DEMO") -> Path:
    run = root / run_name
    logs = run / "ProcessLogs"
    logs.mkdir(parents=True)
    prefix = f"{run_name}_A_DEMOPOOL001_DEMOFC001"
    reports = {
        run / f"{prefix}_nipt_report_20000102_010000.tab": (
            "batch_name\tsample_barcode\tsample_type\tsex_chrom\tscreen_type\tflowcell\tclass_sx\tclass_auto\tanomaly_description\tqc_flag\tqc_reason\tff\n"
            f"{run_name}\tDEMO-NEGATIVE\tSingleton\tyes\tbasic\tDEMOFC001\tNO ANOMALY DETECTED - XX\tNO ANOMALY DETECTED\tNO ANOMALY DETECTED\tPASS\tNONE\t12%\n"
        ),
        run / f"{prefix}_supplementary_report_20000102_010100.tab": (
            "flowcell\tbatch_name\tsample_barcode\tregion\tmetric_name\tmetric_value\n"
            f"DEMOFC001\t{run_name}\tDEMO-NEGATIVE\tNA\tfetal_fraction\t0.1234\n"
            f"DEMOFC001\t{run_name}\tDEMO-NEGATIVE\tchr21\tchromosome\tchr21\n"
            f"DEMOFC001\t{run_name}\tDEMO-NEGATIVE\tchr21\tregion_classification\tNO ANOMALY DETECTED\n"
            "# footer ignored\n"
        ),
        logs / f"{prefix}_sequencing_report_20000102_000000.tab": (
            "batch_name\tpool_barcode\tflowcell\tsequencing_status\tqc_status\tqc_reason\tcluster_density\tpct_q30\tpct_pf\tphasing\tprephasing\tpredicted_aligned_reads\n"
            f"{run_name}\tDEMOPOOL001\tDEMOFC001\tcompleted\tpass\t\t200000\t90\t80\t0.002\t0.001\t10000000\n"
        ),
        logs / f"{run_name}_DEMOPOOL001_pool_report_20000101_230000.tab": (
            f"batch_name\tsample_barcode\tpool_barcode\n{run_name}\tDEMO-NEGATIVE\tDEMOPOOL001\n"
        ),
        logs / f"{run_name}_batch_initiation_report_20000101_090000.tab": (
            f"batch_name\tsample_barcode\n{run_name}\tDEMO-NEGATIVE\n"
        ),
        logs / f"{run_name}_library_labware_report_20000101_120000.tab": (
            f"batch_name\tlabware\n{run_name}\tPLATE-01\n"
        ),
        logs / f"{run_name}_library_process_log.tab": (
            f"batch_name\tprocess\toperator\n{run_name}\tLIBRARY:complete\toperator\n"
        ),
        logs / f"{run_name}_library_quant_report_20000101_120000.tab": (
            f"batch_name\tquant_id\n{run_name}\tQ1\n"
        ),
        logs / f"{run_name}_library_reagent_report_20000101_120000.tab": (
            f"batch_name\treagent\n{run_name}\tR1\n"
        ),
        logs / f"{run_name}_library_sample_report_20000101_120000.tab": (
            f"batch_name\tsample_barcode\n{run_name}\tDEMO-NEGATIVE\n"
        ),
    }
    nipt = next(path for path in reports if "_nipt_report_" in path.name)
    base = reports[nipt].splitlines()[1]
    reports[nipt] += base.replace("DEMO-NEGATIVE", "DEMO-POSITIVE").replace("\tNO ANOMALY DETECTED\tNO ANOMALY DETECTED\tPASS", "\t+21\t+21\tPASS") + "\n"
    reports[nipt] += base.replace("DEMO-NEGATIVE", "DEMO-QC-FAIL").replace("\tPASS\tNONE", "\tFAIL\tLOW_FETAL_FRACTION") + "\n"
    for path in list(reports):
        if path == nipt:
            continue
        content = reports[path]
        if "DEMO-NEGATIVE" in content:
            header, *rows = content.splitlines()
            original = [row for row in rows if not row.startswith("#")]
            reports[path] = header + "\n" + "\n".join(
                row.replace("DEMO-NEGATIVE", sample)
                for sample in ["DEMO-NEGATIVE", "DEMO-POSITIVE", "DEMO-QC-FAIL"]
                for row in original
            ) + "\n"
    supplementary = next(path for path in reports if "_supplementary_report_" in path.name)
    for sample in ["DEMO-NEGATIVE", "DEMO-POSITIVE", "DEMO-QC-FAIL"]:
        for metric, value in [("number_of_cnv_events", "0"), ("frag_size_dist", "0.3"),
                              ("non_excluded_sites", "10000000"), ("NCV_X", "0.2"), ("NCV_Y", "0.1")]:
            reports[supplementary] += f"DEMOFC001\t{run_name}\t{sample}\tNA\t{metric}\t{value}\n"
    for path, content in reports.items():
        path.write_text(content, encoding="utf-8")
        write_md5(path)
    return run


def write_md5(path: Path) -> None:
    digest = hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()
    path.with_name(f"{path.name}.MD5").write_text(f"{digest}  {path.name}\n", encoding="utf-8")


def main() -> None:
    from sqlalchemy import select
    from .config import get_settings
    from .db import SessionLocal
    from .discovery import scan_source_root
    from .ingestion import ingest_run
    from .models import SourceRun, IngestionStatus
    settings = get_settings()
    # This command imports only the fixed demo run, never an operational run.
    if not (settings.source_root / "DEMO_ONLY.txt").is_file():
        raise ValueError("Demo source marker missing; refusing to import")
    with SessionLocal() as session:
        scan_source_root(session, settings.source_root)
        runs = session.scalars(select(SourceRun)).all()
        if any(run.run_name != "2000-01-01_DEMO" for run in runs):
            raise ValueError("Demo import requires an isolated demo database")
        for run in runs:
            if run.ingestion_status != IngestionStatus.READY:
                ingest_run(session, settings.source_root, run.id)

if __name__ == "__main__":
    main()
