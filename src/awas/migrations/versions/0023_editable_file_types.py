"""Store the administrator-configured file type list.

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_type_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_types", sa.String(length=2048), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("id = 1", name="ck_file_type_settings_singleton"),
    )
    op.execute(
        "INSERT INTO file_type_settings (id, file_types, updated_at) "
        "VALUES (1, 'ts, mp3, mp4, ogg, wma, wmv, mpg, flac', CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_table("file_type_settings")
