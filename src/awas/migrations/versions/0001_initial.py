"""Create the AWAS 3 baseline.

Revision ID: 0001
Revises:
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The baseline intentionally contains no business tables. User, stream,
    # schedule and recording tables arrive in their respective milestones.
    pass


def downgrade() -> None:
    pass

