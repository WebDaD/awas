"""Add file types and configurable recurrence patterns.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

LINK_BACKUP_TABLE = "_awas_0009_recording_schedule_links"


def preserve_recording_schedule_links() -> None:
    op.execute(
        f"CREATE TEMPORARY TABLE {LINK_BACKUP_TABLE} "
        "(recording_id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL)"
    )
    op.execute(
        f"INSERT INTO {LINK_BACKUP_TABLE} (recording_id, schedule_id) "
        "SELECT id, schedule_id FROM recordings WHERE schedule_id IS NOT NULL"
    )


def restore_recording_schedule_links() -> None:
    op.execute(
        "UPDATE recordings SET schedule_id = "
        f"(SELECT schedule_id FROM {LINK_BACKUP_TABLE} "
        f"WHERE recording_id = recordings.id) WHERE id IN "
        f"(SELECT recording_id FROM {LINK_BACKUP_TABLE})"
    )
    op.execute(f"DROP TABLE {LINK_BACKUP_TABLE}")


def upgrade() -> None:
    op.add_column(
        "streams",
        sa.Column(
            "preferred_file_type",
            sa.String(length=16),
            nullable=False,
            server_default="ts",
        ),
    )
    op.add_column(
        "recordings",
        sa.Column("file_type", sa.String(length=16), nullable=False, server_default="ts"),
    )
    op.execute(
        "UPDATE recordings "
        "SET file_type = lower(substr(file_name, instr(file_name, '.') + 1)) "
        "WHERE instr(file_name, '.') > 0"
    )
    op.add_column(
        "recording_schedules",
        sa.Column("file_type", sa.String(length=16), nullable=False, server_default="ts"),
    )
    preserve_recording_schedule_links()
    with op.batch_alter_table("recording_schedules") as batch_op:
        batch_op.drop_constraint(
            "uq_recording_schedules_recurrence_date",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_recording_schedules_recurrence_start",
            ["recurrence_id", "starts_at"],
        )
    restore_recording_schedule_links()
    op.add_column(
        "recurring_schedules",
        sa.Column("file_type", sa.String(length=16), nullable=False, server_default="ts"),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column(
            "recurrence_type",
            sa.String(length=24),
            nullable=False,
            server_default="weekly",
        ),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column(
            "interval_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column("month_day", sa.Integer(), nullable=True),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column("month_week", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recurring_schedules", "month_week")
    op.drop_column("recurring_schedules", "month_day")
    op.drop_column("recurring_schedules", "recurrence_type")
    op.drop_column("recurring_schedules", "interval_count")
    op.drop_column("recurring_schedules", "file_type")
    preserve_recording_schedule_links()
    with op.batch_alter_table("recording_schedules") as batch_op:
        batch_op.drop_constraint(
            "uq_recording_schedules_recurrence_start",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_recording_schedules_recurrence_date",
            ["recurrence_id", "occurrence_date"],
        )
    restore_recording_schedule_links()
    op.drop_column("recording_schedules", "file_type")
    op.drop_column("recordings", "file_type")
    op.drop_column("streams", "preferred_file_type")
