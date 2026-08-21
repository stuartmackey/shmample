from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Tree

from shmample import config_store
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.tag_browser import TagBrowser

# How long the cursor has to sit still on a file before its preview
# (stat + duration/format probe + waveform decode, see PreviewInfo.show)
# actually loads - scrolling quickly through the tree would otherwise
# generate one of these, synchronously on the UI thread, per file
# briefly passed over, which is what made scrolling feel sluggish.
PREVIEW_DEBOUNCE_SECONDS = 0.15


class MainColumn(Vertical):
    """Device status, configuration list, file browser, and its preview
    info pane, all stacked in one column - lazygit-style (status/branches
    above files), not a 2x2 grid. See 06-configuration-list.md for why."""

    # :focus border colour is shared across every pane (here, DevicePanel,
    # AssignmentGrid) so "which pane is active" reads the same way
    # everywhere, not just in the ones that happen to live in this column.
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
    MainColumn > #samples-row {
        height: 3fr;
    }
    MainColumn > #samples-row > FileBrowser {
        width: 1fr;
        border: round $foreground;
    }
    MainColumn > #samples-row > FileBrowser:focus {
        border: round $primary;
    }
    MainColumn > #samples-row > TagBrowser {
        width: 1fr;
        border: round $foreground;
    }
    MainColumn > #samples-row > TagBrowser:focus {
        border: round $primary;
    }
    MainColumn > PreviewInfo {
        height: 1fr;
        border: round $foreground;
    }
    MainColumn > PreviewInfo:focus {
        border: round $primary;
    }
    """

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
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
        )
        self.settings_path = settings_path
        self.db_path = db_path
        self._preview_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        device_panel = DevicePanel(id="device")
        device_panel.border_title = "[1] Device"
        yield device_panel

        configs = ConfigList(self.configurations_dir, id="configurations")
        configs.border_title = "[2] Configurations"
        yield configs

        with Horizontal(id="samples-row"):
            files = FileBrowser(
                self.samples_directories, self.settings_path, self.db_path, id="files"
            )
            files.border_title = "[3] Samples"
            yield files

            tags = TagBrowser(self.db_path, id="tags")
            tags.border_title = "[4] Tags"
            yield tags

        preview = PreviewInfo(self.db_path, id="preview")
        preview.border_title = "[5] Preview"
        yield preview

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None

        node = event.node
        preview = self.query_one(PreviewInfo)
        if node.data is not None and not node.allow_expand:
            path = node.data.path
            self._preview_timer = self.set_timer(
                PREVIEW_DEBOUNCE_SECONDS, lambda: preview.show(path)
            )
        else:
            # Cheap (just clears the pane) - no need to debounce this side.
            preview.show(None)

    def on_file_browser_tagged(self, message: FileBrowser.Tagged) -> None:
        self.query_one("#tags", TagBrowser).refresh_list()

        # Re-show whatever's currently highlighted so a just-tagged file's
        # new tags show up in the preview pane immediately, rather than
        # only on the next time it's highlighted.
        node = self.query_one("#files", FileBrowser).cursor_node
        preview = self.query_one(PreviewInfo)
        if node is not None and node.data is not None and not node.allow_expand:
            preview.show(node.data.path)
        else:
            preview.show(None)
