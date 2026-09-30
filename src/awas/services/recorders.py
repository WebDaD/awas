from __future__ import annotations

import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from urllib.parse import urlsplit


class RecorderInputError(ValueError):
    pass


class RecorderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecorderProfile:
    key: str
    label: str
    executable: str
    default_arguments: str
    output_placeholder: str = "output"


RECORDER_PROFILES = (
    RecorderProfile(
        "streamripper",
        "streamripper",
        "streamripper",
        "{url} -a {output_base} -A --quiet -u winamp",
        "output_base",
    ),
    RecorderProfile(
        "ffmpeg",
        "ffmpeg",
        "ffmpeg",
        "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
        "-reconnect 1 -reconnect_on_network_error 1 "
        "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
        "-sn -dn -c copy {output}",
    ),
    RecorderProfile(
        "ffmpeg-all",
        "ffmpeg-all",
        "ffmpeg",
        "-nostdin -hide_banner -loglevel warning -rw_timeout 15000000 "
        "-reconnect 1 -reconnect_on_network_error 1 "
        "-reconnect_streamed 1 -reconnect_delay_max 5 -i {url} "
        "-map 0 -c copy {output}",
    ),
    RecorderProfile(
        "streamlink-http",
        "streamlink-http",
        "streamlink",
        "--loglevel warning --force --quiet --output {output} --retry-streams 3 "
        "--retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 "
        "--stream-segment-timeout 60.0 --stream-timeout 120.0 "
        "httpstream://{url} best",
    ),
    RecorderProfile(
        "streamlink-hls-dash",
        "streamlink-hls-dash",
        "streamlink",
        "--loglevel warning --force --quiet --output {output} --retry-streams 3 "
        "--retry-max 9999 --retry-open 9999 --stream-segment-attempts 9999 "
        "--stream-segment-timeout 60.0 --stream-timeout 120.0 {url} best",
    ),
    RecorderProfile(
        "vlc",
        "vlc",
        "cvlc",
        "{url} --sout file:{output} --sout-keep --http-reconnect "
        "--network-caching=10000 --rtsp-tcp --no-sout-rtp-sap "
        "--no-sout-standard-sap",
    ),
    RecorderProfile(
        "mpv",
        "mpv",
        "mpv",
        "--no-config --really-quiet --no-terminal --vo=null --ao=null "
        "--stream-record={output} -- {url}",
    ),
    RecorderProfile(
        "mplayer",
        "mplayer",
        "mplayer",
        "-really-quiet -nolirc -vo null -ao null -dumpstream -dumpfile {output} "
        "{url} -cache 8192 -cache-min 50 -forceidx",
    ),
)

RECORDER_BY_KEY = {profile.key: profile for profile in RECORDER_PROFILES}
RECORDER_CHOICES = tuple((profile.key, profile.label) for profile in RECORDER_PROFILES)
DEFAULT_RECORDER = "streamripper"

# Keep the order used by the previous AWAS release. The selected value is the
# output suffix passed to the recorder, not a request to transcode the stream.
FILE_TYPE_CHOICES = tuple(
    (value, value)
    for value in (
        "ts",
        "mp3",
        "mp4",
        "ogg",
        "wma",
        "wmv",
        "mpg",
        "flac",
    )
)
FILE_TYPES = frozenset(value for value, _ in FILE_TYPE_CHOICES)
DEFAULT_FILE_TYPE = "ts"
LEGACY_RECORDER_EXTENSIONS = {
    "streamripper": ".stream",
    "ffmpeg": ".mka",
    "ffmpeg-all": ".mkv",
    "streamlink-http": ".stream",
    "streamlink-hls-dash": ".ts",
    "vlc": ".mkv",
    "mpv": ".mkv",
    "mplayer": ".stream",
}
ARGUMENT_PLACEHOLDERS = frozenset(("url", "output", "output_base"))
FILE_TIMESTAMP_PREFIX = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_"
)


