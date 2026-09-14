"""Initial MVP ingestion and reference schema."""

from alembic import op

from veriseq_dashboard import models  # noqa: F401
from veriseq_dashboard.db import Base

revision = "20260903_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
