"""Add recurring recording schedules.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

LINK_BACKUP_TABLE = "_awas_0006_recording_schedule_links"


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
    op.create_table(
        "recurring_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("weekday_mask", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.CheckConstraint(
            "weekday_mask BETWEEN 1 AND 127",
            name="ck_recurring_schedules_weekday_mask",
        ),
        sa.CheckConstraint(
            "start_minute BETWEEN 0 AND 1439",
            name="ck_recurring_schedules_start_minute",
        ),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 1 AND 1440",
            name="ck_recurring_schedules_duration",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_recurring_schedules_valid_range",
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_recurring_schedules_stream_id", "recurring_schedules", ["stream_id"]
    )
    op.create_index(
        "ix_recurring_schedules_is_active", "recurring_schedules", ["is_active"]
    )

    preserve_recording_schedule_links()
    with op.batch_alter_table("recording_schedules") as batch_op:
        batch_op.add_column(sa.Column("recurrence_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("occurrence_date", sa.Date(), nullable=True))
        batch_op.create_foreign_key(
            "fk_recording_schedules_recurrence_id",
            "recurring_schedules",
            ["recurrence_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_recording_schedules_recurrence_id", ["recurrence_id"])
        batch_op.create_unique_constraint(
            "uq_recording_schedules_recurrence_date",
            ["recurrence_id", "occurrence_date"],
        )
    restore_recording_schedule_links()


def downgrade() -> None:
    preserve_recording_schedule_links()
    with op.batch_alter_table("recording_schedules") as batch_op:
        batch_op.drop_constraint(
            "uq_recording_schedules_recurrence_date",
            type_="unique",
        )
        batch_op.drop_index("ix_recording_schedules_recurrence_id")
        batch_op.drop_constraint(
            "fk_recording_schedules_recurrence_id",
            type_="foreignkey",
        )
        batch_op.drop_column("occurrence_date")
        batch_op.drop_column("recurrence_id")
    restore_recording_schedule_links()

    op.drop_table("recurring_schedules")
