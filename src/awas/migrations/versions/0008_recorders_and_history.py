"""Add recorder selection and retained recording history.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "streams",
        sa.Column(
            "preferred_recorder",
            sa.String(length=32),
            nullable=False,
            server_default="streamripper",
        ),
    )
    op.add_column(
        "recordings",
        sa.Column("recorder", sa.String(length=32), nullable=False, server_default="ffmpeg"),
    )
    op.add_column("recordings", sa.Column("file_deleted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "recordings",
        sa.Column("file_delete_reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "recording_schedules",
        sa.Column("recorder", sa.String(length=32), nullable=False, server_default="ffmpeg"),
    )
    op.add_column(
        "recording_schedules",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_recording_schedules_is_hidden",
        "recording_schedules",
        ["is_hidden"],
    )
    op.add_column(
        "recurring_schedules",
        sa.Column("recorder", sa.String(length=32), nullable=False, server_default="ffmpeg"),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_recurring_schedules_is_hidden",
        "recurring_schedules",
        ["is_hidden"],
    )


def downgrade() -> None:
    op.drop_index("ix_recurring_schedules_is_hidden", table_name="recurring_schedules")
    op.drop_column("recurring_schedules", "is_hidden")
    op.drop_column("recurring_schedules", "recorder")
    op.drop_index("ix_recording_schedules_is_hidden", table_name="recording_schedules")
    op.drop_column("recording_schedules", "is_hidden")
    op.drop_column("recording_schedules", "recorder")
    op.drop_column("recordings", "file_delete_reason")
    op.drop_column("recordings", "file_deleted_at")
    op.drop_column("recordings", "recorder")
    op.drop_column("streams", "preferred_recorder")
