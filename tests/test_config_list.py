import threading
import wave
from datetime import datetime
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, Static, TextArea

from shmample import device
from shmample.config_store import Configuration, list_configurations, save_configuration
from shmample.device import DeviceState
from shmample.widgets.config_list import ConfigList


def _write_wav(path, seconds, frame_rate=44_100, channels=1, sample_width=2):
    """A real (if silent) WAV file of the given duration - see
    test_device.py's identical helper for why content doesn't matter."""
    frames = int(seconds * frame_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00" * frames * channels * sample_width)


async def _wait_for_send(app):
    # app.workers.wait_for_complete() with no args waits for *every*
    # worker in the whole app - in the full ShmampleApp, FileBrowser's own
    # unrelated background directory-loader worker can get cancelled
    # during ordinary UI activity (focus changes etc.), which then fails
    # that bare wait even though the send itself completed fine. Scoping
    # to just the "send" group's worker(s) avoids that cross-talk.
    send_workers = [w for w in app.workers if w.group == "send"]
    if send_workers:
        await app.workers.wait_for_complete(send_workers)


class ConfigListApp(App):
    def __init__(self, configurations_dir, device_state=None) -> None:
        super().__init__()
        self.configurations_dir = configurations_dir
        # Mirrors ShmampleApp's own attribute (see action_send_to_device's
        # getattr) - defaults to None ("not connected yet") like the real
        # app before its first on_mount detection completes.
        self.device_state = device_state

    def compose(self) -> ComposeResult:
        yield ConfigList(self.configurations_dir, id="configs")


def _save(directory, name, description="", assignments=None):
    now = datetime(2026, 1, 1)
    save_configuration(
        Configuration(
            name=name,
            description=description,
            created_at=now,
            modified_at=now,
            assignments=assignments or {},
        ),
        directory,
    )


async def test_shows_placeholder_when_empty(tmp_path):
    app = ConfigListApp(tmp_path)
    async with app.run_test():
        configs = app.query_one(ConfigList)
        assert configs.entries == []


async def test_lists_existing_configurations_sorted_by_name(tmp_path):
    _save(tmp_path, "Zebra Kit")
    _save(tmp_path, "Alpha Kit")
    app = ConfigListApp(tmp_path)
    async with app.run_test():
        configs = app.query_one(ConfigList)
        assert [c.name for _, c in configs.entries] == ["Alpha Kit", "Zebra Kit"]


async def test_n_opens_modal_and_creates_configuration_on_submit(tmp_path):
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        app.screen.query_one("#name-input", Input).value = "My Kit"
        app.screen.query_one("#description-input", TextArea).text = "desc"
        await pilot.press("ctrl+s")
        await pilot.pause()

        saved = list_configurations(tmp_path)
        assert len(saved) == 1
        assert saved[0][1].name == "My Kit"
        assert saved[0][1].description == "desc"
        assert [c.name for _, c in configs.entries] == ["My Kit"]


async def test_n_posts_opened_so_a_new_configuration_is_immediately_active(tmp_path):
    # AssignmentGrid requires an active configuration before it'll accept
    # assignments (see its docstring) - "n" is the only way to create a
    # brand new one, so it must post Opened immediately, not just save
    # the file and leave it unselected until a separate Enter.
    opened = []

    class TrackingConfigListApp(ConfigListApp):
        def on_config_list_opened(self, message: ConfigList.Opened) -> None:
            opened.append((message.path, message.configuration))

    app = TrackingConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        app.screen.query_one("#name-input", Input).value = "My Kit"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert len(opened) == 1
        path, config = opened[0]
        assert config.name == "My Kit"
        assert path in [p for p, _ in list_configurations(tmp_path)]


async def test_n_then_cancel_creates_nothing(tmp_path):
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert list_configurations(tmp_path) == []
        assert configs.entries == []


async def test_c_then_confirm_duplicates_the_highlighted_configuration(tmp_path):
    _save(tmp_path, "Kit A", description="desc", assignments={("A", "1"): "/samples/kick.wav"})
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit A"

        await pilot.press("c")
        await pilot.pause()
        await pilot.press("enter")  # "Clone '...'" is the first, highlighted option
        await pilot.pause()

        saved = {c.name: c for _, c in list_configurations(tmp_path)}
        assert set(saved) == {"Kit A", "Copy of Kit A"}
        clone = saved["Copy of Kit A"]
        assert clone.description == "desc"
        assert clone.assignments == {("A", "1"): "/samples/kick.wav"}
        # Left untouched - the clone is a new file, not a rename in place.
        assert saved["Kit A"].name == "Kit A"


async def test_c_then_confirm_gives_the_clone_a_fresh_created_at(tmp_path):
    _save(tmp_path, "Kit A")  # created/modified 2026-01-01, via _save's helper
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        clone = next(c for _, c in list_configurations(tmp_path) if c.name == "Copy of Kit A")
        assert clone.created_at > datetime(2026, 1, 1)
        assert clone.modified_at > datetime(2026, 1, 1)


async def test_c_then_cancel_clones_nothing(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert [c.name for _, c in list_configurations(tmp_path)] == ["Kit A"]


async def test_c_navigate_to_cancel_option_clones_nothing(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        await pilot.press("j")  # down from "Clone '...'" to "Cancel"
        await pilot.press("enter")
        await pilot.pause()

        assert [c.name for _, c in list_configurations(tmp_path)] == ["Kit A"]


async def test_c_detail_text_switches_with_highlighted_option(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        detail = app.screen.query_one("#detail", Static)
        assert "Duplicate 'Kit A'" in str(detail.render())

        await pilot.press("j")
        await pilot.pause()
        assert "Don't clone anything" in str(detail.render())


async def test_c_with_no_configurations_does_nothing(tmp_path):
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)

        await pilot.press("c")
        await pilot.pause()

        # no confirmation modal should have appeared - nothing to clone
        assert len(app.screen_stack) == screens_before
        assert list_configurations(tmp_path) == []


async def test_d_then_confirm_deletes_the_selected_configuration(tmp_path):
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit A"

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")  # "Delete '...'" is the first, highlighted option
        await pilot.pause()

        remaining = [c.name for _, c in list_configurations(tmp_path)]
        assert remaining == ["Kit B"]
        assert [c.name for _, c in configs.entries] == ["Kit B"]


async def test_d_then_cancel_deletes_nothing(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert len(list_configurations(tmp_path)) == 1
        assert len(configs.entries) == 1


async def test_d_navigate_to_cancel_option_deletes_nothing(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("j")  # down from "Delete '...'" to "Cancel"
        await pilot.press("enter")
        await pilot.pause()

        assert len(list_configurations(tmp_path)) == 1


async def test_d_detail_text_switches_with_highlighted_option(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        detail = app.screen.query_one("#detail", Static)
        assert "cannot be undone" in str(detail.render())

        await pilot.press("j")
        await pilot.pause()
        assert "Keep the configuration" in str(detail.render())


async def test_d_with_no_configurations_does_nothing(tmp_path):
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("d")
        await pilot.pause()
        # no confirmation modal should have appeared - nothing to delete
        assert len(app.screen_stack) == screens_before


async def test_enter_records_last_opened(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        assert configs.last_opened is None
        await pilot.press("enter")
        await pilot.pause()
        assert configs.last_opened.name == "Kit A"


async def test_vim_keys_navigate(tmp_path):
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit A"
        await pilot.press("j")
        assert configs.highlighted_configuration.name == "Kit B"
        await pilot.press("k")
        assert configs.highlighted_configuration.name == "Kit A"


async def test_gg_then_shift_g_jump_to_top_and_bottom(tmp_path):
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    _save(tmp_path, "Kit C")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit A"

        await pilot.press("G")
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit C"

        await pilot.press("g")
        await pilot.press("g")
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit A"


async def test_a_single_g_does_nothing(tmp_path):
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit B"

        await pilot.press("g")
        await pilot.pause()
        assert configs.highlighted_configuration.name == "Kit B"  # unmoved - not a real "gg"


async def test_s_with_no_configurations_does_nothing(tmp_path):
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, tmp_path / "mount", device.MODE_IMPORT))
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == screens_before


async def test_s_with_no_assignments_notifies_and_opens_no_modal(tmp_path):
    _save(tmp_path, "Kit A")
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, tmp_path / "mount", device.MODE_IMPORT))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == screens_before
        assert notifications == ["No assignments to send."]


async def test_s_with_device_not_connected_notifies_and_opens_no_modal(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    app = ConfigListApp(tmp_path, device_state=DeviceState(False, None, None))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == screens_before
        assert len(notifications) == 1
        assert "not connected" in notifications[0]


async def test_s_with_wrong_mode_notifies_and_opens_no_modal(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    app = ConfigListApp(
        tmp_path, device_state=DeviceState(True, tmp_path / "mount", device.MODE_EXPORT)
    )
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == screens_before
        assert notifications == [device.IMPORT_MODE_INSTRUCTIONS]


async def test_s_then_confirm_sends_the_highlighted_configuration(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()  # check_available_space needs a real mount to statfs
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")  # "Send '...'" is the first, highlighted option
        await _wait_for_send(app)
        await pilot.pause()

        copied = mount / device.MODE_IMPORT / device.bank_folder("A") / device.pad_folder(1)
        assert (copied / "kick.wav").read_bytes() == b"kick"
        assert configs.loading is False  # cleared once the send finished
        # device.unmount() can't find a real block device for this fake
        # mount (no lsblk entry matches it) - the "couldn't safely
        # eject automatically" fallback is expected here, not a failure.
        assert notifications == [
            "Sent 1 sample(s) to the device. Couldn't safely eject automatically - "
            "eject it yourself before power-cycling, or the import may not see everything.",
        ]


async def test_s_shows_a_persistent_loading_indicator_for_the_duration_of_the_send(
    tmp_path, monkeypatch
):
    # Regression coverage for a real report: a notify() toast times out
    # on a fixed schedule regardless of whether the send has actually
    # finished, which for a slow real USB copy looked like the "pop-up"
    # vanishing before anything happened. `loading` doesn't have that
    # problem - it's cleared explicitly by _send's own finally, however
    # long the copy actually takes. Controlled deterministically with a
    # real threading.Event (not a sleep/timing guess) so this can check
    # the indicator mid-flight without being racy.
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    release = threading.Event()
    real_send_configuration = device.send_configuration

    def _blocking_send(config, mount):
        release.wait(timeout=5)
        return real_send_configuration(config, mount)

    monkeypatch.setattr(device, "send_configuration", _blocking_send)
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert configs.loading is True  # still "copying" - release not set yet

        release.set()
        await _wait_for_send(app)
        await pilot.pause()

        assert configs.loading is False


async def test_s_then_confirm_ejects_the_device_when_unmount_succeeds(tmp_path, monkeypatch):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()

    async def _fake_unmount(path):
        return True

    async def _fake_detect_disconnected():
        return DeviceState(False, None, None)

    monkeypatch.setattr(device, "unmount", _fake_unmount)
    monkeypatch.setattr(device, "detect_device_state_async", _fake_detect_disconnected)
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await _wait_for_send(app)
        await pilot.pause()

        assert notifications == [
            "Sent 1 sample(s) to the device. Safely ejected - you can power-cycle the device now.",
        ]
        assert app.device_state.connected is False


async def test_s_then_cancel_sends_nothing(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not (mount / device.MODE_IMPORT).exists()


async def test_s_navigate_to_cancel_option_sends_nothing(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("j")  # down from "Send '...'" to "Cancel"
        await pilot.press("enter")
        await pilot.pause()

        assert not (mount / device.MODE_IMPORT).exists()


async def test_s_reports_missing_sources_without_blocking_the_rest(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick")
    _save(
        tmp_path,
        "Kit A",
        assignments={("A", "1"): str(sample), ("A", "2"): str(tmp_path / "gone.wav")},
    )
    mount = tmp_path / "mount"
    mount.mkdir()
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await _wait_for_send(app)
        await pilot.pause()

        copied = mount / device.MODE_IMPORT / device.bank_folder("A") / device.pad_folder(1)
        assert (copied / "kick.wav").exists()
        assert notifications == [
            "Sent 1 sample(s); 1 missing and skipped. Couldn't safely eject automatically - "
            "eject it yourself before power-cycling, or the import may not see everything.",
        ]


async def test_s_with_insufficient_space_notifies_and_opens_no_modal(tmp_path, monkeypatch):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"kick" * 1000)
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=10)
    )
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        screens_before = len(app.screen_stack)
        await pilot.press("s")
        await pilot.pause()
        assert len(app.screen_stack) == screens_before
        assert len(notifications) == 1
        assert "won't fit" in notifications[0]
        assert "Kit A" in notifications[0]


async def test_s_confirm_modal_warns_about_a_likely_truncated_sample(tmp_path):
    # 5 seconds at 96kHz mono is well past the ~2.7s that rate/channel
    # count fits in a pad's fixed memory budget (see device.py's
    # PAD_MEMORY_BUDGET_BYTES) - long enough to trigger the warning
    # without writing a large file.
    long_sample = tmp_path / "long.wav"
    _write_wav(long_sample, seconds=5, frame_rate=96_000, channels=1)
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(long_sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()

        detail = str(app.screen.query_one("#detail", Static).render())
        assert "truncated" in detail
        assert "long.wav" in detail


def _configuration(tmp_path, assignments=None):
    now = datetime(2026, 1, 1)
    return Configuration(
        name="Kit A", description="", created_at=now, modified_at=now, assignments=assignments or {}
    )


def test_config_label_shows_no_size_for_an_empty_configuration(tmp_path):
    configs = ConfigList(tmp_path)
    text = configs._config_label(_configuration(tmp_path), available=None)
    assert str(text) == "Kit A"


def test_config_label_shows_size_dim_with_no_verdict_available(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 2000)
    configs = ConfigList(tmp_path)

    text = configs._config_label(_configuration(tmp_path, {("A", "1"): str(sample)}), available=None)

    assert "2.0KB" in str(text)
    assert text.spans[-1].style == "dim"


def test_config_label_flags_too_large_in_bold_red(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 2000)
    configs = ConfigList(tmp_path)

    fits = configs._config_label(_configuration(tmp_path, {("A", "1"): str(sample)}), available=2000)
    too_big = configs._config_label(_configuration(tmp_path, {("A", "1"): str(sample)}), available=1999)

    assert fits.spans[-1].style == "dim"
    assert too_big.spans[-1].style == "bold red"


async def test_list_shows_a_configurations_size_next_to_its_name(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 2000)
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    app = ConfigListApp(tmp_path)
    async with app.run_test():
        configs = app.query_one(ConfigList)
        labels = [str(label.render()) for label in configs.query(Label)]
        assert any("Kit A" in label and "2.0KB" in label for label in labels)


async def test_list_computes_available_space_from_the_connected_device(tmp_path, monkeypatch):
    # Verifies refresh_list()'s wiring - that it actually calls
    # _config_label with device.available_bytes_once_cleared(mount), not
    # just that _config_label itself colours correctly in isolation
    # (already covered above). Spies on the real method rather than
    # inspecting rendered style, since Textual's own Content/Visual
    # pipeline doesn't expose the original Text's style spans back out
    # through a mounted widget.
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 2000)
    _save(tmp_path, "Kit A", assignments={("A", "1"): str(sample)})
    mount = tmp_path / "mount"
    mount.mkdir()
    monkeypatch.setattr(
        device.shutil, "disk_usage", lambda path: SimpleNamespace(total=0, used=0, free=1234)
    )
    app = ConfigListApp(tmp_path, device_state=DeviceState(True, mount, device.MODE_IMPORT))

    async with app.run_test():
        configs = app.query_one(ConfigList)
        seen = []
        original = configs._config_label
        configs._config_label = lambda config, available: (
            seen.append(available) or original(config, available)
        )

        configs.refresh_list()

        assert seen == [1234]


async def test_list_preserves_highlight_across_a_device_triggered_refresh(tmp_path):
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("j")
        assert configs.highlighted_configuration.name == "Kit B"

        configs.refresh_list()
        # Two pauses, not one - the highlight restore is deferred via
        # call_after_refresh (see refresh_list's comment for why), which
        # runs on the *next* refresh cycle after this one, not this one.
        await pilot.pause()
        await pilot.pause()

        assert configs.highlighted_configuration.name == "Kit B"


async def test_list_visually_highlights_the_restored_row_not_just_its_index(tmp_path):
    # Regression test for a real bug: index (and so
    # highlighted_configuration) came back correct even when the actual
    # visual highlight didn't - setting self.index synchronously right
    # after append() fires ListView's own watch_index against ListItem
    # nodes that Textual hadn't actually mounted yet, so the "highlight
    # the new node" side effect inside it silently no-ops and never gets
    # a second chance to run once the nodes do exist.
    _save(tmp_path, "Kit A")
    _save(tmp_path, "Kit B")
    app = ConfigListApp(tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("j")

        configs.refresh_list()
        await pilot.pause()
        await pilot.pause()

        highlighted_node = configs._nodes[configs.index]
        assert highlighted_node.highlighted is True
        others = [node for node in configs._nodes if node is not highlighted_node]
        assert others and all(node.highlighted is False for node in others)
