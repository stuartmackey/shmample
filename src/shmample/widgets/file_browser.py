import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Tree
from textual.widgets._tree import TOGGLE_STYLE  # no public re-export of this small style constant
from textual.widgets.tree import TreeNode

from shmample import auto_tag, sample_store, tag_store
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
    inside still needs its whole subtree walked to prove that. Used when
    there's no tag filter active - see FileBrowser.filter_paths, and
    tag_store.any_sample_under_matches_all_tags for the filtered
    equivalent (a single SQL query, not a filesystem walk, since it also
    needs each file's tags rather than just its existence).
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

    "." on a folder narrows the displayed root(s) down to just that
    subfolder (01-auto-tagging.md's "focusing a subfolder") - a view-level
    change only, `self.samples_directories` (the persisted config) is
    untouched. `_root_focus_stack` remembers what was displayed before
    each narrowing, so "h" pressed with nowhere left to go within the
    current scope (see action_cursor_parent) pops back out one level at a
    time, same "re-root up once you hit the top" idea as
    `_DirsOnlyDirectoryTree.action_cursor_parent` in directory_picker.py.
    Adding/removing a configured samples directory is disabled while
    focused (see check_action) - both would otherwise mutate the real
    config from within what's meant to be a temporary, view-only scope.

    `set_tag_filter` applies the tag pane's space-selected tags as an AND
    filter (see filter_paths) - a file has to carry every filtered tag to
    show up, and a folder has to have at least one such file anywhere
    beneath it, or it's hidden entirely rather than shown empty.

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
        # Same action as Tree's own built-in "enter" binding (select_cursor)
        # - overridden only to make it visible in the footer, since
        # otherwise there's no hint at all that return plays the
        # highlighted sample (it still just expands/collapses a folder).
        Binding("enter", "select_cursor", "Preview"),
        Binding("a", "start_assign", "Assign"),
        Binding("A", "add_samples_directory", "Add path"),
        Binding("D", "remove_samples_directory", "Remove path"),
        Binding("t", "auto_tag_cursor_node", "Auto-tag"),
        Binding(".", "focus_cursor_folder", "Focus folder"),
        # Replaces Tree's own "space" (toggle_node) entirely, not just
        # for files - action_toggle_select_or_node below falls back to
        # the original expand/collapse behaviour for a folder.
        Binding("space", "toggle_select_or_node", "Select"),
    ] + VimGoToTopAndBottom.BINDINGS

    class Tagged(Message):
        """Posted after `t` auto-tags the cursor node (file or folder) -
        lets MainColumn refresh the tag pane and re-show the current
        preview without FileBrowser needing to know about either."""

    class RootFocusChanged(Message):
        """Posted whenever the displayed root(s) change via "."/the
        focus-popping side of "h" (see _rebuild_roots) - lets MainColumn
        re-scope the tag pane to FileBrowser's own focused_root."""

    def __init__(
        self,
        samples_directories: list[Path],
        settings_path: Path | None = None,
        db_path: Path | None = None,
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
        # Same reasoning, shared database file - see TagBrowser's own
        # db_path for why this falls back to sample_store's attribute
        # rather than a locally-imported copy of it.
        self.db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH
        self.samples_directories = list(samples_directories)
        self.last_previewed: Path | None = None
        self.preview_error: str | None = None
        self.previewer = Previewer()
        # Which root node (direct child of self.root) is currently the
        # one expanded, if any - tracked explicitly rather than scanning
        # children each time, since collapsing it is exactly what needs
        # doing on the *next* expand elsewhere (see on_tree_node_expanded).
        self._expanded_root_node: TreeNode[Entry] | None = None
        # Each entry is the list of root paths that were displayed just
        # before a "." narrowed the view further - see
        # action_focus_cursor_folder/action_cursor_parent. Empty means
        # "showing the full configured list", not "focused".
        self._root_focus_stack: list[list[Path]] = []
        # AND filter from the tag pane's space-selected tags (see
        # set_tag_filter/filter_paths) - empty means "no filter".
        self.tag_filter: set[str] = set()
        for directory in self.samples_directories:
            self._add_root_node(directory)

    def _add_root_node(self, directory: Path) -> TreeNode[Entry]:
        return self.root.add(str(directory), data=Entry(directory), allow_expand=True)

    def _display_roots(self, paths: list[Path]) -> None:
        """Replaces whatever's currently displayed at the root level with
        `paths` - used when the root(s) themselves actually change (see
        _rebuild_roots). Never touches `self.samples_directories`."""
        self.root.remove_children()
        self._expanded_root_node = None
        nodes = [self._add_root_node(path) for path in paths]
        if not nodes:
            return
        self.move_cursor(nodes[0])
        if len(nodes) == 1:
            # A freshly focused (or popped-back-to-still-focused) single
            # root expands straight away - the point of focusing is to see
            # into it immediately, not land on a still-collapsed node that
            # looks like "." did nothing.
            nodes[0].expand()

    def _rebuild_roots(self, paths: list[Path]) -> None:
        """Same as _display_roots, but for an actual change of *which*
        root(s) are displayed - posts RootFocusChanged so MainColumn
        re-scopes the tag pane."""
        self._display_roots(paths)
        self.post_message(self.RootFocusChanged())

    def set_tag_filter(self, tags: set[str]) -> None:
        """Applies `tags` as an AND filter (must carry every one) over the
        sample tree - see filter_paths. The roots themselves aren't
        changing here (unlike _display_roots), so this re-scans in place
        rather than tearing the whole tree down and rebuilding it -
        collapsing every previously-expanded folder back to the top just
        because the filter changed would look like the browser "lost" the
        samples that should still be there once the filter's cleared
        again, rather than just re-showing them.
        """
        self.tag_filter = set(tags)
        snapshot = self._expansion_snapshot(self.root)
        self.run_worker(
            self._reapply_tag_filter(snapshot),
            exclusive=True,
            group="tag-filter",
            name="tag-filter",
        )

    def _expansion_snapshot(self, node: TreeNode[Entry]) -> dict[Path, dict]:
        """Maps each of `node`'s currently-loaded children to its own
        snapshot, recursively - the "what was expanded" record
        _reapply_tag_filter restores after re-scanning from scratch."""
        return {
            child.data.path: self._expansion_snapshot(child)
            for child in node.children
            if child.data is not None and child.data.loaded
        }

    async def _reapply_tag_filter(self, snapshot: dict[Path, dict]) -> None:
        for node in list(self.root.children):
            child_snapshot = snapshot.get(node.data.path)
            if child_snapshot is not None:
                await self._apply_expansion_snapshot(node, child_snapshot)

    async def _apply_expansion_snapshot(
        self, node: TreeNode[Entry], snapshot: dict[Path, dict]
    ) -> None:
        """Re-scans `node`'s children fresh against the current filter,
        then re-expands and recurses into whichever ones `snapshot` says
        were expanded before - restoring depth rather than collapsing
        back to the top just because the filter changed."""
        node.data.loaded = False
        await self._load(node)
        for child_node in node.children:
            child_snapshot = snapshot.get(child_node.data.path)
            if child_snapshot is not None:
                child_node.expand()
                await self._apply_expansion_snapshot(child_node, child_snapshot)

    @property
    def focused_root(self) -> Path | None:
        """The single folder currently focused on via "." (see
        _root_focus_stack), or None when showing the full configured list
        - what MainColumn scopes the tag pane to."""
        if not self._root_focus_stack:
            return None
        return self.root.children[0].data.path

    def action_focus_cursor_folder(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None or not node.allow_expand:
            return
        if node.parent is self.root and len(self.root.children) == 1:
            return  # already the sole displayed root - nothing to narrow
        current_roots = [child.data.path for child in self.root.children]
        self._root_focus_stack.append(current_roots)
        self._rebuild_roots([node.data.path])

    def action_cursor_parent(self) -> None:
        node = self.cursor_node
        if node is not None and node.parent is self.root and self._root_focus_stack:
            self._rebuild_roots(self._root_focus_stack.pop())
            return
        super().action_cursor_parent()

    def filter_paths(self, paths):
        paths = list(paths)
        wav_files = [p for p in paths if p.suffix.lower() == ".wav"]
        # One batched lookup for every wav file in this directory, not one
        # per file (see tag_store.tags_for_samples) - only needed at all
        # once a tag filter is active.
        tags_by_path = tag_store.tags_for_samples(wav_files, self.db_path) if self.tag_filter else {}
        return [
            p
            for p in paths
            if (
                p.suffix.lower() == ".wav"
                and self.tag_filter.issubset(tags_by_path.get(str(p), set()))
            )
            or (p.is_dir() and self._directory_matches_filter(p))
        ]

    def _directory_matches_filter(self, directory: Path) -> bool:
        """Whether `directory` still belongs in the tree - has a .wav
        anywhere beneath it (no filter), or, with a tag filter active, has
        a .wav anywhere beneath it carrying every filtered tag (hiding a
        folder with nothing matching, rather than showing it empty)."""
        if not self.tag_filter:
            return _contains_wav(directory)
        return tag_store.any_sample_under_matches_all_tags(directory, self.tag_filter, self.db_path)

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

    def on_focus(self, event: events.Focus) -> None:
        # Tree's own cursor starts at -1 (nothing highlighted) until the
        # first arrow/vim-key press - jumping here via a numbered pane
        # shortcut (see app.py) would otherwise focus the pane but show
        # no highlighted row at all. Only kicks in on that untouched
        # state, not every focus - once the cursor's actually somewhere,
        # tabbing away and back shouldn't reset it back to the top.
        if self.cursor_line == -1 and self.root.children:
            self.move_cursor(self.root.children[0])

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Entry]) -> None:
        # check_action's "remove_samples_directory" answer depends on
        # which node the cursor's on - tell the footer to re-ask as it
        # moves, same as DevicePanel does when its own state changes.
        self.refresh_bindings()

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

    def action_auto_tag_cursor_node(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data.path

        if node.allow_expand:
            # A folder's worth of samples can genuinely take a while (see
            # 01-auto-tagging.md's "long running process" note) - run it
            # off the UI thread with a persistent spinner, same pattern as
            # ConfigList's own device send, rather than freezing the tree
            # for however long the walk takes.
            self.loading = True
            self.border_subtitle = "Auto-tagging..."
            self.run_worker(
                self._auto_tag_folder(path), exclusive=True, group="auto-tag", name="auto-tag"
            )
        else:
            tags = auto_tag.tag_file(path, self.db_path)
            if tags:
                self.app.notify(f"Tagged '{path.name}': {', '.join(sorted(tags))}")
            else:
                self.app.notify(
                    f"No naming-convention tags found for '{path.name}'.", severity="warning"
                )
            self.post_message(self.Tagged())

    # How often (in files processed) to push a progress update to the UI
    # during a folder tag run - frequent enough to look alive, far short
    # of updating on every single file, which across a library the size
    # of a real sample pack would mean tens of thousands of cross-thread
    # calls for no visible benefit.
    TAGGING_PROGRESS_INTERVAL = 50

    async def _auto_tag_folder(self, path: Path) -> None:
        def on_file_tagged(file_path: Path, tags: set[str], index: int, total: int) -> None:
            if index == total or index % self.TAGGING_PROGRESS_INTERVAL == 0:
                # Called from tag_folder's worker thread (asyncio.to_thread
                # runs it entirely off the event loop) - call_from_thread
                # is the only safe way back onto the UI thread from here.
                self.app.call_from_thread(self._set_tagging_progress, index, total)

        try:
            count = await asyncio.to_thread(
                auto_tag.tag_folder, path, self.db_path, on_file_tagged
            )
        finally:
            self.loading = False
            self.border_subtitle = ""
        noun = "sample" if count == 1 else "samples"
        self.app.notify(f"Auto-tagged {count} {noun} under '{path.name}'.")
        self.post_message(self.Tagged())

    def _set_tagging_progress(self, index: int, total: int) -> None:
        self.border_subtitle = f"Auto-tagging... {index}/{total}"

    def action_add_samples_directory(self) -> None:
        def handle_result(directory: Path | None) -> None:
            if directory is None or directory in self.samples_directories:
                return
            self.samples_directories.append(directory)
            self._persist_samples_directories()
            self._add_root_node(directory)

        self.app.push_screen(DirectoryPickerModal(Path.home()), handle_result)

    def _cursor_on_root_path(self) -> TreeNode[Entry] | None:
        """The cursor's node, but only if it's a root path itself (a
        direct child of the hidden self.root) - not a file/subfolder
        under one, where removing "the path" wouldn't be meaningful.

        None while focused on a subfolder (see _root_focus_stack), even
        though the sole displayed root is technically a direct child of
        self.root too - it's not necessarily (or even usually) one of the
        actual configured samples_directories, so removing "the path"
        isn't meaningful there either.
        """
        if self._root_focus_stack:
            return None
        node = self.cursor_node
        if node is not None and node.parent is self.root and node.data is not None:
            return node
        return None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "remove_samples_directory":
            return self._cursor_on_root_path() is not None
        if action == "add_samples_directory":
            return not self._root_focus_stack
        return True

    def action_remove_samples_directory(self) -> None:
        node = self._cursor_on_root_path()
        if node is None:
            return
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
