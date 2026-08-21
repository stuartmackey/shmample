import asyncio
from pathlib import Path

import pytest

from shmample import audio
from shmample.audio import NoPlayerFoundError, Previewer, build_play_command


# --- build_play_command: pure function, no subprocess involved ---

def _make_which(available: set[str]):
    return lambda name: f"/usr/bin/{name}" if name in available else None


def test_linux_prefers_paplay_when_available(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "linux")
    monkeypatch.setattr(audio.shutil, "which", _make_which({"paplay", "mpv"}))
    assert build_play_command(Path("kick.wav")) == ["paplay", "kick.wav"]


def test_linux_falls_back_through_the_player_list(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "linux")
    monkeypatch.setattr(audio.shutil, "which", _make_which({"mpv"}))
    assert build_play_command(Path("kick.wav")) == ["mpv", "--no-video", "--really-quiet", "kick.wav"]


def test_linux_ffplay_gets_quiet_flags(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "linux")
    monkeypatch.setattr(audio.shutil, "which", _make_which({"ffplay"}))
    assert build_play_command(Path("kick.wav")) == [
        "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "kick.wav",
    ]


def test_linux_no_player_found_returns_none(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "linux")
    monkeypatch.setattr(audio.shutil, "which", _make_which(set()))
    assert build_play_command(Path("kick.wav")) is None


def test_macos_uses_afplay_when_available(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "darwin")
    monkeypatch.setattr(audio.shutil, "which", _make_which({"afplay"}))
    assert build_play_command(Path("kick.wav")) == ["afplay", "kick.wav"]


def test_macos_no_afplay_returns_none(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "darwin")
    monkeypatch.setattr(audio.shutil, "which", _make_which(set()))
    assert build_play_command(Path("kick.wav")) is None


# --- Previewer: process lifecycle, with a controllable fake process ---

class _ControllableFakeProcess:
    """Unlike conftest's _InstantFakeProcess, this one stays "running"
    (wait() blocks) until explicitly finished or killed - needed to prove
    kill-on-replace actually interrupts a still-running preview, not just
    a fresh empty one."""

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.killed = False
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self._done.set()

    def finish(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self._done.set()


@pytest.fixture
def fake_processes(monkeypatch):
    """Patches asyncio.create_subprocess_exec to hand out
    _ControllableFakeProcess instances, in order, collected in a list the
    test can inspect/drive."""
    created: list[_ControllableFakeProcess] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        proc = _ControllableFakeProcess()
        created.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(audio, "build_play_command", lambda path: ["fake-player", str(path)])
    return created


async def test_play_runs_to_completion_when_nothing_else_is_playing(fake_processes):
    previewer = Previewer()
    task = asyncio.create_task(previewer.play(Path("kick.wav")))
    await asyncio.sleep(0)  # let the worker reach `await proc.wait()`
    fake_processes[0].finish()
    await task
    assert not fake_processes[0].killed


async def test_starting_a_new_preview_kills_the_one_in_progress(fake_processes):
    # play() doesn't return until its process finishes/is killed, so both
    # calls here run as background tasks - awaiting the second directly
    # would just block forever on a process nothing ever finishes.
    previewer = Previewer()
    first = asyncio.create_task(previewer.play(Path("kick.wav")))
    await asyncio.sleep(0)  # first process is now "playing"

    second = asyncio.create_task(previewer.play(Path("snare.wav")))
    await asyncio.sleep(0)  # second call's stop() has now killed the first process

    assert len(fake_processes) == 2
    assert fake_processes[0].killed
    assert not fake_processes[1].killed

    fake_processes[1].finish()
    await first
    await second


async def test_stop_with_nothing_playing_is_a_no_op(fake_processes):
    previewer = Previewer()
    await previewer.stop()
    assert fake_processes == []


async def test_no_player_found_raises(monkeypatch):
    monkeypatch.setattr(audio, "build_play_command", lambda path: None)
    previewer = Previewer()
    with pytest.raises(NoPlayerFoundError):
        await previewer.play(Path("kick.wav"))
