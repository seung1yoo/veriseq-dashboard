from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from veriseq_dashboard.matching import _match_interval
from veriseq_dashboard.models import CatalogItem, MatchKind
from veriseq_dashboard.repair_matching import repair_matching
from veriseq_dashboard.seed import initialize_database


def test_interval_matching_uses_region_chromosome(session):
    initialize_database(session, Path(__file__).resolve().parents[2] / 'database/seed')
    items = session.scalars(select(CatalogItem)).all()
    interval_items = [i for i in items if i.payload['match_definition']['method'] == 'genomic_interval']
    assert len(interval_items) == 232
    assert all(i.chromosome is not None for i in interval_items)
    for item in interval_items:
        item.chromosome = None  # Reproduce databases created by the old loader.
    finding = SimpleNamespace(id='test-finding', chromosome='chr19', consequence='deletion',
                              start_zero_based=8100000, end_exclusive=19600000)
    added = []
    _match_interval(SimpleNamespace(add=added.append), finding, items)
    by_id = {i.id: i.item_name for i in items}
    matches = {by_id[c.catalog_item_id]: c for c in added}
    assert set(matches) == {'19p deletion', '19p13.2 deletion', '19p13.13 deletion', '19p13.12 deletion'}
    exact = matches['19p13.2 deletion']
    assert exact.match_kind == MatchKind.EXACT
    assert exact.result_overlap_ratio == pytest.approx(5800000 / 11500000)
    assert exact.item_overlap_ratio == pytest.approx(5800000 / 7000000)
    assert all(c.match_kind == MatchKind.REFERENCE for name, c in matches.items() if name != '19p13.2 deletion')
    finding.chromosome = 'chrY'
    added.clear()
    _match_interval(SimpleNamespace(add=added.append), finding,
                    [i for i in interval_items if i.item_name.startswith("19")])
    assert not added
    assert repair_matching(session)['catalog_updated'] == 232
    assert repair_matching(session)['catalog_updated'] == 0


def test_repair_adds_candidates_once_and_preserves_approved_findings(session, source_root):
    from conftest import write_valid_run
    from sqlalchemy import func

    from veriseq_dashboard.discovery import scan_source_root
    from veriseq_dashboard.ingestion import ingest_run
    from veriseq_dashboard.models import (
        ApprovalDecision,
        Finding,
        MatchCandidate,
        SampleApproval,
        SampleResult,
        SourceRun,
    )
    initialize_database(session, Path(__file__).resolve().parents[2] / 'database/seed')
    write_valid_run(source_root)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    ingest_run(session, source_root, run.id)
    sample = session.scalar(select(SampleResult))
    finding = Finding(sample_result_id=sample.id, finding_type='PARTIAL_CNV',
                      raw_classification='DETECTED: del(19)(p13.2p13.11)',
                      chromosome='chr19', consequence='deletion',
                      start_zero_based=8100000, end_exclusive=19600000)
    session.add(finding)
    session.flush()
    assert repair_matching(session)['candidates_added'] == 4
    assert repair_matching(session)['candidates_added'] == 0
    session.add(SampleApproval(sample_result_id=sample.id, revision_number=1,
                              decision=ApprovalDecision.NEGATIVE, comment='test',
                              approved_by='test@example.com'))
    session.flush()
    session.expire(sample, ['approvals'])
    assert repair_matching(session)['approved_findings_skipped'] == 1
    assert session.scalar(select(func.count()).select_from(MatchCandidate)) == 4
