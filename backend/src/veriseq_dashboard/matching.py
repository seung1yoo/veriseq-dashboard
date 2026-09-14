from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CatalogItem, CatalogVersion, Finding, MatchCandidate, MatchKind, SampleResult
from .preflight import PreflightBundle


def persist_findings_and_candidates(
    session: Session,
    samples: dict[tuple[str, str], SampleResult],
    bundle: PreflightBundle,
) -> None:
    catalog = session.scalar(select(CatalogVersion).where(CatalogVersion.is_active.is_(True)))
    if catalog is None:
        return
    items = session.scalars(
        select(CatalogItem).where(
            CatalogItem.catalog_version_id == catalog.id, CatalogItem.active.is_(True)
        )
    ).all()
    _persist_categorical_findings(session, samples, items)
    groups: dict[tuple[str, str, str], dict[str, str]] = defaultdict(dict)
    for file in bundle.files:
        if file.report_kind != "supplementary_report":
            continue
        for row in file.rows:
            region = row.get("region", "")
            if region in {"", "NA", row.get("chromosome", "")}:
                continue
            groups[(row.get("flowcell", ""), row.get("sample_barcode", ""), region)][
                row.get("metric_name", "")
            ] = row.get("metric_value", "")
    for (flowcell, sample_id, region), values in groups.items():
        sample = samples.get((flowcell, sample_id))
        if sample is None:
            continue
        classification = values.get("region_classification", "")
        consequence = _consequence(classification)
        chromosome = values.get("chromosome") or _chromosome_from_region(region)
        start = _integer(values.get("start_base"))
        end = _integer(values.get("end_base"))
        if (
            consequence is None
            or chromosome is None
            or start is None
            or end is None
            or end <= start
        ):
            continue
        finding = Finding(
            sample_result_id=sample.id,
            finding_type="PARTIAL_CNV",
            raw_classification=classification,
            chromosome=chromosome,
            consequence=consequence,
            region=region,
            start_zero_based=max(0, start - 1),
            end_exclusive=end,
        )
        session.add(finding)
        session.flush()
        _match_interval(session, finding, items)


def _persist_categorical_findings(
    session: Session, samples: dict[tuple[str, str], SampleResult], items: list[CatalogItem]
) -> None:
    categorical = [
        item for item in items if item.payload["match_definition"].get("method") == "categorical"
    ]
    for sample in samples.values():
        evidence = f"{sample.anomaly_description} {sample.class_auto} {sample.class_sx}"
        for item in categorical:
            tokens = item.payload["match_definition"].get("veriseq_tokens", [])
            if not any(_token_present(evidence, str(token)) for token in tokens):
                continue
            finding = Finding(
                sample_result_id=sample.id,
                finding_type="WHOLE_CHROMOSOME",
                raw_classification=evidence.strip(),
                chromosome=item.chromosome,
                consequence=item.consequence,
            )
            session.add(finding)
            session.flush()
            session.add(
                MatchCandidate(
                    finding_id=finding.id,
                    catalog_item_id=item.id,
                    match_kind=MatchKind.EXACT,
                )
            )


def _match_interval(session: Session, finding: Finding, items: list[CatalogItem]) -> None:
    assert finding.start_zero_based is not None and finding.end_exclusive is not None
    result_size = finding.end_exclusive - finding.start_zero_based
    for item in items:
        definition = item.payload["match_definition"]
        if definition.get("method") != "genomic_interval":
            continue
        if item.consequence != finding.consequence:
            continue
        best: tuple[int, float, float] | None = None
        for region in definition.get("regions", []):
            if region.get("chromosome") != finding.chromosome:
                continue
            item_start, item_end = int(region["start"]), int(region["end"])
            overlap = max(
                0, min(finding.end_exclusive, item_end) - max(finding.start_zero_based, item_start)
            )
            if overlap <= 0:
                continue
            ratios = (overlap, overlap / result_size, overlap / (item_end - item_start))
            if best is None or ratios[0] > best[0]:
                best = ratios
        if best is None:
            continue
        overlap, result_ratio, item_ratio = best
        kind = MatchKind.EXACT if result_ratio > 0.5 and item_ratio > 0.5 else MatchKind.REFERENCE
        session.add(
            MatchCandidate(
                finding_id=finding.id,
                catalog_item_id=item.id,
                match_kind=kind,
                overlap_bp=overlap,
                result_overlap_ratio=result_ratio,
                item_overlap_ratio=item_ratio,
            )
        )


def _token_present(text: str, token: str) -> bool:
    return (
        re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.IGNORECASE)
        is not None
    )


def _consequence(value: str) -> str | None:
    lowered = value.lower()
    if "deletion" in lowered or re.search(r"(^|\W)del(\W|$)", lowered):
        return "deletion"
    if "duplication" in lowered or re.search(r"(^|\W)dup(\W|$)", lowered):
        return "duplication"
    return None


def _chromosome_from_region(region: str) -> str | None:
    match = re.match(r"^(chr(?:[1-9]|1\d|2[0-2]|X|Y))", region, re.IGNORECASE)
    return match.group(1) if match else None


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value not in {None, "", "NA"} else None
    except ValueError:
        return None
