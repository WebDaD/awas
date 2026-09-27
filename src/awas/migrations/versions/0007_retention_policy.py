"""Add automatic recording retention policy.

Revision ID: 0007
Revises: 0006
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_recordings_status_ended_at",
        "recordings",
        ["status", "ended_at"],
    )
    op.create_table(
        "retention_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_mode", sa.String(length=16), nullable=True),
        sa.Column("last_deleted_count", sa.Integer(), nullable=False),
        sa.Column("last_freed_bytes", sa.BigInteger(), nullable=False),
        sa.Column("last_failed_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_retention_policy_singleton"),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 3650",
            name="ck_retention_policy_days",
        ),
        sa.CheckConstraint(
            "last_run_mode IS NULL OR last_run_mode IN ('automatic', 'manual')",
            name="ck_retention_policy_run_mode",
        ),
        sa.CheckConstraint(
            "last_deleted_count >= 0",
            name="ck_retention_policy_deleted_count",
        ),
        sa.CheckConstraint(
            "last_freed_bytes >= 0",
            name="ck_retention_policy_freed_bytes",
        ),
        sa.CheckConstraint(
            "last_failed_count >= 0",
            name="ck_retention_policy_failed_count",
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    policy = sa.table(
        "retention_policy",
        sa.column("id", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("retention_days", sa.Integer()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("last_deleted_count", sa.Integer()),
        sa.column("last_freed_bytes", sa.BigInteger()),
        sa.column("last_failed_count", sa.Integer()),
    )
    op.bulk_insert(
        policy,
        [
            {
                "id": 1,
                "enabled": False,
                "retention_days": 90,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
                "last_deleted_count": 0,
                "last_freed_bytes": 0,
                "last_failed_count": 0,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("retention_policy")
    op.drop_index("ix_recordings_status_ended_at", table_name="recordings")
