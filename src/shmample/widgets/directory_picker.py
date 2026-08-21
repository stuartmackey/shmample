from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree


class _DirsOnlyDirectoryTree(DirectoryTree):
    """Plain DirectoryTree with files filtered out entirely - unlike
    FileBrowser, this one's only ever used to pick a folder, so a file
    showing up in it would just be dead weight the user can't do
    anything with.

    j/k/h/l live here, not on DirectoryPickerModal - a Binding's action
    runs against whichever DOM node actually owns it, not the focused
    widget it was meant to steer, so vim keys have to be bound directly
    on the tree itself (same as FileBrowser does) rather than on the
    modal wrapping it.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("h", "cursor_parent", "Parent (vim)", show=False),
        Binding("l", "toggle_node", "Expand/collapse (vim)", show=False),
    ]

    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir()]


class DirectoryPickerModal(ModalScreen[Path | None]):
    """Shift+A's folder browser (see FileBrowser.action_add_samples_directory)
    - its own confined DirectoryTree, since this app has no other way to
    point at an arbitrary path than navigating to it. Enter still means
    "expand/collapse" here, matching FileBrowser's own convention
    elsewhere in the app, so "choose this folder" needs a separate key -
    ctrl+s, mirroring NewConfigurationModal's own escape/ctrl+s scheme.
    """

    DEFAULT_CSS = """
    DirectoryPickerModal {
        align: center middle;
    }
    DirectoryPickerModal > Vertical {
        width: 90%;
        max-width: 60%;
        height: 80%;
    }
    DirectoryPickerModal DirectoryTree {
        border: round $success;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "choose", "Choose folder"),
    ]

    def __init__(self, start_directory: Path) -> None:
        super().__init__()
        self._start_directory = start_directory

    def compose(self) -> ComposeResult:
        with Vertical():
            tree = _DirsOnlyDirectoryTree(self._start_directory)
            tree.border_title = "Choose a folder"
            tree.border_subtitle = "ctrl+s: choose  esc: cancel"
            yield tree

    def on_mount(self) -> None:
        self.query_one(DirectoryTree).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_choose(self) -> None:
        tree = self.query_one(DirectoryTree)
        node = tree.cursor_node
        if node is not None and node.data is not None:
            self.dismiss(node.data.path)
        else:
            self.dismiss(self._start_directory)
