"""add login attempt tracking

Revision ID: 3c91a4d7e2b8
Revises: b75bb5e15a5e
Create Date: 2026-10-26 10:42:11.004512

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c91a4d7e2b8"
down_revision: str | None = "b75bb5e15a5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_logged_in_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("login_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "users", sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "last_failed_login_at")
    op.drop_column("users", "login_attempts")
    op.drop_column("users", "last_logged_in_at")
