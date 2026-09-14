"""Add findings, approvals, and GLCP export history."""

from alembic import op

from veriseq_dashboard.models import Finding, GlcpExport, MatchCandidate, SampleApproval

revision = "20260903_03"
down_revision = "20260903_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Finding.__table__.create(bind=bind, checkfirst=True)
    MatchCandidate.__table__.create(bind=bind, checkfirst=True)
    SampleApproval.__table__.create(bind=bind, checkfirst=True)
    GlcpExport.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    GlcpExport.__table__.drop(bind=bind, checkfirst=True)
    SampleApproval.__table__.drop(bind=bind, checkfirst=True)
    MatchCandidate.__table__.drop(bind=bind, checkfirst=True)
    Finding.__table__.drop(bind=bind, checkfirst=True)
