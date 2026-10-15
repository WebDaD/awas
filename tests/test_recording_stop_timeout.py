import signal
import sys
import time
from contextlib import suppress
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from awas.models import AuditLog, Recording, RecordingSchedule, Stream
from awas.models.auth import utc_now
from awas.services.recorders import RECORDER_CHOICES
from tests.test_recordings import wait_for_status


@pytest.fixture
def recorder_factory(app, admin, tmp_path, monkeypatch):
    executable = tmp_path / "test-recorder.py"
    executable.write_text(
        """import pathlib
import signal
import sys
import time

output = pathlib.Path(sys.argv[1])
running = True

def stop(*_):
    global running
    running = False

signal.signal(signal.SIGTERM, signal.SIG_IGN if 'stubborn' in output.name else stop)
with output.open('wb') as target:
    target.write(b'AWAS-stop-test')
    target.flush()
    while running:
        target.write(b'.')
        target.flush()
        time.sleep(0.02)
""",
        encoding="utf-8",
    )

    def build_command(*_args, output_path, **_kwargs):
        return [sys.executable, str(executable), str(output_path)]

    monkeypatch.setattr("awas.services.recording.build_recorder_command", build_command)
    manager = app.state.recording_manager
    with app.state.session_factory() as db:
        stream = Stream(
            name="Stop timeout stream",
            stream_url="http://radio.example/stop-timeout",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.commit()
        stream_id = stream.id

    processes = []

    def start(*, recorder="ffmpeg", stubborn=True, planned=False):
        with app.state.session_factory() as db:
            stream = db.get(Stream, stream_id)
            schedule_id = None
            if planned:
                now = utc_now()
                schedule = RecordingSchedule(
                    stream_id=stream.id,
                    title="Stop timeout schedule",
                    recorder=recorder,
                    file_type="mp3",
                    starts_at=now - timedelta(minutes=1),
                    ends_at=now + timedelta(minutes=5),
                    status="running",
                    created_by_id=admin.id,
                )
                db.add(schedule)
                db.flush()
                schedule_id = schedule.id
            recording = manager.start_recording(
                db,
                stream=stream,
                actor=admin,
                ip_address="127.0.0.1",
                schedule_id=schedule_id,
                recorder=recorder,
                file_name_base="stubborn" if stubborn else "cooperative",
            )
            running = manager._running[recording.id]
            processes.append(running)
            path = manager.output_path(recording)
            deadline = time.monotonic() + 3
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert path.exists(), "Recorder did not install its signal handler"
            return recording.id, schedule_id, running

    yield start

    for running in processes:
        if running.process.poll() is None:
            with suppress(ProcessLookupError):
                manager._kill_process_group(running.process)
    for running in processes:
        running.thread.join(timeout=3)


def request_stop(app, admin, recording_id, schedule_id, stop_kind):
    if stop_kind == "schedule":
        with app.state.session_factory() as db:
            db.get(RecordingSchedule, schedule_id).ends_at = utc_now() - timedelta(seconds=1)
            db.commit()
        app.state.recording_scheduler.run_due()
    elif stop_kind == "manual_schedule":
        app.state.recording_scheduler.stop_schedule(
            schedule_id,
            actor=admin,
            ip_address="127.0.0.1",
        )
    else:
        with app.state.session_factory() as db:
            app.state.recording_manager.stop_recording(
                db,
                recording=db.get(Recording, recording_id),
                actor=admin,
                ip_address="127.0.0.1",
            )


@pytest.mark.parametrize("recorder", [key for key, _ in RECORDER_CHOICES])
@pytest.mark.parametrize("stop_kind", ["manual", "manual_schedule", "schedule"])
def test_unresponsive_recorder_is_killed_without_stopping_parallel_recordings(
    app, admin, recorder_factory, monkeypatch, recorder, stop_kind
):
    monkeypatch.setattr("awas.services.recording.RECORDING_STOP_TIMEOUT_SECONDS", 0.2)
    recording_id, schedule_id, running = recorder_factory(
        recorder=recorder,
        planned=stop_kind != "manual",
    )
    control_id, _, control = recorder_factory(stubborn=False)

    request_stop(app, admin, recording_id, schedule_id, stop_kind)

    assert running.process.poll() is None
    recording = wait_for_status(app, recording_id, "completed")
    assert running.process.returncode == -signal.SIGKILL
    assert recording.ended_at is not None
    assert recording.file_size_bytes > 0
    assert control.process.poll() is None
    with app.state.session_factory() as db:
        assert db.get(Recording, control_id).status == "recording"

    if schedule_id is not None:
        app.state.recording_scheduler.run_due(utc_now() + timedelta(minutes=1))
        with app.state.session_factory() as db:
            assert db.get(RecordingSchedule, schedule_id).status == "completed"
            assert db.scalar(
                select(func.count(Recording.id)).where(Recording.schedule_id == schedule_id)
            ) == 1


def test_graceful_exit_cancels_force_stop_and_preserves_parallel_recording(
    app, admin, recorder_factory, monkeypatch
):
    monkeypatch.setattr("awas.services.recording.RECORDING_STOP_TIMEOUT_SECONDS", 0.2)
    recording_id, _, running = recorder_factory(stubborn=False)
    control_id, _, control = recorder_factory(stubborn=False)
    killed = []
    real_kill = app.state.recording_manager._kill_process_group

    def record_kill(process):
        killed.append(process.pid)
        real_kill(process)

    monkeypatch.setattr(app.state.recording_manager, "_kill_process_group", record_kill)
    request_stop(app, admin, recording_id, None, "manual")
    wait_for_status(app, recording_id, "completed")
    running.thread.join(timeout=1)
    running.stop_timer.join(timeout=1)

    assert running.process.returncode == 0
    assert not running.stop_timer.is_alive()
    app.state.recording_manager._force_stop_recording(recording_id, running.process)
    app.state.recording_manager._force_stop_recording(control_id, running.process)
    assert killed == []
    assert control.process.poll() is None


def test_repeated_stop_does_not_extend_the_deadline(app, admin, recorder_factory, monkeypatch):
    monkeypatch.setattr("awas.services.recording.RECORDING_STOP_TIMEOUT_SECONDS", 0.2)
    recording_id, _, running = recorder_factory()

    request_stop(app, admin, recording_id, None, "manual")
    first_timer = running.stop_timer
    request_stop(app, admin, recording_id, None, "manual")

    assert running.stop_timer is first_timer
    wait_for_status(app, recording_id, "completed")
    assert running.process.returncode == -signal.SIGKILL


def test_production_deadline_allows_sixty_seconds_for_manual_and_scheduled_stops(
    app, admin, recorder_factory
):
    manual_id, _, manual = recorder_factory()
    planned_id, schedule_id, planned = recorder_factory(planned=True)
    _, _, control = recorder_factory(stubborn=False)

    started = time.monotonic()
    request_stop(app, admin, manual_id, None, "manual")
    request_stop(app, admin, planned_id, schedule_id, "schedule")

    assert manual.stop_timer.interval == 60
    assert planned.stop_timer.interval == 60
    while (remaining := started + 59 - time.monotonic()) > 0:
        assert manual.process.poll() is None
        assert planned.process.poll() is None
        assert control.process.poll() is None
        time.sleep(min(0.1, remaining))

    deadline = started + 65
    while time.monotonic() < deadline:
        if manual.process.poll() is not None and planned.process.poll() is not None:
            break
        time.sleep(0.02)

    assert time.monotonic() - started >= 60
    for recording_id, running in ((manual_id, manual), (planned_id, planned)):
        wait_for_status(app, recording_id, "completed")
        assert running.process.returncode == -signal.SIGKILL
        with app.state.session_factory() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "recording.completed",
                    AuditLog.target_id == recording_id,
                )
            )
            assert audit is not None
    assert control.process.poll() is None
