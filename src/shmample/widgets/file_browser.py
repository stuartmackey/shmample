import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Tree
from textual.widgets._tree import TOGGLE_STYLE  # no public re-export of this small style constant
from textual.widgets.tree import TreeNode

from shmample import settings as settings_module
from shmample.audio import NoPlayerFoundError, Previewer
from shmample.device import PAD_NUMBERS
from shmample.widgets.assignment_grid import AssignmentGrid, BankPickerModal, PadPickerModal
from shmample.widgets.directory_picker import DirectoryPickerModal
from shmample.widgets.vim_navigation import VimGoToTopAndBottom


def _contains_wav(directory: Path) -> bool:
    """Recursively check for a .wav anywhere under directory, stopping as
    soon as one is found rather than walking the whole subtree.

    Runs once per folder as it's revealed in the tree, trading away part
    of the lazy-loading benefit - a folder with genuinely nothing valid
    inside still needs its whole subtree walked to prove that.
    """
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.lower().endswith(".wav"):
                return True
            if entry.is_dir(follow_symlinks=False) and _contains_wav(Path(entry.path)):
                return True
    except OSError:
        return False
    return False


@dataclass
class Entry:
    """Attaches filesystem info to a FileBrowser node - same idea as
    DirectoryTree's own DirEntry, just not reusable here since FileBrowser
    no longer subclasses DirectoryTree (see FileBrowser's own docstring
    for why)."""

    path: Path
    loaded: bool = False


