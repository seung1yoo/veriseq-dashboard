"""Add server-side authentication sessions."""

from alembic import op

from veriseq_dashboard.models import AuthSession

revision = "20260903_04"
down_revision = "20260903_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    AuthSession.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    AuthSession.__table__.drop(bind=bind, checkfirst=True)
