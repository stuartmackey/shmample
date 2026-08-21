from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer

from shmample import device
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.main_column import MainColumn

# ansi-dark is one of Textual's built-in themes that render using the
# terminal's own configured palette (ansi_default, ansi_blue, ...) instead
# of fixed truecolor hex, so the UI picks up the terminal's colour scheme.
# Fixed, not user-toggleable - the terminal's own light/dark setting
# already governs how this actually looks, a separate in-app toggle on
# top of that was more confusing than useful.
THEME = "ansi-dark"

# How often to re-check whether the P-6 is still there. Deliberately a
# read-only detect_device_state_async() poll, not detect_or_mount() - a
# poll tick shouldn't go mounting things, only notice that a mount
# vanished (unplugged, or unmounted from outside the app), appeared, or
# is now visible-but-unmounted (see DeviceState.unmounted_device).
DEVICE_POLL_INTERVAL = 2.0


class ShmampleApp(App):
    # Global fallback bindings: Textual checks the focused widget's own
    # BINDINGS first, walking up to the App only if nothing closer claims
    # the key - so these don't clash with ConfigList/FileBrowser's own
    # bindings (neither uses digits). Numbered pane jump, lazygit-style.
    BINDINGS = [
        Binding("1", "focus_pane('#device')", "Device", show=False),
        Binding("2", "focus_pane('#configurations')", "Configurations", show=False),
        Binding("3", "focus_pane('#files')", "Samples", show=False),
        Binding("4", "focus_pane('#tags')", "Tags", show=False),
        Binding("5", "focus_pane('#preview')", "Preview", show=False),
        Binding("6", "focus_pane('#assignments')", "Assignments", show=False),
    ]

    def action_focus_pane(self, selector: str) -> None:
        self.query_one(selector).focus()

    def __init__(
        self,
        samples_directories: list[Path],
        configurations_dir: Path | None = None,
        settings_path: Path | None = None,
        db_path: Path | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.samples_directories = samples_directories
        self.configurations_dir = configurations_dir
        self.settings_path = settings_path
        self.db_path = db_path
        self.theme = THEME
        self.device_state: device.DeviceState | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield MainColumn(
                self.samples_directories,
                self.configurations_dir,
                self.settings_path,
                self.db_path,
                id="main-column",
            )
            assignments = AssignmentGrid(self.configurations_dir, id="assignments")
            assignments.border_title = "[6] Assignments"
            yield assignments
        yield Footer()

    async def on_mount(self) -> None:
        self.device_state = await device.detect_or_mount()
        self.query_one("#device", DevicePanel).show(self.device_state)
        # ConfigList's own on_mount already ran (and rendered) before
        # this device_state was known - refresh it once now so its
        # per-configuration size colouring reflects the real device from
        # the start, not just from the next poll tick onwards.
        self.query_one("#configurations", ConfigList).refresh_list()
        self.set_interval(DEVICE_POLL_INTERVAL, self._poll_device)

    async def _poll_device(self) -> None:
        state = await device.detect_device_state_async()
        if state != self.device_state:
            self.device_state = state
            self.query_one("#device", DevicePanel).show(state)
            # Same reasoning as on_mount above - a connect/disconnect or
            # mode change can flip whether a configuration would fit, so
            # the list's size colouring needs to follow it live.
            self.query_one("#configurations", ConfigList).refresh_list()

    def on_config_list_opened(self, message: ConfigList.Opened) -> None:
        self.query_one("#assignments", AssignmentGrid).load((message.path, message.configuration))

    def on_assignment_grid_saved(self, message: AssignmentGrid.Saved) -> None:
        self.query_one("#configurations", ConfigList).refresh_list()