class FileBrowser(Tree[Entry], VimGoToTopAndBottom):
    """Browses every configured samples directory, each shown as its own
    top-level root node (11-sample-paths.md) - folders and .wav files
    only, same filtering as before (see filter_paths/_contains_wav).

    Deliberately a plain Tree, not a DirectoryTree, despite looking a lot
    like one: DirectoryTree hard-codes a *single* root path (`self.path`,
    set once at construction) as the thing its lazy-loading machinery
    reloads - retrofitting that for several independent, addable/
    removable root paths meant fighting private, version-specific
    internals (`_load_queue`, `_loader`, `_add_to_load_queue`) for no
    real benefit over just rolling the (much smaller) lazy-load-on-expand
    logic here directly. self.root itself stays hidden (show_root=False)
    and unused as data - each configured directory is a direct child of
    it instead, which is what makes multiple "root nodes" possible at
    all: Tree only ever has the one real root, but it can have any number
    of children, and with the root itself invisible those children render
    as if they were roots.

    Only one configured root is expanded at a time (accordion, per the
    brief) - expanding one collapses whichever other root was expanded
    (see on_tree_node_expanded/on_tree_node_collapsed). Nested folders
    below the open root can still expand/collapse freely among
    themselves; the accordion only applies at the root level.

    Tree has no left/right cursor concept (it's not a grid), so h/l map to
    the nearest vim-flavoured equivalents - jump to parent, toggle node -
    rather than a direct equivalent of DataTable's cursor_left/cursor_right.

    ICON_NODE/ICON_NODE_EXPANDED/ICON_FILE default to colour emoji
    (folder/file glyphs whose colour is baked into the terminal's emoji
    font and can't be restyled via CSS/theme). Nerd Font glyphs are plain
    text characters instead, so they inherit whatever colour the
    directory-tree--folder/--file component styles give them - here,
    that's just the theme's normal foreground, same as everything else.
    Every visible file is a .wav under filter_paths below, so one file
    icon (rather than per-extension icons) is enough.
    """

    ICON_NODE = " "  #  nf-fa-folder
    ICON_NODE_EXPANDED = " "  #  nf-fa-folder_open
    ICON_FILE = " "  #  nf-fa-file_audio_o

    COMPONENT_CLASSES = {
        "directory-tree--extension",
        "directory-tree--file",
        "directory-tree--folder",
        "directory-tree--hidden",
    }

    DEFAULT_CSS = """
    FileBrowser {
        scrollbar-size-vertical: 1;

        & > .directory-tree--folder {
            text-style: bold;
        }

        & > .directory-tree--extension {
            text-style: italic;
        }

        & > .directory-tree--hidden {
            text-style: dim;
        }
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("h", "cursor_parent", "Parent (vim)", show=False),
        Binding("l", "toggle_node", "Expand/collapse (vim)", show=False),
        Binding("p", "preview_cursor_node", "Preview", show=False),
        Binding("a", "start_assign", "Assign"),
        Binding("A", "add_samples_directory", "Add path"),
        Binding("D", "remove_samples_directory", "Remove path"),
        # Replaces Tree's own "space" (toggle_node) entirely, not just
        # for files - action_toggle_select_or_node below falls back to
        # the original expand/collapse behaviour for a folder.
        Binding("space", "toggle_select_or_node", "Select"),
    ] + VimGoToTopAndBottom.BINDINGS

    def __init__(
        self,
        samples_directories: list[Path],
        settings_path: Path | None = None,
        *args,
        **kwargs,
    ) -> None:
        # Set before super().__init__() - Tree's own constructor measures
        # the root node's initial label width, which calls render_label
        # (below) synchronously before this method gets to set anything
        # else, and render_label reads self.selected. Ordered (not a set)
        # so multi-assign fills pads in the order samples were picked,
        # not alphabetically/by tree position.
        self.selected: list[TreeNode] = []
        super().__init__("Samples", *args, **kwargs)
        self.show_root = False
        # Resolved at call time, not a mutable default parameter - same
        # reasoning as ConfigList/AssignmentGrid's own configurations_dir,
        # so tests can redirect persistence to a tmp_path.
        self.settings_path = (
            settings_path if settings_path is not None else settings_module.SETTINGS_PATH
        )
        self.samples_directories = list(samples_directories)
        self.last_previewed: Path | None = None
        self.preview_error: str | None = None
        self.previewer = Previewer()
        # Which root node (direct child of self.root) is currently the
        # one expanded, if any - tracked explicitly rather than scanning
        # children each time, since collapsing it is exactly what needs
        # doing on the *next* expand elsewhere (see on_tree_node_expanded).
        self._expanded_root_node: TreeNode[Entry] | None = None
        for directory in self.samples_directories:
            self._add_root_node(directory)

    def _add_root_node(self, directory: Path) -> TreeNode[Entry]:
        return self.root.add(str(directory), data=Entry(directory), allow_expand=True)

    def filter_paths(self, paths):
        return [
            p
            for p in paths
            if p.suffix.lower() == ".wav" or (p.is_dir() and _contains_wav(p))
        ]

    def _scan_directory(self, directory: Path) -> list[Path]:
        """Runs in a thread (see on_tree_node_expanded) - iterdir() and
        _contains_wav's own os.scandir walk are both blocking calls."""
        try:
            return sorted(
                self.filter_paths(directory.iterdir()),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return []

    async def _load(self, node: TreeNode[Entry]) -> None:
        entry = node.data
        if entry is None or entry.loaded:
            return
        entry.loaded = True
        children = await asyncio.to_thread(self._scan_directory, entry.path)
        node.remove_children()
        for path in children:
            node.add(str(path.name), data=Entry(path), allow_expand=path.is_dir())

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded[Entry]) -> None:
        node = event.node
        if node.parent is self.root:
            if self._expanded_root_node is not None and self._expanded_root_node is not node:
                self._expanded_root_node.collapse()
            self._expanded_root_node = node
        await self._load(node)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[Entry]) -> None:
        if event.node is self._expanded_root_node:
            self._expanded_root_node = None

    # Recolours the label in place rather than prefixing a marker (e.g.
    # "✓ ") - a prefix shifts every filename in the tree a couple of
    # columns to the right whenever a selection changes, which reads as
    # the list itself moving rather than a selection state changing.
    SELECTED_STYLE = "bold green"

    def render_label(self, node: TreeNode[Entry], base_style: Style, style: Style) -> Text:
        node_label = node._label.copy()
        node_label.stylize(style)

        if self.is_mounted:
            if node.allow_expand:
                prefix = (
                    self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE,
                    base_style + TOGGLE_STYLE,
                )
                node_label.stylize_before(
                    self.get_component_rich_style("directory-tree--folder", partial=True)
                )
            else:
                prefix = (self.ICON_FILE, base_style)
                node_label.stylize_before(
                    self.get_component_rich_style("directory-tree--file", partial=True)
                )
                node_label.highlight_regex(
                    r"\..+$",
                    self.get_component_rich_style("directory-tree--extension", partial=True),
                )
            if node_label.plain.startswith("."):
                node_label.stylize_before(
                    self.get_component_rich_style("directory-tree--hidden", partial=True)
                )
            node_label = Text.assemble(prefix, node_label)

        if node in self.selected:
            node_label.stylize(self.SELECTED_STYLE)
        return node_label

    def action_toggle_select_or_node(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.data is not None and not node.allow_expand:
            if node in self.selected:
                self.selected.remove(node)
                node.refresh()
            elif len(self.selected) >= len(PAD_NUMBERS):
                # A bank only has this many pads - capped at selection
                # time rather than letting the pick grow unbounded and
                # only complaining once "a" is pressed.
                self.app.notify(
                    f"Can't select more than {len(PAD_NUMBERS)} samples - "
                    f"a bank only has {len(PAD_NUMBERS)} pads.",
                    severity="warning",
                )
            else:
                self.selected.append(node)
                node.refresh()
        else:
            self.action_toggle_node()

    def _start_preview(self, path: Path) -> None:
        if not path.is_file():
            return
        self.last_previewed = path
        self.preview_error = None
        # exclusive=True: a new preview kills whatever was already
        # playing, rather than queuing behind it (see Previewer).
        self.run_worker(self._play(path), exclusive=True, group="preview", name="preview")

    async def _play(self, path: Path) -> None:
        try:
            await self.previewer.play(path)
        except NoPlayerFoundError as error:
            self.preview_error = str(error)

    def action_preview_cursor_node(self) -> None:
        node = self.cursor_node
        if node is not None and node.data is not None and not node.allow_expand:
            self._start_preview(node.data.path)

    def on_tree_node_selected(self, event: Tree.NodeSelected[Entry]) -> None:
        node = event.node
        if node.data is not None and not node.allow_expand:
            self._start_preview(node.data.path)

    def action_start_assign(self) -> None:
        grid = self.app.query_one("#assignments", AssignmentGrid)
        if grid.configuration is None:
            self.app.notify(
                "Pick or create a configuration before assigning samples.",
                severity="warning",
            )
            return

        if self.selected:
            self._start_assign_selection()
            return

        node = self.cursor_node
        if node is None or node.data is None or node.allow_expand:
            return
        self._start_assign_single(node.data.path)

    def _start_assign_single(self, path: Path) -> None:
        def handle_bank(bank: str | None) -> None:
            if bank is None:
                return

            def handle_pad(pad: str | None) -> None:
                if pad is None:
                    return
                self.app.query_one("#assignments", AssignmentGrid).assign(bank, pad, path)

            self.app.push_screen(PadPickerModal(path.name, bank), handle_pad)

        self.app.push_screen(BankPickerModal(f"'{path.name}'"), handle_bank)

    def _start_assign_selection(self) -> None:
        # Snapshotted up front: handle_bank below clears self.selected
        # once the assignment's done, but still needs the original nodes
        # afterwards to refresh each one's now-stale checkmark.
        nodes = list(self.selected)
        paths = [node.data.path for node in nodes]

        def handle_bank(bank: str | None) -> None:
            if bank is None:
                return
            grid = self.app.query_one("#assignments", AssignmentGrid)
            # No "too many selected" handling needed here - capped at
            # selection time in action_toggle_select_or_node, so paths
            # can never exceed len(PAD_NUMBERS) by the time we get here.
            grid.assign_many(bank, paths)
            self.selected.clear()
            for node in nodes:
                node.refresh()

        self.app.push_screen(BankPickerModal(f"{len(paths)} selected samples"), handle_bank)

    def action_add_samples_directory(self) -> None:
        def handle_result(directory: Path | None) -> None:
            if directory is None or directory in self.samples_directories:
                return
            self.samples_directories.append(directory)
            self._persist_samples_directories()
            self._add_root_node(directory)

        self.app.push_screen(DirectoryPickerModal(Path.home()), handle_result)

    def action_remove_samples_directory(self) -> None:
        node = self.cursor_node
        if node is None or node.parent is not self.root or node.data is None:
            return  # only meaningful on a root path itself, not a file/subfolder under it
        self.samples_directories.remove(node.data.path)
        self._persist_samples_directories()
        if self._expanded_root_node is node:
            self._expanded_root_node = None
        node.remove()

    def _persist_samples_directories(self) -> None:
        settings_module.save_settings(
            settings_module.Settings(samples_directories=list(self.samples_directories)),
            self.settings_path,
        )

    def go_to_top(self) -> None:
        self.action_scroll_home()

    def go_to_bottom(self) -> None:
        self.action_scroll_end()
