"""Allow parallel recordings and add configurable recording storage.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("storage_directory", sa.String(length=4096), nullable=True),
    )
    op.create_table(
        "storage_configuration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recording_directory", sa.String(length=4096), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.drop_index("ix_streams_is_active", table_name="streams")
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_column("is_active")


def downgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    op.create_index("ix_streams_is_active", "streams", ["is_active"])
    op.drop_table("storage_configuration")
    op.drop_column("recordings", "storage_directory")
