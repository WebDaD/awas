"""Add one-time recording schedules.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recording_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="scheduled"),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'running', 'completed', 'cancelled', 'missed', "
            "'failed')",
            name="ck_recording_schedules_status",
        ),
        sa.CheckConstraint(
            "ends_at > starts_at",
            name="ck_recording_schedules_time_range",
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_recording_schedules_stream_id", "recording_schedules", ["stream_id"]
    )
    op.create_index(
        "ix_recording_schedules_starts_at", "recording_schedules", ["starts_at"]
    )
    op.create_index(
        "ix_recording_schedules_status", "recording_schedules", ["status"]
    )

    with op.batch_alter_table("recordings") as batch_op:
        batch_op.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_recordings_schedule_id",
            "recording_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_recordings_schedule_id", ["schedule_id"])


def downgrade() -> None:
    with op.batch_alter_table("recordings") as batch_op:
        batch_op.drop_index("ix_recordings_schedule_id")
        batch_op.drop_constraint("fk_recordings_schedule_id", type_="foreignkey")
        batch_op.drop_column("schedule_id")

    op.drop_table("recording_schedules")
