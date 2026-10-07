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
    # SQLite commits ALTER TABLE independently from the remaining migration.
    # Therefore a failed upgrade can leave these columns behind while the
    # Alembic revision still points to 0021. Make the migration restartable so
    # a corrected package can safely finish such an installation.
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("recording_schedules")
    }
    if "stream_name" not in columns:
        op.add_column(
            "recording_schedules",
            sa.Column(
                "stream_name",
                sa.String(length=128),
                nullable=False,
                server_default="",
            ),
        )
    if "stream_url" not in columns:
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
        "COALESCE((SELECT streams.name FROM streams "
        "WHERE streams.id = recording_schedules.stream_id), stream_name, '') "
        "WHERE stream_id IS NOT NULL"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_name = "
        "COALESCE((SELECT recordings.stream_name FROM recordings "
        "WHERE recordings.schedule_id = recording_schedules.id "
        "ORDER BY recordings.started_at, recordings.id LIMIT 1), "
        "'Gelöschter Stream') "
        "WHERE stream_name = ''"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_name = 'Gelöschter Stream' "
        "WHERE stream_name = ''"
    )
    op.execute(
        "UPDATE recording_schedules SET stream_url = "
        "COALESCE((SELECT streams.stream_url FROM streams "
        "WHERE streams.id = recording_schedules.stream_id), stream_url, '') "
        "WHERE stream_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("recording_schedules", "stream_url")
    op.drop_column("recording_schedules", "stream_name")
