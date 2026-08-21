import asyncio
from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from shmample import config_store, device
from shmample.config_store import Configuration, delete_configuration, list_configurations, save_configuration
from shmample.widgets.vim_navigation import VimGoToTopAndBottom
from shmample.widgets.vim_option_list import VimOptionList


class NewConfigurationModal(ModalScreen[tuple[str, str] | None]):
    """Name + description prompt for `n` - lazygit's commit-message modal
    look: titled/bordered input boxes floating over the app, no visible
    buttons. Description is a TextArea (multi-line, so Enter there inserts
    a newline rather than submitting - ctrl+s submits from either field,
    matching Input's own Enter-submits behaviour for the name field)."""

    DEFAULT_CSS = """
    NewConfigurationModal {
        align: center middle;
    }
    NewConfigurationModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    NewConfigurationModal #name-input {
        border: round $success;
        height: 3;
    }
    NewConfigurationModal #description-input {
        border: round $success;
        height: 8;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "submit", "Create"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            name_input = Input(id="name-input")
            name_input.border_title = "Name"
            yield name_input

            description_input = TextArea(id="description-input")
            description_input.border_title = "Description"
            description_input.border_subtitle = "tab: switch field  ctrl+s: create  esc: cancel"
            yield description_input

    def on_mount(self) -> None:
        self.query_one("#name-input", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        name = self.query_one("#name-input", Input).value.strip()
        description = self.query_one("#description-input", TextArea).text.strip()
        if name:
            self.dismiss((name, description))

    @on(Input.Submitted)
    def _name_submitted(self) -> None:
        self.action_submit()


class ConfirmCloneModal(ModalScreen[bool]):
    """Clone confirmation - same OptionList + detail-pane shape as
    ConfirmDeleteModal below, but styled $success since duplicating a
    configuration destroys nothing (mirrors ConfirmSendModal's own choice
    of styling for a non-destructive confirm)."""

    DEFAULT_CSS = """
    ConfirmCloneModal {
        align: center middle;
    }
    ConfirmCloneModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    ConfirmCloneModal OptionList {
        border: round $success;
        height: auto;
    }
    ConfirmCloneModal #detail {
        border: round $success;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config_name: str) -> None:
        super().__init__()
        self.config_name = config_name
        self._details = (
            f"Duplicate '{self.config_name}' as 'Copy of {self.config_name}'.",
            "Don't clone anything.",
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Clone '{self.config_name}'", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Clone configuration"
            options.border_subtitle = f"1 of {len(self._details)}"
            yield options
            yield Static(self._details[0], id="detail")

    def on_mount(self) -> None:
        self.query_one(VimOptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        options = event.option_list
        options.border_subtitle = f"{event.option_index + 1} of {options.option_count}"
        self.query_one("#detail", Static).update(self._details[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id == "confirm")


class ConfirmDeleteModal(ModalScreen[bool]):
    """Delete confirmation - lazygit's discard-changes menu look: a titled
    option-list menu (position indicator in the border, like "1 of 2")
    plus a second bordered box detailing whichever option is highlighted.
    `d` always asks first, per 06-configuration-list.md."""

    DEFAULT_CSS = """
    ConfirmDeleteModal {
        align: center middle;
    }
    ConfirmDeleteModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    ConfirmDeleteModal OptionList {
        border: round $error;
        height: auto;
    }
    ConfirmDeleteModal #detail {
        border: round $error;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config_name: str) -> None:
        super().__init__()
        self.config_name = config_name
        self._details = (
            f"Delete '{self.config_name}'. This cannot be undone.",
            "Keep the configuration as it is.",
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Delete '{self.config_name}'", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Delete configuration"
            options.border_subtitle = f"1 of {len(self._details)}"
            yield options
            yield Static(self._details[0], id="detail")

    def on_mount(self) -> None:
        self.query_one(VimOptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        options = event.option_list
        options.border_subtitle = f"{event.option_index + 1} of {options.option_count}"
        self.query_one("#detail", Static).update(self._details[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id == "confirm")


class ConfirmSendModal(ModalScreen[bool]):
    """Confirmation before "s" actually touches the device - same
    OptionList + detail-pane shape as ConfirmDeleteModal, but styled
    $success rather than $error since nothing on the device's actual
    memory is destroyed (only staged IMPORT-folder content, which never
    represented anything committed - see send_configuration's docstring),
    per 09-save-assignments.md's "needs a confirmation before being
    actioned". The detail text still names the wipe explicitly though -
    it does clear the whole IMPORT tree, not just this configuration's
    pads, so it's worth the user knowing that up front."""

    DEFAULT_CSS = """
    ConfirmSendModal {
        align: center middle;
    }
    ConfirmSendModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    ConfirmSendModal OptionList {
        border: round $success;
        height: auto;
    }
    ConfirmSendModal #detail {
        border: round $success;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config_name: str, sample_count: int, warnings: list[str] = ()) -> None:
        super().__init__()
        self.config_name = config_name
        noun = "sample" if sample_count == 1 else "samples"
        confirm_detail = (
            f"Copy {sample_count} {noun} from '{self.config_name}' onto the "
            "device's IMPORT folder, clearing anything currently staged there first "
            "(including any other configuration's samples not yet imported)."
        )
        if warnings:
            confirm_detail += (
                f"\n\n{len(warnings)} may come back truncated once the device imports "
                "them (their sample is longer than that pad fits at its rate):\n"
                + "\n".join(warnings)
            )
        self._details = (confirm_detail, "Don't send anything.")

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Send '{self.config_name}' to the device", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Send to device"
            options.border_subtitle = f"1 of {len(self._details)}"
            yield options
            yield Static(self._details[0], id="detail")

    def on_mount(self) -> None:
        self.query_one(VimOptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        options = event.option_list
        options.border_subtitle = f"{event.option_index + 1} of {options.option_count}"
        self.query_one("#detail", Static).update(self._details[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id == "confirm")


class ConfigList(ListView, VimGoToTopAndBottom):
    """Lists saved configurations from ~/.config/shmample/configurations.

    No parent index file - just reads whatever's in the directory (see
    config_store.list_configurations). Vertical-only, like FileBrowser's
    file list before it became a tree, so it only needs vim's j/k/gg/G.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("n", "new_configuration", "New"),
        Binding("c", "clone_selected", "Clone"),
        Binding("d", "delete_selected", "Delete"),
        Binding("s", "send_to_device", "Send"),
    ] + VimGoToTopAndBottom.BINDINGS

    def go_to_top(self) -> None:
        if self.children:
            self.index = 0

    def go_to_bottom(self) -> None:
        if self.children:
            self.index = len(self.children) - 1

    class Opened(Message):
        """Posted when Enter opens a configuration.

        The assignment grid that should load it is a sibling, not a
        descendant, of this widget (see app.py's layout) - bubbling a
        message up to whatever owns both, rather than reaching sideways
        into it directly, avoids ConfigList and AssignmentGrid needing to
        import each other.
        """

        def __init__(self, path: Path, configuration: Configuration) -> None:
            super().__init__()
            self.path = path
            self.configuration = configuration

    def __init__(
        self, configurations_dir: Path | None = None, *args, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        # Resolved at call time (not a mutable default parameter) so tests
        # can monkeypatch config_store.DEFAULT_CONFIGURATIONS_DIR and have
        # it actually take effect, rather than binding the real
        # ~/.config path once at class-definition time.
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
        )
        self.entries: list[tuple[Path, Configuration]] = []
        # Enter opens a configuration, but actually loading it into the
        # pad-assignment grid waits until that pane exists
        # (06-configuration-list.md) - this just records what was opened.
        self.last_opened: Configuration | None = None

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        # ListView only applies its own initial_index (defaulting the
        # highlight to 0) the very first time it mounts with children -
        # clear()+append() here doesn't get that for free on a *later*
        # call, so without explicitly saving/restoring it, any refresh
        # after the first (e.g. the device-state-driven one below) would
        # silently drop the user's current highlight back to nothing.
        previous_index = self.index

        self.entries = sorted(
            list_configurations(self.configurations_dir),
            key=lambda entry: entry[1].name.lower(),
        )
        self.clear()
        if not self.entries:
            self.append(ListItem(Label("No saved configurations (n to create one)")))
            return

        # Computed once per refresh, not once per row - available_bytes_
        # once_cleared only depends on the mount, not on which
        # configuration's being sized against it. None (rather than a
        # number) when there's nothing connected to check against, so
        # _config_label knows to show a size with no fits/too-large
        # judgement at all instead of guessing.
        available = None
        state = getattr(self.app, "device_state", None)
        if state is not None and state.connected and state.mount is not None:
            if state.mode == device.MODE_IMPORT:
                try:
                    available = device.available_bytes_once_cleared(state.mount)
                except OSError:
                    # Reported connected/mounted a moment ago, but
                    # statfs-ing it just now failed (unplugged mid-
                    # render, or - only ever seen in tests - a
                    # DeviceState built by hand pointing at a mount that
                    # was never actually created). Show sizes with no
                    # fits/too-large verdict rather than crash the list.
                    available = None

        for _, config in self.entries:
            self.append(ListItem(Label(self._config_label(config, available))))

        if previous_index is not None and previous_index < len(self.entries):
            # Deferred, not set inline here - append() schedules a mount
            # rather than completing it synchronously, so setting index
            # immediately fires ListView's own watch_index against nodes
            # that aren't actually attached yet. It still ends up with
            # the right *value*, but the "highlight the new node" side
            # effect inside that watcher silently no-ops against the
            # not-yet-mounted node and never gets a second chance to run.
            self.call_after_refresh(setattr, self, "index", previous_index)

    def _config_label(self, config: Configuration, available: int | None) -> Text:
        """config's name, plus its total assigned-sample size if it has
        any - styled `bold red` if it's known to be too big to send
        (available is not None and it exceeds it), plain `dim` otherwise
        (including when there's nothing connected to judge it against -
        showing the size is still useful even with no verdict attached).
        """
        label = Text(config.name)
        size_bytes = device.configuration_size_bytes(config)
        if size_bytes:
            too_large = available is not None and size_bytes > available
            label.append("  " + device.human_bytes(size_bytes), style="bold red" if too_large else "dim")
        return label

    @property
    def highlighted_configuration(self) -> Configuration | None:
        if self.index is None or not self.entries:
            return None
        return self.entries[self.index][1]

    def action_new_configuration(self) -> None:
        def handle_result(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            name, description = result
            now = datetime.now()
            config = Configuration(
                name=name, description=description, created_at=now, modified_at=now
            )
            path = save_configuration(config, self.configurations_dir)
            self.refresh_list()
            # Immediately active in the assignment grid too - creating a
            # configuration and then having to separately Enter it before
            # anything can be assigned to it would be a pointless extra
            # step, and per AssignmentGrid's docstring there's no implicit
            # scratch configuration to assign into in the meantime.
            self.post_message(self.Opened(path, config))

        self.app.push_screen(NewConfigurationModal(), handle_result)

    def action_clone_selected(self) -> None:
        if self.index is None or not self.entries:
            return
        _, config = self.entries[self.index]

        def handle_result(confirmed: bool) -> None:
            if not confirmed:
                return
            now = datetime.now()
            clone = Configuration(
                name=f"Copy of {config.name}",
                description=config.description,
                created_at=now,
                modified_at=now,
                assignments=dict(config.assignments),
            )
            save_configuration(clone, self.configurations_dir)
            self.refresh_list()

        self.app.push_screen(ConfirmCloneModal(config.name), handle_result)

    def action_delete_selected(self) -> None:
        if self.index is None or not self.entries:
            return
        path, config = self.entries[self.index]

        def handle_result(confirmed: bool) -> None:
            if confirmed:
                delete_configuration(path)
                self.refresh_list()

        self.app.push_screen(ConfirmDeleteModal(config.name), handle_result)

    def action_send_to_device(self) -> None:
        if self.index is None or not self.entries:
            return
        _, config = self.entries[self.index]
        if not config.assignments:
            self.app.notify("No assignments to send.", severity="warning")
            return

        # getattr, not a direct attribute access - ShmampleApp sets
        # device_state, but this widget is also mounted standalone (see
        # tests/test_config_list.py's plain App), which has no such
        # attribute at all. Treat "no app-level device state yet" the
        # same as "not connected", not as a crash.
        state = getattr(self.app, "device_state", None)
        if state is None or not state.connected or state.mount is None:
            self.app.notify(
                "P-6 not connected - connect and mount it before sending.", severity="warning"
            )
            return
        if state.mode != device.MODE_IMPORT:
            self.app.notify(device.IMPORT_MODE_INSTRUCTIONS, severity="warning")
            return

        space = device.check_available_space(config, state.mount)
        if not space.fits:
            self.app.notify(
                f"'{config.name}' needs ~{device.human_bytes(space.needed_bytes)}, but only "
                f"~{device.human_bytes(space.free_bytes)} is available on the device even once "
                "its IMPORT folder is cleared - this configuration won't fit.",
                severity="warning",
            )
            return

        warnings = [
            f"{risk.bank}{risk.pad} '{Path(risk.sample_path).name}' "
            f"(~{risk.actual_seconds:.1f}s, ~{risk.max_seconds:.1f}s fits)"
            for risk in device.truncation_risks(config)
        ]

        def handle_result(confirmed: bool) -> None:
            if not confirmed:
                return
            # Not a notify() toast - those time out on a fixed schedule
            # regardless of whether the send has actually finished (a
            # real report: "the pop-up is disappearing before it's
            # finished" - a multi-file USB copy can easily outlast a
            # toast's default lifetime). `loading` is Textual's own
            # persistent-until-cleared indicator: a spinner overlaid on
            # this pane that only goes away when _send's finally clears
            # it, however long that actually takes.
            self.loading = True
            self.run_worker(
                self._send(config, state.mount), exclusive=True, group="send", name="send"
            )

        self.app.push_screen(
            ConfirmSendModal(config.name, len(config.assignments), warnings), handle_result
        )

    async def _send(self, config: Configuration, mount: Path) -> None:
        try:
            # A plain file copy over what may be a slow USB-mounted
            # volume - asyncio.to_thread rather than calling
            # send_configuration directly, so it doesn't block the
            # whole UI event loop for however long that takes (the
            # original synchronous version did exactly that - "the ui
            # stalled while performing the copy").
            result = await asyncio.to_thread(device.send_configuration, config, mount)
        finally:
            self.loading = False

        if result.missing:
            summary = f"Sent {result.sent} sample(s); {len(result.missing)} missing and skipped."
            concerning = True
        else:
            summary = f"Sent {result.sent} sample(s) to the device."
            concerning = False

        # send_configuration's own fsyncing only makes the *data*
        # durable - the manual's own import flow still requires a clean
        # eject before power-cycling into [KYBD] (see
        # 09-save-assignments.md's "files are gone on remount" report:
        # leaving this as a manual step the user has to remember was
        # exactly what went wrong). Doing it here as part of the send
        # closes that gap rather than just fsyncing and hoping.
        if await device.unmount(mount):
            message = f"{summary} Safely ejected - you can power-cycle the device now."
            state = getattr(self.app, "device_state", None)
            if state is not None:
                self.app.device_state = await device.detect_device_state_async()
                self.refresh_list()
        else:
            message = (
                f"{summary} Couldn't safely eject automatically - eject it yourself "
                "before power-cycling, or the import may not see everything."
            )
            concerning = True

        self.app.notify(message, severity="warning" if concerning else "information")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.last_opened = self.highlighted_configuration
        if self.index is not None and self.entries:
            path, config = self.entries[self.index]
            self.post_message(self.Opened(path, config))
