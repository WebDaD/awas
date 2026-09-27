"""Select the best ffmpeg streams and remove yt-dlp recorders.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


OLD_FFMPEG_ARGUMENTS = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-map 0:a:0 -vn -c:a copy {output}"
)
NEW_FFMPEG_ARGUMENTS = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-sn -dn -c copy {output}"
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE recorder_settings "
            "SET arguments = :new_arguments, updated_at = CURRENT_TIMESTAMP "
            "WHERE recorder = 'ffmpeg' AND arguments = :old_arguments"
        ),
        {
            "new_arguments": NEW_FFMPEG_ARGUMENTS,
            "old_arguments": OLD_FFMPEG_ARGUMENTS,
        },
    )
    connection.execute(
        sa.text(
            "UPDATE streams "
            "SET preferred_recorder = 'ffmpeg' "
            "WHERE preferred_recorder IN ('yt-dlp', 'yt-dlp-ffmpeg')"
        )
    )

    for table_name, condition in (
        ("recording_schedules", "AND status IN ('scheduled', 'running')"),
        ("recurring_schedules", ""),
    ):
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET recorder = 'ffmpeg' "
                "WHERE recorder IN ('yt-dlp', 'yt-dlp-ffmpeg') "
                f"{condition}"
            )
        )
    connection.execute(
        sa.text(
            "DELETE FROM recorder_settings "
            "WHERE recorder IN ('yt-dlp', 'yt-dlp-ffmpeg')"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE recorder_settings "
            "SET arguments = :old_arguments, updated_at = CURRENT_TIMESTAMP "
            "WHERE recorder = 'ffmpeg' AND arguments = :new_arguments"
        ),
        {
            "old_arguments": OLD_FFMPEG_ARGUMENTS,
            "new_arguments": NEW_FFMPEG_ARGUMENTS,
        },
    )
