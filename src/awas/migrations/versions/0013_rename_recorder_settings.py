"""Rename recorder settings.

Revision ID: 0013
Revises: 0012
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("recorder_tool_settings", "recorder_settings")


def downgrade() -> None:
    op.rename_table("recorder_settings", "recorder_tool_settings")
