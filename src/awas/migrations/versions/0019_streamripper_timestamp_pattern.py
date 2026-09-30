"""Use a fresh streamripper timestamp for every produced file.

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


STREAMRIPPER_ARGUMENTS_3_0_5 = (
    "{url} -a {output_base} -A --quiet -u winamp"
)
STREAMRIPPER_ARGUMENTS_3_0_6 = (
    "{url} -a {output_base}_%D -A --quiet -u winamp"
)


def _replace_default_arguments(old_arguments: str, new_arguments: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE recorder_settings "
            "SET arguments = :new_arguments, updated_at = CURRENT_TIMESTAMP "
            "WHERE recorder = 'streamripper' AND arguments = :old_arguments"
        ),
        {
            "old_arguments": old_arguments,
            "new_arguments": new_arguments,
        },
    )


def upgrade() -> None:
    _replace_default_arguments(
        STREAMRIPPER_ARGUMENTS_3_0_5,
        STREAMRIPPER_ARGUMENTS_3_0_6,
    )


def downgrade() -> None:
    _replace_default_arguments(
        STREAMRIPPER_ARGUMENTS_3_0_6,
        STREAMRIPPER_ARGUMENTS_3_0_5,
    )
