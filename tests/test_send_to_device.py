import pytest
from textual.widgets import Input

from shmample import device
from shmample.app import ShmampleApp
from shmample.config_store import list_configurations
from shmample.device import DeviceState
from shmample.widgets.config_list import ConfigList
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.holding_area import HoldingArea


@pytest.fixture
def samples_dir(tmp_path):
    (tmp_path / "kick.wav").write_bytes(b"kick")
    return tmp_path


async def _wait_for_send(app):
    # Bare app.workers.wait_for_complete() waits for *every* worker in
    # the app, including FileBrowser's own unrelated preview-playback
    # worker - that one can get cancelled during ordinary UI activity
    # (focus changes etc.), which fails the wait even though the send
    # itself completed fine. Scope to just the "send" group's worker(s)
    # instead.
    send_workers = [w for w in app.workers if w.group == "send"]
    if send_workers:
        await app.workers.wait_for_complete(send_workers)


async def test_end_to_end_create_assign_and_send(samples_dir, tmp_path, monkeypatch):
    # Full path: "n" creates a configuration, "a" from the file browser
    # holds a sample against it, "a" from the holding area then assigns
    # that held sample to a pad, and "s" (highlighted in ConfigList)
    # sends the result onto a mounted-in-IMPORT-mode device - exercising
    # every pane this feature touches, not just ConfigList in isolation.
    #
    # ShmampleApp's own DEVICE_POLL_INTERVAL keeps re-detecting the real
    # (disconnected) hardware state every 2s in the background - with
    # this many real steps now in the middle (holding area round-trip
    # included), the test can run long enough for a poll tick to land
    # between the manual `app.device_state = ...` below and "s", clobbering
    # it back to disconnected. Pin detection to the fake connected state
    # so the assertions below don't depend on beating that clock.
    mount = tmp_path / "mount"
    mount.mkdir()  # check_available_space needs a real mount to statfs

    async def _fake_detect_connected():
        return DeviceState(True, mount, device.MODE_IMPORT)

    monkeypatch.setattr(device, "detect_device_state_async", _fake_detect_connected)

    app = ShmampleApp(samples_directories=[samples_dir], configurations_dir=tmp_path / "configs")
    async with app.run_test() as pilot:
        configs = app.query_one("#configurations", ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#name-input", Input).value = "My Kit"
        await pilot.press("ctrl+s")
        await pilot.pause()

        browser = app.query_one("#files", FileBrowser)
        root_node = browser.root.children[0]
        root_node.expand()
        await pilot.pause()
        kick_node = next(n for n in root_node.children if "kick.wav" in str(n.label))
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        holding = app.query_one("#holding", HoldingArea)
        holding.focus()
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()

        app.device_state = DeviceState(True, mount, device.MODE_IMPORT)

        configs.focus()
        await pilot.pause()
        # ConfigList's index is still None here - "n" doesn't highlight
        # the configuration it just created (same pre-existing gap "d"
        # has right after "n", not something this feature introduces) -
        # a nudge highlights the only entry there is.
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await _wait_for_send(app)
        await pilot.pause()

        copied = mount / device.MODE_IMPORT / device.bank_folder("E") / device.pad_folder(4)
        assert (copied / "kick.wav").read_bytes() == b"kick"
        saved = list_configurations(tmp_path / "configs")
        assert saved[0][1].assignments[("E", "4")] == str(samples_dir / "kick.wav")
