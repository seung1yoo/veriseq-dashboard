"""Add Dashboard allowlist users.

Revision ID: 20260903_02
Revises: 20260903_01
"""

from alembic import op

from veriseq_dashboard.models import DashboardUser

revision = "20260903_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    DashboardUser.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    DashboardUser.__table__.drop(bind=op.get_bind(), checkfirst=True)
