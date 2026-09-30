from pathlib import Path

import pytest

from awas.services.recorders import (
    FILE_TYPE_CHOICES,
    RECORDER_CHOICES,
    RecorderInputError,
    RecorderUnavailableError,
    build_recorder_command,
    file_type_extension,
    recorder_extension,
    validate_argument_template,
    validate_file_type,
    validate_recorder,
    validate_recorder_url,
)

EXPECTED_RECORDERS = (
    ("streamripper", "streamripper"),
    ("ffmpeg", "ffmpeg"),
    ("ffmpeg-all", "ffmpeg-all"),
    ("streamlink-http", "streamlink-http"),
    ("streamlink-hls-dash", "streamlink-hls-dash"),
    ("vlc", "vlc"),
    ("mpv", "mpv"),
    ("mplayer", "mplayer"),
)


@pytest.fixture
def installed_recorders(monkeypatch):
    monkeypatch.setattr(
        "awas.services.recorders.shutil.which",
        lambda executable: f"/usr/bin/{executable}",
    )


def test_recorder_choices_match_supported_recorders() -> None:
    assert RECORDER_CHOICES == EXPECTED_RECORDERS
    assert validate_recorder(" vlc ") == "vlc"
    with pytest.raises(RecorderInputError, match="ungültig"):
        validate_recorder("unknown")


def test_file_types_match_previous_awas_and_are_validated() -> None:
    assert tuple(value for value, _ in FILE_TYPE_CHOICES) == (
        "ts",
        "mp3",
        "mp4",
        "ogg",
        "wma",
        "wmv",
        "mpg",
        "flac",
    )
    assert validate_file_type(" .MP3 ") == "mp3"
    assert file_type_extension("flac") == ".flac"
    with pytest.raises(RecorderInputError, match="Dateityp"):
        validate_file_type("mka")


