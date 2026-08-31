from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical

from shmample import config_store
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser

# How long the cursor has to sit still on a highlighted sample before its
# preview (stat + duration/format probe + waveform decode, see
# PreviewInfo.show) actually loads - scrolling quickly through a list
# would otherwise generate one of these, synchronously on the UI thread,
# per item briefly passed over, which is what made scrolling feel
# sluggish. Defined here (rather than app.py, which actually uses it for
# FileBrowser/HoldingArea preview debouncing) and re-exported, since
# duplicate_review.py needs it too and importing from app.py would be
# circular - app.py already imports DuplicateReviewScreen.
PREVIEW_DEBOUNCE_SECONDS = 0.15


class MainColumn(Vertical):
    """Device status and pack list, stacked above the file browser in one
    column - lazygit-style (status/branches above files), not a 2x2 grid.
    See 06-configuration-list.md for why.

    Tags, Holding, and Preview all used to live here too - moved out to
    their own column (see app.py's compose) so packs/samples could have
    the first column to themselves and Preview could span the width of
    the other two instead of being squeezed under Samples. Their various
    cross-talk with this column's widgets (tag filtering, folder-scoping,
    refreshing the tag list after a tag, showing a highlighted sample in
    Preview) now all happens at the App level instead, since none of them
    are descendants of this widget any more for those messages to bubble
    through."""

    # :focus border colour is shared across every pane (here, DevicePanel)
    # so "which pane is active" reads the same way everywhere, not just in
    # the ones that happen to live in this column.
    DEFAULT_CSS = """
    MainColumn {
        width: 1fr;
        max-width: 33%;
        height: 1fr;
    }
    MainColumn > ConfigList {
        height: 1fr;
        border: round $foreground;
    }
    MainColumn > ConfigList:focus {
        border: round $primary;
    }
    MainColumn > FileBrowser {
        height: 3fr;
        border: round $foreground;
    }
    MainColumn > FileBrowser:focus {
        border: round $primary;
    }
    """

    def __init__(
        self,
        samples_directories: list[Path],
        configurations_dir: Path | None = None,
        settings_path: Path | None = None,
        db_path: Path | None = None,
        directory_aliases: dict[Path, str] | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.samples_directories = samples_directories
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
        )
        self.settings_path = settings_path
        self.db_path = db_path
        self.directory_aliases = directory_aliases

    def compose(self) -> ComposeResult:
        device_panel = DevicePanel(id="device")
        device_panel.border_title = "[1] Device"
        # Parked, not deleted - per 03-handling-multiple-devices.md, the
        # sample-management side of the app doesn't need the device pane
        # right now (that's the separate device-configuration screen this
        # task doesn't build yet). Still mounted so ShmampleApp's on_mount/
        # _poll_device device_state handling keeps working unchanged -
        # display:none only affects layout/paint, not the DOM. Same
        # reasoning as AssignmentGrid's own display=False in app.py.
        device_panel.display = False
        yield device_panel

        configs = ConfigList(self.configurations_dir, id="packs")
        configs.border_title = "[2] Packs"
        yield configs

        files = FileBrowser(
            self.samples_directories,
            self.settings_path,
            self.db_path,
            self.configurations_dir,
            self.directory_aliases,
            id="files",
        )
        files.border_title = "[3] Samples"
        yield files
