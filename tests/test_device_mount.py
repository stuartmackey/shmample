import asyncio
import json

import pytest

from shmample import device


class _FakeCommandProcess:
    def __init__(self, stdout: bytes, returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""

    async def wait(self):
        return self.returncode


@pytest.fixture
def fake_commands(monkeypatch):
    """Patches asyncio.create_subprocess_exec so tests can control what
    each command (lsblk, udisksctl, ...) appears to output, without
    running anything real. `responses` maps the program name to
    (stdout_bytes, returncode); `calls` records every invocation made."""
    responses: dict[str, tuple[bytes, int]] = {}
    calls: list[tuple] = []

    async def _fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        stdout, returncode = responses.get(args[0], (b"", 0))
        return _FakeCommandProcess(stdout, returncode)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr(device.platform, "system", lambda: "Linux")
    return responses, calls


def _lsblk_json(*devices):
    return json.dumps({"blockdevices": list(devices)}).encode()


async def test_find_unmounted_device_matches_by_label(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (
        _lsblk_json(
            {"name": "sda", "label": None, "mountpoint": None},
            {"name": "sdc", "label": "P-6", "mountpoint": None},
        ),
        0,
    )

    result = await device.find_unmounted_device()

    assert result == device.Path("/dev/sdc")


async def test_find_unmounted_device_ignores_already_mounted(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (
        _lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": "/run/media/stuart/P-6"}),
        0,
    )

    assert await device.find_unmounted_device() is None


async def test_find_unmounted_device_searches_nested_children(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (
        _lsblk_json(
            {
                "name": "sda",
                "label": None,
                "mountpoint": None,
                "children": [{"name": "sda1", "label": "P-6", "mountpoint": None}],
            }
        ),
        0,
    )

    assert await device.find_unmounted_device() == device.Path("/dev/sda1")


async def test_find_unmounted_device_none_on_non_linux(fake_commands, monkeypatch):
    monkeypatch.setattr(device.platform, "system", lambda: "Darwin")
    responses, calls = fake_commands
    responses["lsblk"] = (_lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": None}), 0)

    assert await device.find_unmounted_device() is None
    assert calls == []  # never even tried


async def test_mount_device_parses_udisksctl_output(fake_commands):
    responses, _ = fake_commands
    responses["udisksctl"] = (b"Mounted /dev/sdc at /run/media/stuart/P-6.\n", 0)

    result = await device.mount_device(device.Path("/dev/sdc"))

    assert result == device.Path("/run/media/stuart/P-6")


async def test_mount_device_returns_none_on_failure(fake_commands):
    responses, _ = fake_commands
    responses["udisksctl"] = (b"", 1)

    assert await device.mount_device(device.Path("/dev/sdc")) is None


async def test_unmount_device_success_and_failure(fake_commands):
    responses, _ = fake_commands
    responses["udisksctl"] = (b"Unmounted /dev/sdc.\n", 0)
    assert await device.unmount_device(device.Path("/dev/sdc")) is True

    responses["udisksctl"] = (b"", 1)
    assert await device.unmount_device(device.Path("/dev/sdc")) is False


async def test_find_device_for_mount_matches_by_mountpoint(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (
        _lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": "/run/media/stuart/P-6"}),
        0,
    )

    result = await device.find_device_for_mount(device.Path("/run/media/stuart/P-6"))

    assert result == device.Path("/dev/sdc")


async def test_ensure_mounted_end_to_end(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": None}), 0)
    responses["udisksctl"] = (b"Mounted /dev/sdc at /run/media/stuart/P-6.\n", 0)

    result = await device.ensure_mounted()

    assert result == device.Path("/run/media/stuart/P-6")


async def test_ensure_mounted_none_when_nothing_to_mount(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json(), 0)

    assert await device.ensure_mounted() is None


async def test_unmount_none_when_nothing_found_at_mount(fake_commands):
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json(), 0)

    assert await device.unmount(device.Path("/run/media/stuart/P-6")) is False


async def test_detect_or_mount_skips_auto_mount_when_already_connected(
    fake_commands, monkeypatch, tmp_path
):
    already_mounted = tmp_path / "already-mounted"
    (already_mounted / device.MODE_IMPORT).mkdir(parents=True)
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: already_mounted)
    _, calls = fake_commands

    state = await device.detect_or_mount()

    assert state.connected is True
    assert state.mode == device.MODE_IMPORT
    assert calls == []  # never touched lsblk/udisksctl - no need to


async def test_detect_or_mount_auto_mounts_when_nothing_found(
    fake_commands, monkeypatch, tmp_path
):
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: None)
    target = tmp_path / "newly-mounted"
    (target / device.MODE_EXPORT).mkdir(parents=True)

    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": None}), 0)
    responses["udisksctl"] = (f"Mounted /dev/sdc at {target}.\n".encode(), 0)

    state = await device.detect_or_mount()

    assert state.connected is True
    assert state.mount == target
    assert state.mode == device.MODE_EXPORT


async def test_detect_or_mount_falls_back_to_not_connected(fake_commands, monkeypatch):
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: None)
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json(), 0)  # nothing to find

    state = await device.detect_or_mount()

    assert state.connected is False
    assert state.unmounted_device is None


async def test_detect_or_mount_reports_unmounted_device_when_auto_mount_fails(
    fake_commands, monkeypatch
):
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: None)
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": None}), 0)
    responses["udisksctl"] = (b"", 1)  # mount attempt fails

    state = await device.detect_or_mount()

    assert state.connected is False
    assert state.unmounted_device == device.Path("/dev/sdc")


async def test_detect_device_state_async_reports_unmounted_device_when_present(
    fake_commands, monkeypatch
):
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: None)
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json({"name": "sdc", "label": "P-6", "mountpoint": None}), 0)

    state = await device.detect_device_state_async()

    assert state.connected is False
    assert state.mount is None
    assert state.unmounted_device == device.Path("/dev/sdc")


async def test_detect_device_state_async_none_when_nothing_present(fake_commands, monkeypatch):
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: None)
    responses, _ = fake_commands
    responses["lsblk"] = (_lsblk_json(), 0)

    state = await device.detect_device_state_async()

    assert state.connected is False
    assert state.unmounted_device is None


async def test_detect_device_state_async_skips_lsblk_when_already_mounted(
    fake_commands, monkeypatch, tmp_path
):
    mounted = tmp_path / "already-mounted"
    (mounted / device.MODE_IMPORT).mkdir(parents=True)
    monkeypatch.setattr(device, "autodetect_mount", lambda expected_names=None: mounted)
    _, calls = fake_commands

    state = await device.detect_device_state_async()

    assert state.connected is True
    assert calls == []  # already mounted - never needed to ask lsblk
