from pathlib import Path
import csv
import io
import json

import pytest
from sqlalchemy import select

from veriseq_dashboard.demo import write_demo_run
from veriseq_dashboard.discovery import scan_source_root
from veriseq_dashboard.ingestion import ingest_run
from veriseq_dashboard.exports import build_glcp
from veriseq_dashboard.seed import initialize_database
from veriseq_dashboard.errors import SourceValidationError
from veriseq_dashboard.models import SourceRun, SampleResult, SampleApproval, ApprovalDecision, CatalogItem

SEEDS = Path(__file__).resolve().parents[2] / 'database/seed'


def test_demo_and_export_formats_preserve_approved_results(session, source_root):
    initialize_database(session, SEEDS)
    write_demo_run(source_root)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    ingest_run(session, source_root, run.id)
    samples = {s.sample_id: s for s in session.scalars(select(SampleResult)).all()}
    assert set(samples) == {'DEMO-NEGATIVE', 'DEMO-POSITIVE', 'DEMO-QC-FAIL'}
    negative = samples['DEMO-NEGATIVE']
    positive = samples['DEMO-POSITIVE']
    failed = samples['DEMO-QC-FAIL']
    assert len(negative.approvals) == 1
    assert negative.approvals[0].decision == ApprovalDecision.NEGATIVE
    assert not positive.approvals and not failed.approvals
    assert any(f.chromosome == 'chr21' for f in positive.findings)
    item = session.scalar(select(CatalogItem).where(CatalogItem.item_id == 'I-T21'))
    session.add(SampleApproval(sample_result_id=positive.id, revision_number=1,
        decision=ApprovalDecision.POSITIVE, comment='Synthetic review', selected_item_ids=[item.item_id],
        secondary_findings=[], approved_by='demo-reviewer@example.com'))
    session.commit()
    session.expire_all()
    rows_by_format = {}
    for format in ['csv', 'tsv', 'glcp']:
        filename, content, record = build_glcp(session, run.id, negative.flowcell_id,
            [negative.id, positive.id], 'demo-reviewer@example.com', format)
        lines = [line for line in content.splitlines() if not line.startswith('#')]
        rows_by_format[format] = list(csv.DictReader(io.StringIO('\n'.join(lines)), delimiter=',' if format == 'csv' else '\t'))
        assert len(rows_by_format[format]) == 516
        assert record.checksum_sha256 and filename.endswith('.csv' if format == 'csv' else '.tsv')
    assert rows_by_format['csv'] == rows_by_format['tsv']
    common_positive = [r for r in rows_by_format['csv'] if r['item_result'] == 'POSITIVE']
    glcp_positive = [r for r in rows_by_format['glcp'] if r['allele_2_call'] == 'O']
    assert len(common_positive) == len(glcp_positive) == 1
    assert common_positive[0]['item_id'] == 'I-T21'
    assert glcp_positive[0]['gene_id'] == item.item_name
    with pytest.raises(SourceValidationError):
        build_glcp(session, run.id, negative.flowcell_id, [failed.id], 'demo@example.com', 'csv')
    assert len(negative.approvals) == 1


def test_custom_catalog_count_and_immutable_version(session, tmp_path):
    payload = json.loads((SEEDS / 'nipt_catalog.v1.json').read_text())
    payload['items'] = payload['items'][:2]
    payload['item_count'] = 2
    (tmp_path / 'nipt_catalog.v1.json').write_text(json.dumps(payload))
    (tmp_path / 'dashboard_reference.v1.json').write_bytes((SEEDS / 'dashboard_reference.v1.json').read_bytes())
    assert initialize_database(session, tmp_path)['catalog_items'] == 2
    payload['items'][0]['display']['item_name'] = 'Changed'
    (tmp_path / 'nipt_catalog.v1.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='without a new catalog_version'):
        initialize_database(session, tmp_path)
