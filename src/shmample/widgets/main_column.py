from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Tree

from shmample import config_store
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.preview_info import PreviewInfo


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
    MainColumn > FileBrowser {
        height: 3fr;
        border: round $foreground;
    }
    MainColumn > FileBrowser:focus {
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

    def compose(self) -> ComposeResult:
        device_panel = DevicePanel(id="device")
        device_panel.border_title = "[1] Device"
        yield device_panel

        configs = ConfigList(self.configurations_dir, id="configurations")
        configs.border_title = "[2] Configurations"
        yield configs

        files = FileBrowser(self.samples_directories, self.settings_path, id="files")
        files.border_title = "[3] Samples"
        yield files

        preview = PreviewInfo(id="preview")
        preview.border_title = "[4] Preview"
        yield preview

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        node = event.node
        preview = self.query_one(PreviewInfo)
        if node.data is not None and not node.allow_expand:
            preview.show(node.data.path)
        else:
            preview.show(None)
