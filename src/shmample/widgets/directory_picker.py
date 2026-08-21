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
        # Hidden folders (.config, .cache, .git, ...) are rarely where
        # samples live and clutter every listing once "up a level"
        # reaches somewhere like $HOME, so they're filtered out here
        # alongside files rather than just left for the user to skip
        # past.
        return [p for p in paths if p.is_dir() and not p.name.startswith(".")]

    def action_cursor_parent(self) -> None:
        """Move to the parent node, same as Tree's own action - except
        once the cursor's already on this tree's root, where Tree's
        version has nowhere left to go. Re-roots the tree one level up
        the real filesystem instead, so starting confined to (say) the
        user's home directory doesn't also mean being unable to ever
        reach a sibling like a mounted drive under /run/media/<user>/ -
        repeated use eventually reaches the filesystem root, at which
        point going further up is a no-op (its own parent is itself).
        """
        cursor_node = self.cursor_node
        if cursor_node is not None and cursor_node.parent is not None:
            self.move_cursor(cursor_node.parent, animate=True)
            return
        parent_dir = self.path.parent
        if parent_dir != self.path:
            self.path = parent_dir


class DirectoryPickerModal(ModalScreen[Path | None]):
    """Shift+A's folder browser (see FileBrowser.action_add_samples_directory)
    - its own confined DirectoryTree, since this app has no other way to
    point at an arbitrary path than navigating to it. Enter/space still
    mean "expand/collapse" here, matching FileBrowser's own convention
    elsewhere in the app, so "choose this folder" needs a separate key -
    "a", not ctrl+s (NewConfigurationModal's choice for the same "confirm"
    role): most terminals treat ctrl+s as the XOFF flow-control character
    unless the user has disabled that themselves (`stty -ixon`), so it
    can silently freeze output instead of reaching the app at all.
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
        Binding("a", "choose", "Choose folder"),
    ]

    def __init__(self, start_directory: Path) -> None:
        super().__init__()
        self._start_directory = start_directory

    def compose(self) -> ComposeResult:
        with Vertical():
            tree = _DirsOnlyDirectoryTree(self._start_directory)
            tree.border_title = "Choose a folder"
            tree.border_subtitle = (
                "enter/space: open   h: up a level   a: choose folder   esc: cancel"
            )
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
