"""Add configurable file-name bases and recorder tool settings.

Revision ID: 0011
Revises: 0010
"""

import re
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


TOOL_DEFAULTS = (
    (
        "streamripper",
        "{url} -a {output_base} -A --quiet -u winamp",
    ),
    (
        "ffmpeg",
        "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
        "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
        "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
        "-map 0:a:0 -vn -c:a copy {output}",
    ),
    (
        "ffmpeg-all",
        "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
        "-reconnect 1 -reconnect_at_eof 1 -reconnect_on_network_error 1 "
        "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
        "-map 0 -c copy {output}",
    ),
    (
        "streamlink-http",
        "--loglevel warning --force --quiet --output {output} --retry-streams 3 "
        "--retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 "
        "--stream-segment-timeout 60.0 --stream-timeout 120.0 "
        "httpstream://{url} best",
    ),
    (
        "streamlink-hls-dash",
        "--loglevel warning --force --quiet --output {output} --retry-streams 3 "
        "--retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 "
        "--stream-segment-timeout 60.0 --stream-timeout 120.0 {url} best",
    ),
    (
        "yt-dlp",
        "--no-playlist --no-part --force-overwrites --hls-use-mpegts "
        "--no-abort-on-error --socket-timeout 3600 --file-access-retries infinite "
        "--fragment-retries infinite --quiet --output {output} {url}",
    ),
    (
        "yt-dlp-ffmpeg",
        "--no-playlist --no-part --force-overwrites --hls-use-mpegts "
        "--no-abort-on-error --socket-timeout 3600 --file-access-retries infinite "
        "--fragment-retries infinite --quiet --output {output} "
        "--downloader ffmpeg {url}",
    ),
    (
        "vlc",
        "{url} --sout file:{output} --sout-keep --http-reconnect "
        "--network-caching=10000 --rtsp-tcp --no-sout-rtp-sap "
        "--no-sout-standard-sap",
    ),
    (
        "mpv",
        "--no-config --really-quiet --no-terminal --vo=null --ao=null "
        "--stream-record={output} -- {url}",
    ),
    (
        "mplayer",
        "-really-quiet -nolirc -vo null -ao null -dumpstream -dumpfile {output} "
        "{url} -cache 8192 -cache-min 50 -forceidx",
    ),
)


def _file_name_base(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:128] or "aufnahme"


def _populate_file_name_bases(table_name: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT id, title FROM {table_name}")).all()
    for row in rows:
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET file_name_base = :file_name_base WHERE id = :id"
            ),
            {"file_name_base": _file_name_base(row.title), "id": row.id},
        )


def upgrade() -> None:
    op.add_column(
        "recording_schedules",
        sa.Column(
            "file_name_base",
            sa.String(length=128),
            nullable=False,
            server_default="aufnahme",
        ),
    )
    op.add_column(
        "recurring_schedules",
        sa.Column(
            "file_name_base",
            sa.String(length=128),
            nullable=False,
            server_default="aufnahme",
        ),
    )
    _populate_file_name_bases("recording_schedules")
    _populate_file_name_bases("recurring_schedules")

    tool_settings = op.create_table(
        "recorder_tool_settings",
        sa.Column("recorder", sa.String(length=32), primary_key=True),
        sa.Column("arguments", sa.Text(), nullable=False),
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
    op.bulk_insert(
        tool_settings,
        [
            {"recorder": recorder, "arguments": arguments}
            for recorder, arguments in TOOL_DEFAULTS
        ],
    )


def downgrade() -> None:
    op.drop_table("recorder_tool_settings")
    op.drop_column("recurring_schedules", "file_name_base")
    op.drop_column("recording_schedules", "file_name_base")
