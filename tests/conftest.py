import asyncio

import pytest

from shmample import config_store, sample_store, settings


class _InstantFakeProcess:
    """A fake asyncio subprocess that's already finished - used as the
    default stand-in everywhere so no test in this suite ever spawns a
    real player/lsblk/udisksctl process, just by exercising the ordinary
    FileBrowser preview flow (Enter/p on a file) or device auto-mount
    check (ShmampleApp startup). communicate() returns empty output rather
    than raising, so any incidental subprocess call in an unrelated test
    degrades to "found nothing" instead of crashing."""

    def __init__(self) -> None:
        self.returncode = 0

    async def wait(self) -> int:
        return self.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    def kill(self) -> None:
        self.returncode = -9


@pytest.fixture(autouse=True)
def no_real_audio_playback(monkeypatch):
    async def _fake_create_subprocess_exec(*args, **kwargs):
        return _InstantFakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)


@pytest.fixture(autouse=True)
def no_real_config_directory(tmp_path, monkeypatch):
    """ShmampleApp/MainColumn/ConfigList all resolve a None configurations_dir
    to config_store.DEFAULT_CONFIGURATIONS_DIR at call time (not a mutable
    default parameter) specifically so this monkeypatch works - without
    it, every test that doesn't pass configurations_dir explicitly would
    read/write the real ~/.config/shmample/configurations."""
    monkeypatch.setattr(config_store, "DEFAULT_CONFIGURATIONS_DIR", tmp_path / "configurations")


@pytest.fixture(autouse=True)
def no_real_settings_file(tmp_path, monkeypatch):
    """FileBrowser resolves a None settings_path to settings.SETTINGS_PATH
    at call time (same reasoning as DEFAULT_CONFIGURATIONS_DIR above) -
    without this, any test exercising Shift+A/Shift+D would read/write
    the real ~/.config/shmample/settings.json."""
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")


@pytest.fixture(autouse=True)
def no_real_sample_db(tmp_path, monkeypatch):
    """PreviewInfo resolves a None db_path to sample_store.DEFAULT_DB_PATH
    at call time (same reasoning as no_real_settings_file above) - without
    this, any test that highlights a file would read/write the real
    ~/.config/shmample/shmample.db."""
    monkeypatch.setattr(sample_store, "DEFAULT_DB_PATH", tmp_path / "shmample.db")
