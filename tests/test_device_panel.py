from textual.app import App, ComposeResult
from textual.widgets import Footer
from textual.widgets._footer import FooterKey

from shmample.app import ShmampleApp
from shmample.device import DeviceState
from shmample.widgets.device_panel import DevicePanel


class DevicePanelApp(App):
    def compose(self) -> ComposeResult:
        yield DevicePanel(id="device")


def _text(panel: DevicePanel) -> str:
    return str(panel.render())


async def test_shows_checking_message_before_anything_is_known():
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)
        assert "Checking" in _text(panel)


async def test_shows_not_connected():
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=False, mount=None, mode=None))
        assert _text(panel) == "P-6 not connected"


async def test_shows_mode_when_connected_and_recognised():
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=True, mount=None, mode="IMPORT"))
        assert "IMPORT" in _text(panel)
        assert "connected" in _text(panel)


async def test_shows_ambiguous_when_connected_but_mode_unrecognised():
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=True, mount=None, mode=None))
        assert "not recognised" in _text(panel)


async def test_unmount_action_unmounts_and_refreshes(monkeypatch, tmp_path):
    calls = []

    async def _fake_unmount(mount):
        calls.append(mount)
        return True

    async def _fake_detect_device_state_async():
        return DeviceState(connected=False, mount=None, mode=None)

    monkeypatch.setattr("shmample.widgets.device_panel.device.unmount", _fake_unmount)
    monkeypatch.setattr(
        "shmample.widgets.device_panel.device.detect_device_state_async",
        _fake_detect_device_state_async,
    )

    app = DevicePanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=True, mount=tmp_path, mode="IMPORT"))
        panel.focus()
        await pilot.press("u")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == [tmp_path]
        assert _text(panel) == "P-6 not connected"
        assert app.device_state.connected is False


async def test_unmount_action_is_a_noop_when_not_connected(monkeypatch):
    async def _fake_unmount(mount):
        raise AssertionError("should never be called when not connected")

    monkeypatch.setattr("shmample.widgets.device_panel.device.unmount", _fake_unmount)

    app = DevicePanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=False, mount=None, mode=None))
        panel.focus()
        await pilot.press("u")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert _text(panel) == "P-6 not connected"


async def test_shows_visible_but_unmounted_device():
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)
        panel.show(
            DeviceState(
                connected=False, mount=None, mode=None, unmounted_device="/dev/sdc"
            )
        )
        assert "not mounted" in _text(panel)
        assert "/dev/sdc" in _text(panel)


async def test_mount_action_mounts_and_refreshes(monkeypatch):
    calls = []

    async def _fake_mount_device(block_device):
        calls.append(block_device)
        return "/run/media/stuart/P-6"

    async def _fake_detect_device_state_async():
        return DeviceState(connected=True, mount="/run/media/stuart/P-6", mode="IMPORT")

    monkeypatch.setattr("shmample.widgets.device_panel.device.mount_device", _fake_mount_device)
    monkeypatch.setattr(
        "shmample.widgets.device_panel.device.detect_device_state_async",
        _fake_detect_device_state_async,
    )

    app = DevicePanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(DevicePanel)
        panel.show(
            DeviceState(connected=False, mount=None, mode=None, unmounted_device="/dev/sdc")
        )
        panel.focus()
        await pilot.press("m")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert calls == ["/dev/sdc"]
        assert "IMPORT" in _text(panel)
        assert app.device_state.connected is True


async def test_mount_action_is_a_noop_when_nothing_visible(monkeypatch):
    async def _fake_mount_device(block_device):
        raise AssertionError("should never be called when nothing's visible")

    monkeypatch.setattr("shmample.widgets.device_panel.device.mount_device", _fake_mount_device)

    app = DevicePanelApp()
    async with app.run_test() as pilot:
        panel = app.query_one(DevicePanel)
        panel.show(DeviceState(connected=False, mount=None, mode=None))
        panel.focus()
        await pilot.press("m")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assert _text(panel) == "P-6 not connected"


async def test_check_action_shows_exactly_one_of_mount_or_unmount(tmp_path):
    app = DevicePanelApp()
    async with app.run_test():
        panel = app.query_one(DevicePanel)

        panel.show(DeviceState(connected=True, mount=tmp_path, mode="IMPORT"))
        assert panel.check_action("unmount", ()) is True
        assert panel.check_action("mount", ()) is False

        panel.show(
            DeviceState(connected=False, mount=None, mode=None, unmounted_device="/dev/sdc")
        )
        assert panel.check_action("unmount", ()) is False
        assert panel.check_action("mount", ()) is True

        panel.show(DeviceState(connected=False, mount=None, mode=None))
        assert panel.check_action("unmount", ()) is False
        assert panel.check_action("mount", ()) is False


async def test_app_poll_updates_panel_when_device_disappears(monkeypatch, tmp_path):
    import shmample.app as app_module

    async def _fake_detect_or_mount():
        return DeviceState(connected=True, mount=tmp_path, mode="IMPORT")

    async def _fake_detect_device_state_async():
        return DeviceState(False, None, None)

    monkeypatch.setattr(app_module.device, "detect_or_mount", _fake_detect_or_mount)
    monkeypatch.setattr(
        app_module.device, "detect_device_state_async", _fake_detect_device_state_async
    )

    app = ShmampleApp(samples_directories=[])
    async with app.run_test():
        panel = app.query_one("#device", DevicePanel)
        assert "IMPORT" in _text(panel)

        await app._poll_device()

        assert app.device_state.connected is False
        assert _text(panel) == "P-6 not connected"


async def test_app_poll_leaves_panel_untouched_when_state_is_unchanged(monkeypatch, tmp_path):
    import shmample.app as app_module

    connected_state = DeviceState(connected=True, mount=tmp_path, mode="IMPORT")

    async def _fake_detect_or_mount():
        return connected_state

    async def _fake_detect_device_state_async():
        return connected_state

    monkeypatch.setattr(app_module.device, "detect_or_mount", _fake_detect_or_mount)
    monkeypatch.setattr(
        app_module.device, "detect_device_state_async", _fake_detect_device_state_async
    )

    app = ShmampleApp(samples_directories=[])
    async with app.run_test():
        panel = app.query_one("#device", DevicePanel)

        await app._poll_device()

        assert app.device_state is connected_state


async def test_footer_shows_unmount_binding_only_when_device_pane_focused(tmp_path):
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        footer = app.query_one(Footer)

        panel = app.query_one("#device", DevicePanel)
        panel.show(DeviceState(connected=True, mount=tmp_path, mode="IMPORT"))
        panel.focus()
        await pilot.pause()
        keys = {key.key for key in footer.query(FooterKey)}
        assert "u" in keys

        app.query_one("#packs").focus()
        await pilot.pause()
        keys = {key.key for key in footer.query(FooterKey)}
        assert "u" not in keys


async def test_app_wires_detected_state_into_the_panel(monkeypatch, tmp_path):
    import shmample.app as app_module

    async def _fake_detect_or_mount():
        return DeviceState(connected=True, mount=tmp_path, mode="EXPORT")

    monkeypatch.setattr(app_module.device, "detect_or_mount", _fake_detect_or_mount)

    app = ShmampleApp(samples_directories=[])
    async with app.run_test():
        panel = app.query_one("#device", DevicePanel)
        assert "EXPORT" in _text(panel)
        assert app.device_state.mode == "EXPORT"
