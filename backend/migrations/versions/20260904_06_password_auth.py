"""Replace Entra and emergency authentication with local password accounts."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "20260904_06"
down_revision = "20260903_05"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    user_columns = _columns("dashboard_users")
    additions = {
        "password_hash": sa.Column("password_hash", sa.Text(), nullable=True),
        "password_history": sa.Column("password_history", sa.JSON(), nullable=True),
        "must_change_password": sa.Column("must_change_password", sa.Boolean(), nullable=True),
        "temporary_password_expires_at": sa.Column("temporary_password_expires_at", sa.DateTime(timezone=True), nullable=True),
        "failed_login_attempts": sa.Column("failed_login_attempts", sa.Integer(), nullable=True),
        "locked_until": sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in additions.items():
        if name not in user_columns:
            op.add_column("dashboard_users", column)
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE dashboard_users SET password_hash = '' WHERE password_hash IS NULL"))
    bind.execute(sa.text("UPDATE dashboard_users SET password_history = '[]' WHERE password_history IS NULL"))
    bind.execute(sa.text("UPDATE dashboard_users SET must_change_password = true WHERE must_change_password IS NULL"))
    bind.execute(sa.text("UPDATE dashboard_users SET failed_login_attempts = 0 WHERE failed_login_attempts IS NULL"))
    session_columns = _columns("auth_sessions")
    if "expires_at" not in session_columns:
        op.add_column("auth_sessions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        bind.execute(
            sa.text("UPDATE auth_sessions SET expires_at = :expires_at WHERE expires_at IS NULL"),
            {"expires_at": datetime.now(UTC) + timedelta(hours=12)},
        )
    if "emergency_login_state" in sa.inspect(bind).get_table_names():
        op.drop_table("emergency_login_state")
    if "entra_subject" in _columns("dashboard_users"):
        op.drop_column("dashboard_users", "entra_subject")


def downgrade() -> None:
    if "entra_subject" not in _columns("dashboard_users"):
        op.add_column("dashboard_users", sa.Column("entra_subject", sa.String(length=255), nullable=True))
