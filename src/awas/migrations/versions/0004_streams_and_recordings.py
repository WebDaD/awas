"""Rename stations to streams and add manual recordings.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("stations", "streams")
    op.drop_index("ix_stations_name", table_name="streams")
    op.drop_index("ix_stations_is_active", table_name="streams")
    op.create_index("ix_streams_name", "streams", ["name"], unique=True)
    op.create_index("ix_streams_is_active", "streams", ["is_active"])
    op.execute("UPDATE audit_log SET action = REPLACE(action, 'station.', 'stream.') "
               "WHERE action LIKE 'station.%'")
    op.execute("UPDATE audit_log SET target_type = 'stream' WHERE target_type = 'station'")

    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="starting"),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()
        ),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("started_by_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('starting', 'recording', 'stopping', 'completed', 'failed', "
            "'interrupted')",
            name="ck_recordings_status",
        ),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("file_name", name="uq_recordings_file_name"),
    )
    op.create_index("ix_recordings_stream_id", "recordings", ["stream_id"])
    op.create_index("ix_recordings_status", "recordings", ["status"])
    op.create_index("ix_recordings_started_at", "recordings", ["started_at"])


def downgrade() -> None:
    op.drop_table("recordings")
    op.execute("UPDATE audit_log SET action = REPLACE(action, 'stream.', 'station.') "
               "WHERE action LIKE 'stream.%'")
    op.execute("UPDATE audit_log SET target_type = 'station' WHERE target_type = 'stream'")
    op.drop_index("ix_streams_name", table_name="streams")
    op.drop_index("ix_streams_is_active", table_name="streams")
    op.create_index("ix_stations_name", "streams", ["name"], unique=True)
    op.create_index("ix_stations_is_active", "streams", ["is_active"])
    op.rename_table("streams", "stations")
