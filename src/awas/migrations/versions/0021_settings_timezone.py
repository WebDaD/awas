"""Add the application timezone setting.

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "storage_configuration",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="Europe/Berlin",
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("storage_configuration") as batch_op:
        batch_op.drop_column("timezone")
