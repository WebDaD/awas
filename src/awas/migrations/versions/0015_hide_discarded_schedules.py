"""Hide discarded schedules from the schedule history.

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE recording_schedules SET is_hidden = 1 "
        "WHERE status = 'cancelled'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE recording_schedules SET is_hidden = 0 "
        "WHERE status = 'cancelled'"
    )
