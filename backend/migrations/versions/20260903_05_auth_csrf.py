"""Add CSRF token to authentication sessions."""

import sqlalchemy as sa
from alembic import op

revision = "20260903_05"
down_revision = "20260903_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
    if "csrf_token" not in columns:
        op.add_column("auth_sessions", sa.Column("csrf_token", sa.String(length=64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
    if "csrf_token" in columns:
        op.drop_column("auth_sessions", "csrf_token")
