from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from veriseq_dashboard.auto_approval import AUTO_ACTOR, eligible
from veriseq_dashboard.models import SampleApproval


def normal(**overrides):
    values = {
        'operational_classification': 'ACTUAL', 'approval_blocked': False,
        'qc_flag': 'PASS', 'qc_reason': 'NONE', 'class_auto': 'NO ANOMALY DETECTED',
        'anomaly_description': 'NO ANOMALY DETECTED', 'class_sx': 'NO ANOMALY DETECTED - XX',
        'findings': [], 'approvals': [],
        'regions': [SimpleNamespace(metric_name='region_classification',
                                    raw_value='NO ANOMALY DETECTED - XX')],
        'metrics': [SimpleNamespace(metric_name='number_of_cnv_events', numeric_value=0)],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize('changes', [
    {'qc_flag':'WARNING'}, {'qc_flag':'FAIL'}, {'approval_blocked':True},
    {'operational_classification':'CONTROL'}, {'operational_classification':'NTC'},
    {'qc_reason':'unexpected'}, {'class_auto':'ANOMALY DETECTED'},
    {'class_sx':'CHR Y PRESENT'}, {'anomaly_description':'DETECTED: +21'},
    {'findings':[object()]}, {'approvals':[object()]}, {'metrics':[]},
    {'metrics':[SimpleNamespace(metric_name='number_of_cnv_events',numeric_value=1)]},
    {'regions':[SimpleNamespace(metric_name='region_classification',raw_value='DETECTED: del(19)')]},
])
def test_excludes_non_explicit_or_blocked_negatives(changes):
    assert eligible(normal())
    assert not eligible(normal(**changes))


def test_ingestion_auto_approves_once(session, source_root):
    from conftest import write_md5, write_valid_run

    from veriseq_dashboard.auto_approval import approve_negatives
    from veriseq_dashboard.discovery import scan_source_root
    from veriseq_dashboard.ingestion import ingest_run
    from veriseq_dashboard.models import SampleResult, SourceRun

    run_dir = write_valid_run(source_root)
    supplementary = next(run_dir.glob('*supplementary*.tab'))
    with supplementary.open('a') as f:
        f.write('FC001\t2026-09-01_DEMO\tSAMPLE-001\tNA\tnumber_of_cnv_events\t0\n')
    write_md5(supplementary)
    scan_source_root(session, source_root)
    run = session.scalar(select(SourceRun))
    ingest_run(session, source_root, run.id)
    approval = session.scalar(select(SampleApproval))
    assert approval is not None
    assert approval.approved_by == AUTO_ACTOR
    assert approval.decision.value == 'NEGATIVE'
    sample = session.scalar(select(SampleResult))
    assert approve_negatives(session, [sample]) == 0
    assert session.scalar(select(func.count()).select_from(SampleApproval)) == 1
