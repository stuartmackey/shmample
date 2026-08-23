from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Footer, ListView

from shmample import device, migrations, sample_store
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.duplicate_review import DuplicateReviewScreen
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.holding_area import HoldingArea
from shmample.widgets.main_column import PREVIEW_DEBOUNCE_SECONDS, MainColumn
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.tag_browser import TagBrowser

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
    # bindings (neither uses digits, and none of the panes bind ctrl+hjkl).
    # Numbered pane jump, lazygit-style, plus vim/tmux-style directional
    # pane movement.
    BINDINGS = [
        Binding("1", "focus_pane('#device')", "Device", show=False),
        Binding("2", "focus_pane('#configurations')", "Configurations", show=False),
        Binding("3", "focus_pane('#files')", "Samples", show=False),
        Binding("4", "focus_pane('#preview')", "Preview", show=False),
        Binding("5", "focus_pane('#tags')", "Tags", show=False),
        Binding("6", "focus_pane('#holding')", "Holding", show=False),
        Binding("7", "focus_pane('#assignments')", "Assignments", show=False),
        # ctrl+h is also bound as plain "backspace": most terminals send
        # the same byte (0x08, or DEL 0x7f) for both, and Textual's
        # legacy ANSI decoding collapses that byte to the "backspace" key
        # rather than "ctrl+h" - only terminals that opt into the Kitty
        # keyboard protocol can tell the two apart. Binding both keeps
        # left-movement working everywhere; harmless elsewhere, since any
        # widget that actually wants backspace for text editing (e.g.
        # Input) claims it before this App-level fallback is ever reached.
        Binding("ctrl+h", "focus_direction('left')", "Pane left", show=False),
        Binding("backspace", "focus_direction('left')", "Pane left", show=False),
        Binding("ctrl+j", "focus_direction('down')", "Pane down", show=False),
        Binding("ctrl+k", "focus_direction('up')", "Pane up", show=False),
        Binding("ctrl+l", "focus_direction('right')", "Pane right", show=False),
        # Capital, not lowercase "u" - DevicePanel already owns lowercase
        # "u" for Unmount (device_panel.py:36), scoped to while that pane
        # is focused; an App-level fallback on the same letter would leak
        # into the footer everywhere else it's not actually being shadowed.
        Binding("U", "review_duplicates", "Duplicates"),
    ]

    # The layout (see MainColumn.compose and ShmampleApp.compose) isn't a
    # regular grid - device/configurations/files/preview stack in one
    # column while tags/holding/assignments are each their own full-height
    # column beside it - so there's no honest geometric "widget in that
    # direction" to compute. Hand-coding the adjacency once here is
    # simpler than teaching a general spatial search about this
    # particular shape.
    PANE_ADJACENCY = {
        "device": {"down": "configurations", "right": "tags"},
        "configurations": {"up": "device", "down": "files", "right": "tags"},
        "files": {"up": "configurations", "down": "preview", "right": "tags"},
        "preview": {"up": "files", "right": "tags"},
        "tags": {"left": "files", "right": "holding"},
        "holding": {"left": "tags", "right": "assignments"},
        "assignments": {"left": "holding"},
    }

    def action_focus_pane(self, selector: str) -> None:
        self.query_one(selector).focus()

    def action_focus_direction(self, direction: str) -> None:
        focused = self.focused
        if focused is None or focused.id is None:
            return
        target = self.PANE_ADJACENCY.get(focused.id, {}).get(direction)
        if target is not None:
            self.query_one(f"#{target}").focus()

    def action_review_duplicates(self) -> None:
        db_path = self.db_path if self.db_path is not None else sample_store.DEFAULT_DB_PATH

        def handle_result(_: None) -> None:
            self.query_one("#tags", TagBrowser).refresh_list()

        self.push_screen(DuplicateReviewScreen(db_path), handle_result)

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
        self._holding_preview_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield MainColumn(
                self.samples_directories,
                self.configurations_dir,
                self.settings_path,
                self.db_path,
                id="main-column",
            )
            tags = TagBrowser(self.db_path, id="tags")
            tags.border_title = "[5] Tags"
            yield tags
            holding = HoldingArea(self.configurations_dir, id="holding")
            holding.border_title = "[6] Holding"
            yield holding
            assignments = AssignmentGrid(self.configurations_dir, id="assignments")
            assignments.border_title = "[7] Assignments"
            # Parked, not deleted - we're trying a "Collect" layout
            # (Samples/Tags/Preview/Holding) with the device-specific
            # "Assign" step (this grid) out of the way for now, per the
            # two-screen-mode direction being explored. Still mounted so
            # ConfigList.Opened/AssignmentGrid.Saved and HoldingArea's own
            # "a" chord (start_assign_single) keep working unchanged -
            # display:none only affects layout/paint, not the DOM.
            assignments.display = False
            yield assignments
        yield Footer()

    async def on_mount(self) -> None:
        # Same None-fallback reasoning as FileBrowser's own db_path -
        # self.db_path is None in real usage (__main__.py never passes it).
        db_path = self.db_path if self.db_path is not None else sample_store.DEFAULT_DB_PATH
        if migrations.is_rescan_pending(db_path):
            self.notify(
                "New functionality needs a rescan - press Shift+R on a folder to update it.",
                severity="warning",
            )

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
        entry = (message.path, message.configuration)
        self.query_one("#assignments", AssignmentGrid).load(entry)
        self.query_one("#holding", HoldingArea).load(entry)

    def on_assignment_grid_saved(self, message: AssignmentGrid.Saved) -> None:
        self.query_one("#configurations", ConfigList).refresh_list()

    def on_holding_area_saved(self, message: HoldingArea.Saved) -> None:
        self.query_one("#configurations", ConfigList).refresh_list()

    # TagBrowser/FileBrowser cross-talk - used to be handled inside
    # MainColumn (see its docstring), back when TagBrowser was one of its
    # descendants. Now that it's a sibling column instead, only the App
    # sits above both, so this is where they have to meet.
    def on_file_browser_tagged(self, message: FileBrowser.Tagged) -> None:
        self.query_one("#tags", TagBrowser).refresh_list()

    def on_file_browser_root_focus_changed(self, message: FileBrowser.RootFocusChanged) -> None:
        browser = self.query_one("#files", FileBrowser)
        self.query_one("#tags", TagBrowser).set_scope(browser.focused_root)

    def on_tag_browser_selection_changed(self, message: TagBrowser.SelectionChanged) -> None:
        tags = self.query_one("#tags", TagBrowser)
        self.query_one("#files", FileBrowser).set_tag_filter(tags.selected_tags)

    # HoldingArea/PreviewInfo cross-talk - same reasoning as the
    # TagBrowser/FileBrowser handlers above: PreviewInfo lives inside
    # MainColumn, HoldingArea is a sibling column, so only the App sits
    # above both. ListView.Highlighted also fires for ConfigList (the
    # other ListView in the tree), hence the id check - it isn't wired to
    # the preview pane.
    def on_list_view_highlighted(self, message: ListView.Highlighted) -> None:
        if message.list_view.id != "holding":
            return
        if self._holding_preview_timer is not None:
            self._holding_preview_timer.stop()
            self._holding_preview_timer = None

        holding = self.query_one("#holding", HoldingArea)
        preview = self.query_one("#preview", PreviewInfo)
        path = holding.cursor_path

        def show_debounced() -> None:
            # The debounce delay is real wall-clock time, not paced by the
            # message pump - a highlight right at app shutdown can still
            # be pending once PreviewInfo's own children are already torn
            # down (is_mounted alone doesn't catch this - it can still be
            # True mid-teardown), so this has to tolerate that rather than
            # assume the widget's still fully there.
            try:
                preview.show(path)
            except NoMatches:
                pass

        if path is not None:
            self._holding_preview_timer = self.set_timer(PREVIEW_DEBOUNCE_SECONDS, show_debounced)
        else:
            preview.show(None)
