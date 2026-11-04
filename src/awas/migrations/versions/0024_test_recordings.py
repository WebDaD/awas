"""Identify immediate test recordings.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("recordings")}
    if "is_test" not in columns:
        op.add_column(
            "recordings",
            sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    with op.batch_alter_table("recordings") as batch_op:
        batch_op.drop_column("is_test")
