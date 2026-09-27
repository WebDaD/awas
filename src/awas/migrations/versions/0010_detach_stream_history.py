"""Detach recordings and hidden planning history from deleted streams.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
RECORDING_LINKS = "_awas_0010_recording_schedule_links"
RECURRENCE_LINKS = "_awas_0010_schedule_recurrence_links"


def preserve_recording_schedule_links() -> None:
    op.execute(
        f"CREATE TEMPORARY TABLE {RECORDING_LINKS} "
        "(recording_id INTEGER PRIMARY KEY, schedule_id INTEGER NOT NULL)"
    )
    op.execute(
        f"INSERT INTO {RECORDING_LINKS} (recording_id, schedule_id) "
        "SELECT id, schedule_id FROM recordings WHERE schedule_id IS NOT NULL"
    )


def restore_recording_schedule_links() -> None:
    op.execute(
        "UPDATE recordings SET schedule_id = "
        f"(SELECT schedule_id FROM {RECORDING_LINKS} "
        f"WHERE recording_id = recordings.id) WHERE id IN "
        f"(SELECT recording_id FROM {RECORDING_LINKS})"
    )
    op.execute(f"DROP TABLE {RECORDING_LINKS}")


def preserve_schedule_recurrence_links() -> None:
    op.execute(
        f"CREATE TEMPORARY TABLE {RECURRENCE_LINKS} "
        "(schedule_id INTEGER PRIMARY KEY, recurrence_id INTEGER NOT NULL)"
    )
    op.execute(
        f"INSERT INTO {RECURRENCE_LINKS} (schedule_id, recurrence_id) "
        "SELECT id, recurrence_id FROM recording_schedules WHERE recurrence_id IS NOT NULL"
    )


def restore_schedule_recurrence_links() -> None:
    op.execute(
        "UPDATE recording_schedules SET recurrence_id = "
        f"(SELECT recurrence_id FROM {RECURRENCE_LINKS} "
        f"WHERE schedule_id = recording_schedules.id) WHERE id IN "
        f"(SELECT schedule_id FROM {RECURRENCE_LINKS})"
    )
    op.execute(f"DROP TABLE {RECURRENCE_LINKS}")


def upgrade() -> None:
    with op.batch_alter_table(
        "recordings", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recordings_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_recordings_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="SET NULL",
        )

    preserve_recording_schedule_links()
    with op.batch_alter_table(
        "recording_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recording_schedules_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_recording_schedules_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="SET NULL",
        )
    restore_recording_schedule_links()

    preserve_schedule_recurrence_links()
    with op.batch_alter_table(
        "recurring_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recurring_schedules_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.create_foreign_key(
            "fk_recurring_schedules_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="SET NULL",
        )
    restore_schedule_recurrence_links()


def downgrade() -> None:
    # A downgrade cannot recreate streams that have already been deleted.
    op.execute("DELETE FROM recordings WHERE stream_id IS NULL")
    op.execute("DELETE FROM recording_schedules WHERE stream_id IS NULL")
    op.execute("DELETE FROM recurring_schedules WHERE stream_id IS NULL")

    preserve_schedule_recurrence_links()
    with op.batch_alter_table(
        "recurring_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recurring_schedules_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_recurring_schedules_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    restore_schedule_recurrence_links()

    preserve_recording_schedule_links()
    with op.batch_alter_table(
        "recording_schedules", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recording_schedules_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_recording_schedules_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    restore_recording_schedule_links()

    with op.batch_alter_table(
        "recordings", naming_convention=NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_recordings_stream_id_streams",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "stream_id",
            existing_type=sa.Integer(),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_recordings_stream_id_streams",
            "streams",
            ["stream_id"],
            ["id"],
            ondelete="RESTRICT",
        )