def validate_recorder(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in RECORDER_BY_KEY:
        raise RecorderInputError("Der ausgewählte Rekorder ist ungültig.")
    return normalized


def recorder_label(value: str) -> str:
    profile = RECORDER_BY_KEY.get(value)
    return profile.label if profile else value


def validate_file_type(value: str) -> str:
    normalized = value.strip().lower().lstrip(".")
    if normalized not in FILE_TYPES:
        raise RecorderInputError("Der ausgewählte Dateityp ist ungültig.")
    return normalized


def file_type_extension(value: str) -> str:
    return f".{validate_file_type(value)}"


def recorder_extension(value: str) -> str:
    """Return the pre-0.10 default suffix for compatibility with integrations."""
    return LEGACY_RECORDER_EXTENSIONS[validate_recorder(value)]


def recorder_default_arguments(value: str) -> str:
    return RECORDER_BY_KEY[validate_recorder(value)].default_arguments


def validate_recorder_url(recorder: str, stream_url: str) -> None:
    normalized_recorder = validate_recorder(recorder)
    if (
        normalized_recorder == "streamripper"
        and urlsplit(stream_url.strip()).scheme.lower() == "https"
    ):
        raise RecorderInputError(
            "streamripper unterstützt keine Stream-Adresse mit https://. "
            "Bitte verwenden Sie eine http://-Adresse oder einen anderen Rekorder."
        )


def validate_argument_template(recorder: str, value: str) -> str:
    profile = RECORDER_BY_KEY[validate_recorder(recorder)]
    normalized = value.strip()
    if not normalized:
        raise RecorderInputError("Die Rekorderparameter dürfen nicht leer sein.")
    if len(normalized) > 4096:
        raise RecorderInputError(
            "Die Rekorderparameter dürfen höchstens 4096 Zeichen lang sein."
        )
    if "\x00" in normalized:
        raise RecorderInputError("Die Rekorderparameter enthalten ein ungültiges Zeichen.")
    try:
        arguments = shlex.split(normalized, posix=True)
    except ValueError as exc:
        raise RecorderInputError(
            "Die Rekorderparameter enthalten ungültige Anführungszeichen."
        ) from exc
    if not arguments:
        raise RecorderInputError("Die Rekorderparameter dürfen nicht leer sein.")

    placeholders: set[str] = set()
    try:
        for argument in arguments:
            for _, field_name, format_spec, conversion in Formatter().parse(argument):
                if field_name is None:
                    continue
                if (
                    field_name not in ARGUMENT_PLACEHOLDERS
                    or format_spec
                    or conversion is not None
                ):
                    raise RecorderInputError(
                        "Die Rekorderparameter enthalten einen ungültigen Platzhalter."
                    )
                placeholders.add(field_name)
    except ValueError as exc:
        raise RecorderInputError(
            "Die Rekorderparameter enthalten einen ungültigen Platzhalter."
        ) from exc

    if "url" not in placeholders:
        raise RecorderInputError("In den Rekorderparametern fehlt der Platzhalter {url}.")
    if profile.output_placeholder not in placeholders:
        raise RecorderInputError(
            "In den Rekorderparametern fehlt der Platzhalter "
            f"{{{profile.output_placeholder}}}."
        )
    return normalized


def build_recorder_command(
    recorder: str,
    *,
    stream_url: str,
    output_path: Path,
    file_type: str | None = None,
    argument_template: str | None = None,
    stream_name: str | None = None,
) -> list[str]:
    del stream_name  # Kept as a compatibility keyword for older integrations.
    profile = RECORDER_BY_KEY[validate_recorder(recorder)]
    validate_recorder_url(profile.key, stream_url)
    if file_type is not None:
        validate_file_type(file_type)
    executable = shutil.which(profile.executable)
    if executable is None:
        raise RecorderUnavailableError(
            f"Der Rekorder {profile.label} ist auf diesem System nicht installiert."
        )

    template = validate_argument_template(
        profile.key,
        argument_template if argument_template is not None else profile.default_arguments,
    )
    output_base = output_path.with_suffix("") if file_type else output_path
    if profile.key == "streamripper":
        dynamic_name = FILE_TIMESTAMP_PREFIX.sub("%D_", output_base.name, count=1)
        if dynamic_name == output_base.name:
            dynamic_name = f"%D_{dynamic_name}"
        output_base = output_base.with_name(dynamic_name)
    values = {
        "url": stream_url,
        "output": str(output_path),
        "output_base": str(output_base),
    }
    arguments = [argument.format_map(values) for argument in shlex.split(template, posix=True)]
    return [executable, *arguments]
