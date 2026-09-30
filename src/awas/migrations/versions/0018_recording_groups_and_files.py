"""Group recorder attempts and persist every produced file.

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("group_key", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE recordings SET group_key = CASE "
        "WHEN schedule_id IS NOT NULL THEN 'schedule-' || schedule_id "
        "ELSE 'recording-' || id END"
    )
    with op.batch_alter_table("recordings") as batch_op:
        batch_op.alter_column("group_key", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_recordings_group_key", "recordings", ["group_key"])

    op.create_table(
        "recording_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_directory", sa.String(length=4096), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("file_deleted_at", sa.DateTime(), nullable=True),
        sa.Column("file_delete_reason", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "storage_directory",
            "file_name",
            name="uq_recording_files_storage_name",
        ),
    )
    op.create_index(
        "ix_recording_files_recording_id",
        "recording_files",
        ["recording_id"],
    )
    op.execute(
        "INSERT INTO recording_files "
        "(recording_id, file_name, storage_directory, file_size_bytes, discovered_at, "
        "updated_at, file_deleted_at, file_delete_reason) "
        "SELECT id, file_name, storage_directory, file_size_bytes, started_at, "
        "COALESCE(ended_at, started_at), file_deleted_at, file_delete_reason "
        "FROM recordings"
    )


def downgrade() -> None:
    op.drop_index("ix_recording_files_recording_id", table_name="recording_files")
    op.drop_table("recording_files")
    op.drop_index("ix_recordings_group_key", table_name="recordings")
    op.drop_column("recordings", "group_key")
