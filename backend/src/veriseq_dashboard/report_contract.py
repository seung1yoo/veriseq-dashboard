from __future__ import annotations

import re
from pathlib import Path

RUN_NAME_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})_.+")

NIPT_REQUIRED_COLUMNS = {
    "batch_name",
    "sample_barcode",
    "sample_type",
    "sex_chrom",
    "screen_type",
    "flowcell",
    "class_sx",
    "class_auto",
    "anomaly_description",
    "qc_flag",
    "qc_reason",
    "ff",
}

SUPPLEMENTARY_REQUIRED_COLUMNS = {
    "flowcell",
    "batch_name",
    "sample_barcode",
    "region",
    "metric_name",
    "metric_value",
}

SEQUENCING_REQUIRED_COLUMNS = {
    "batch_name",
    "pool_barcode",
    "flowcell",
    "sequencing_status",
    "qc_status",
    "qc_reason",
    "cluster_density",
    "pct_q30",
    "pct_pf",
    "phasing",
    "prephasing",
    "predicted_aligned_reads",
}

RUN_LEVEL_REPORT_KINDS = {
    "process_batch_initiation_report",
    "process_library_labware_report",
    "process_library_process_log",
    "process_library_quant_report",
    "process_library_reagent_report",
    "process_library_sample_report",
}

FLOWCELL_LEVEL_REPORT_KINDS = {
    "nipt_report",
    "supplementary_report",
    "process_sequencing_report",
    "process_pool_report",
}

ALL_REQUIRED_REPORT_KINDS = RUN_LEVEL_REPORT_KINDS | FLOWCELL_LEVEL_REPORT_KINDS

OFFICIAL_QC_FLAGS = {
    "PASS",
    "WARNING",
    "FAIL",
    "CANCELLED",
    "INVALIDATED",
    "NTC_PASS",
}

SAMPLE_METRIC_NAMES = {
    "frag_size_dist",
    "fetal_fraction",
    "NCV_X",
    "NCV_Y",
    "number_of_cnv_events",
    "non_excluded_sites",
}

INTEGER_METRIC_NAMES = {
    "number_of_cnv_events",
    "non_excluded_sites",
    "start_base",
    "end_base",
}

FLOAT_METRIC_NAMES = SAMPLE_METRIC_NAMES - INTEGER_METRIC_NAMES | {
    "region_size_mb",
    "region_llr_trisomy",
    "region_llr_monosomy",
    "region_t_stat_long_reads",
    "region_mosaic_ratio",
    "region_mosaic_llr_trisomy",
    "region_mosaic_llr_monosomy",
}


def classify_file(path: Path) -> str:
    lower = path.name.lower()
    parents = {part.lower() for part in path.parts}
    if lower.endswith(".md5"):
        return "checksum"
    if "processlogs" in parents:
        patterns = {
            "batch_initiation_report": "process_batch_initiation_report",
            "library_labware_report": "process_library_labware_report",
            "library_process_log": "process_library_process_log",
            "library_quant_report": "process_library_quant_report",
            "library_reagent_report": "process_library_reagent_report",
            "library_sample_report": "process_library_sample_report",
            "sequencing_report": "process_sequencing_report",
            "pool_report": "process_pool_report",
        }
        for token, kind in patterns.items():
            if token in lower and lower.endswith(".tab"):
                return kind
        return "process_other_report"
    if "_nipt_report_" in lower and lower.endswith(".tab"):
        return "nipt_report"
    if "_supplementary_report_" in lower and lower.endswith(".tab"):
        return "supplementary_report"
    if "_sample_invalidation_report_" in lower and lower.endswith(".tab"):
        return "sample_invalidation_report"
    return "other"