@pytest.mark.parametrize(
    ("recorder", "extension", "executable"),
    (
        ("streamripper", ".stream", "/usr/bin/streamripper"),
        ("ffmpeg", ".mka", "/usr/bin/ffmpeg"),
        ("ffmpeg-all", ".mkv", "/usr/bin/ffmpeg"),
        ("streamlink-http", ".stream", "/usr/bin/streamlink"),
        ("streamlink-hls-dash", ".ts", "/usr/bin/streamlink"),
        ("vlc", ".mkv", "/usr/bin/cvlc"),
        ("mpv", ".mkv", "/usr/bin/mpv"),
        ("mplayer", ".stream", "/usr/bin/mplayer"),
    ),
)
def test_each_recorder_builds_a_direct_command(
    recorder: str,
    extension: str,
    executable: str,
    installed_recorders,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / f"capture{extension}"
    stream_url = (
        "http://radio.example/live"
        if recorder == "streamripper"
        else "https://radio.example/live"
    )
    command = build_recorder_command(
        recorder,
        stream_url=stream_url,
        stream_name="Test Stream",
        output_path=output_path,
    )

    assert recorder_extension(recorder) == extension
    assert command[0] == executable
    if recorder == "streamripper":
        assert str(output_path.with_name(f"%D_{output_path.name}")) in command
    else:
        assert any(str(output_path) in argument for argument in command)
    assert any(stream_url in argument for argument in command)


def test_recorder_specific_modes_are_kept_separate(
    installed_recorders,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "capture.mkv"
    ffmpeg = build_recorder_command(
        "ffmpeg",
        stream_url="https://radio.example/live",
        stream_name="Radio",
        output_path=output_path,
    )
    ffmpeg_all = build_recorder_command(
        "ffmpeg-all",
        stream_url="https://radio.example/live",
        stream_name="Radio",
        output_path=output_path,
    )
    streamlink_http = build_recorder_command(
        "streamlink-http",
        stream_url="https://radio.example/live",
        stream_name="Radio",
        output_path=output_path,
    )
    assert "-map" not in ffmpeg
    assert "-vn" not in ffmpeg
    assert "-sn" in ffmpeg
    assert "-dn" in ffmpeg
    assert "-reconnect_at_eof" not in ffmpeg
    assert "-reconnect_at_eof" not in ffmpeg_all
    assert "-reconnect_on_network_error" in ffmpeg
    assert "-reconnect_on_network_error" in ffmpeg_all
    assert _arguments_after(ffmpeg, "-c")[:1] == ["copy"]
    assert _arguments_after(ffmpeg_all, "-map")[:1] == ["0"]
    assert "-y" not in ffmpeg
    assert "-metadata" not in ffmpeg
    assert "-y" not in ffmpeg_all
    assert "-metadata" not in ffmpeg_all
    assert "httpstream://https://radio.example/live" in streamlink_http


def test_selected_file_type_controls_output_and_ffmpeg_uses_suffix(
    installed_recorders,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "capture.flac"
    ffmpeg = build_recorder_command(
        "ffmpeg",
        stream_url="https://radio.example/live",
        stream_name="Radio",
        output_path=output_path,
        file_type="flac",
    )
    streamripper = build_recorder_command(
        "streamripper",
        stream_url="http://radio.example/live",
        stream_name="Radio",
        output_path=output_path,
        file_type="flac",
    )

    assert str(output_path) in ffmpeg
    assert "-f" not in ffmpeg
    dynamic_output = output_path.with_name(f"%D_{output_path.stem}").with_suffix("")
    assert str(dynamic_output) in streamripper
    assert str(output_path) not in streamripper


def test_streamripper_replaces_leading_file_timestamp_with_dynamic_timestamp(
    installed_recorders,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "2026-09-30_14-30-00_radio_abc123.mp3"

    command = build_recorder_command(
        "streamripper",
        stream_url="http://radio.example/live",
        output_path=output_path,
        file_type="mp3",
    )

    output_argument = command[command.index("-a") + 1]
    assert output_argument == str(tmp_path / "%D_radio_abc123")
    assert "2026-09-30_14-30-00" not in output_argument


def test_streamripper_rejects_https() -> None:
    with pytest.raises(RecorderInputError, match="keine Stream-Adresse mit https"):
        validate_recorder_url("streamripper", "https://radio.example/live")
    validate_recorder_url("streamripper", "http://radio.example/live")
    validate_recorder_url("ffmpeg", "https://radio.example/live")


def test_argument_templates_require_url_and_output_placeholders() -> None:
    assert (
        validate_argument_template("ffmpeg", "-i {url} -c copy {output}")
        == "-i {url} -c copy {output}"
    )
    with pytest.raises(RecorderInputError, match=r"\{url\}"):
        validate_argument_template("ffmpeg", "-i test -c copy {output}")
    with pytest.raises(RecorderInputError, match=r"\{output_base\}"):
        validate_argument_template("streamripper", "{url} -a {output}")
    with pytest.raises(RecorderInputError, match="ungültigen Platzhalter"):
        validate_argument_template("ffmpeg", "-i {url} {unknown} {output}")


def test_custom_argument_template_is_used(installed_recorders, tmp_path: Path) -> None:
    output_path = tmp_path / "capture.mp3"
    command = build_recorder_command(
        "ffmpeg",
        stream_url="https://radio.example/live",
        output_path=output_path,
        argument_template="-i {url} -c copy {output}",
    )
    assert command == [
        "/usr/bin/ffmpeg",
        "-i",
        "https://radio.example/live",
        "-c",
        "copy",
        str(output_path),
    ]


def test_missing_recorder_binary_is_reported(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("awas.services.recorders.shutil.which", lambda _: None)
    with pytest.raises(RecorderUnavailableError, match="nicht installiert"):
        build_recorder_command(
            "mpv",
            stream_url="https://radio.example/live",
            stream_name="Radio",
            output_path=tmp_path / "capture.mkv",
        )


def _arguments_after(command: list[str], option: str) -> list[str]:
    return command[command.index(option) + 1 :]
