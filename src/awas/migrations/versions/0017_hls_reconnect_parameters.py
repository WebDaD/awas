"""Remove EOF reconnect from ffmpeg HLS defaults.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


FFMPEG_ARGUMENTS_3_0_1 = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-sn -dn -c copy {output}"
)
FFMPEG_ARGUMENTS_3_0_2 = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-sn -dn -c copy {output}"
)
FFMPEG_ALL_ARGUMENTS_3_0_1 = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-map 0 -c copy {output}"
)
FFMPEG_ALL_ARGUMENTS_3_0_2 = (
    "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
    "-reconnect 1 -reconnect_on_network_error 1 "
    "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
    "-map 0 -c copy {output}"
)


def _replace_default_arguments(
    recorder: str,
    old_arguments: str,
    new_arguments: str,
) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE recorder_settings "
            "SET arguments = :new_arguments, updated_at = CURRENT_TIMESTAMP "
            "WHERE recorder = :recorder AND arguments = :old_arguments"
        ),
        {
            "recorder": recorder,
            "old_arguments": old_arguments,
            "new_arguments": new_arguments,
        },
    )


def upgrade() -> None:
    _replace_default_arguments("ffmpeg", FFMPEG_ARGUMENTS_3_0_1, FFMPEG_ARGUMENTS_3_0_2)
    _replace_default_arguments(
        "ffmpeg-all",
        FFMPEG_ALL_ARGUMENTS_3_0_1,
        FFMPEG_ALL_ARGUMENTS_3_0_2,
    )


def downgrade() -> None:
    _replace_default_arguments("ffmpeg", FFMPEG_ARGUMENTS_3_0_2, FFMPEG_ARGUMENTS_3_0_1)
    _replace_default_arguments(
        "ffmpeg-all",
        FFMPEG_ALL_ARGUMENTS_3_0_2,
        FFMPEG_ALL_ARGUMENTS_3_0_1,
    )
