"""Store an independent stream snapshot in every recording schedule.

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recording_schedules",
        sa.Column(
            "stream_name",
            sa.String(length=128),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "recording_schedules",
        sa.Column(
            "stream_url",
            sa.String(length=2048),
            nullable=False,
            server_default="",
        ),
    )
    op.execute(
        "UPDATE recording_schedules SET stream_name = "
        "(SELECT streams.name FROM streams "
        "WHERE streams.id = recording_schedules.stream_id) "
        "WHERE stream_id IS NOT NULL"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_name = "
        "(SELECT recordings.stream_name FROM recordings "
        "WHERE recordings.schedule_id = recording_schedules.id "
        "ORDER BY recordings.started_at, recordings.id LIMIT 1) "
        "WHERE stream_name = ''"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_name = 'Gelöschter Stream' "
        "WHERE stream_name = ''"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_url = "
        "(SELECT streams.stream_url FROM streams "
        "WHERE streams.id = recording_schedules.stream_id) "
        "WHERE stream_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("recording_schedules", "stream_url")
    op.drop_column("recording_schedules", "stream_name")
