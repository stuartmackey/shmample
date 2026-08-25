import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode

from shmample import auto_tag, config_store, library_scan, sample_store, tag_store
from shmample import settings as settings_module
from shmample.audio import NoPlayerFoundError, Previewer
from shmample.widgets.config_list import ConfigList
from shmample.widgets.directory_picker import DirectoryPickerModal
from shmample.widgets.holding_area import HoldingArea
from shmample.widgets.vim_navigation import VimGoToTopAndBottom
from shmample.widgets.vim_option_list import VimOptionList


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


class ConfirmRemovePathModal(ModalScreen[bool]):
    """Confirmation before "D" forgets a configured samples directory - same
    lazygit-style OptionList + detail-pane shape as ConfigList's own
    ConfirmDeleteModal. Called out explicitly because removing a path also
    cascades: every tag on a sample under it is removed (see
    tag_store.remove_tags_under), and every pack referencing one of those
    samples has just that reference stripped (see
    config_store.remove_samples_under) - neither is obvious from "remove
    path" alone, so the detail text says so up front rather than surprising
    the user after the fact."""

    DEFAULT_CSS = """
    ConfirmRemovePathModal {
        align: center middle;
    }
    ConfirmRemovePathModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    ConfirmRemovePathModal OptionList {
        border: round $error;
        height: auto;
    }
    ConfirmRemovePathModal #detail {
        border: round $error;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, directory_name: str) -> None:
        super().__init__()
        self.directory_name = directory_name
        self._details = (
            f"Stop tracking '{self.directory_name}'. Its tags are removed, and any "
            "pack holding or assigning one of its samples has that reference "
            "removed too. Files on disk are untouched.",
            "Keep tracking the path as it is.",
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Remove '{self.directory_name}'", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Remove path"
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


class FolderAssignModal(ModalScreen[str | None]):
    """"a" on a folder (with nothing multi-selected) used to be a silent
    no-op - there was no single obvious meaning for "hold this" applied to
    a whole subtree. This offers the two that actually make sense instead:
    fold every sample under it into whichever pack is already open in
    Holding, or start a brand new pack from just this folder (the same
    flow as ConfigList's ctrl+a, minus having to separately browse to a
    folder it's already sitting on). Same lazygit-style OptionList +
    detail-pane shape as this app's other modals, just with a live choice
    instead of a plain yes/no - "add" is only offered at all when a pack
    is actually open to add to.

    Returns "add", "create", or None (cancelled, including plain escape) -
    never a truthy value for "did nothing", so a caller can treat anything
    but None as "do this now"."""

    DEFAULT_CSS = """
    FolderAssignModal {
        align: center middle;
    }
    FolderAssignModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    FolderAssignModal OptionList {
        border: round $success;
        height: auto;
    }
    FolderAssignModal #detail {
        border: round $success;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, folder_name: str, open_pack_name: str | None) -> None:
        super().__init__()
        self.folder_name = folder_name
        self.open_pack_name = open_pack_name
        self._options: list[Option] = []
        self._details: list[str] = []
        if open_pack_name is not None:
            self._options.append(Option(f"Add to '{open_pack_name}'", id="add"))
            self._details.append(
                f"Recursively add every sample under '{folder_name}' to the "
                f"currently open pack, '{open_pack_name}'."
            )
        self._options.append(Option("Create new pack from folder", id="create"))
        self._details.append(f"Create a brand new pack from every sample under '{folder_name}'.")
        self._options.append(Option("Cancel", id="cancel"))
        self._details.append("Do nothing.")

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(*self._options)
            options.border_title = "Add folder to a pack"
            options.border_subtitle = f"1 of {len(self._details)}"
            yield options
            yield Static(self._details[0], id="detail")

    def on_mount(self) -> None:
        self.query_one(VimOptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        options = event.option_list
        options.border_subtitle = f"{event.option_index + 1} of {options.option_count}"
        self.query_one("#detail", Static).update(self._details[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        self.dismiss(None if option_id == "cancel" else option_id)


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

    ICON_NODE/ICON_NODE_EXPANDED/ICON_FILE are Nerd Font glyphs (colour
    emoji folder/file icons bake their colour into the terminal's emoji
    font and can't be restyled via CSS/theme; Nerd Font glyphs are plain
    text characters, so they take whatever colour the
    directory-tree--folder/--file component styles give them). Written
    as \\uXXXX escapes rather than the literal character - a bare PUA
    codepoint pasted straight into source is invisible in most editors
    and easy to silently mangle into something else (the exact glyphs
    named in these comments used to be plain spaces here). A folder also
    gets its own disclosure chevron ahead of the folder icon, separate
    from the open/closed icon swap - two independent signals for the
    same state reads clearer than relying on the one icon change alone.
    Every visible file is a .wav under filter_paths below, so one file
    icon (rather than per-extension icons) is enough.
    """

    ICON_CHEVRON_COLLAPSED = "\uf0da"  # nf-fa-caret_right
    ICON_CHEVRON_EXPANDED = "\uf0d7"  # nf-fa-caret_down
    ICON_NODE = "\uf07b"  # nf-fa-folder
    ICON_NODE_EXPANDED = "\uf07c"  # nf-fa-folder_open
    ICON_FILE = "\uf1c7"  # nf-fa-file_audio_o

    COMPONENT_CLASSES = {
        "directory-tree--extension",
        "directory-tree--file",
        "directory-tree--folder",
        "directory-tree--hidden",
    }

    DEFAULT_CSS = """
    FileBrowser {
        scrollbar-size-vertical: 1;

        /* Folders already read as folders via their chevron/icon prefix -
        the connecting guide lines just add clutter at this indent width. */
        & > .tree--guides,
        & > .tree--guides-hover,
        & > .tree--guides-selected {
            color: transparent;
        }

        & > .directory-tree--folder {
            color: $secondary;
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
        Binding("a", "start_assign", "Hold"),
        Binding("A", "add_samples_directory", "Add path"),
        Binding("D", "remove_samples_directory", "Remove path"),
        Binding("t", "auto_tag_cursor_node", "Auto-tag"),
        Binding("R", "rescan_cursor_node", "Rescan"),
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

    class PathRemoved(Message):
        """Posted after "D" (confirmed) removes a configured samples
        directory and cascades that into its samples' tags and any pack
        referencing them (see action_remove_samples_directory) - lets the
        App refresh the Tags/Packs panes, and reload the pack currently
        open in Holding/Assignments if the cascade touched it."""

    def __init__(
        self,
        samples_directories: list[Path],
        settings_path: Path | None = None,
        db_path: Path | None = None,
        configurations_dir: Path | None = None,
        *args,
        **kwargs,
    ) -> None:
        # Set before super().__init__() - Tree's own constructor measures
        # the root node's initial label width, which calls render_label
        # (below) synchronously before this method gets to set anything
        # else, and render_label reads self.selected. Ordered (not a set)
        # so a multi-add lands in the holding area in the order samples
        # were picked, not alphabetically/by tree position.
        self.selected: list[TreeNode] = []
        super().__init__("Samples", *args, **kwargs)
        self.show_root = False
        # Narrower than Tree's own default (4) - the chevron/icon prefix on
        # every folder already signals depth, so the full guide width just
        # pushes filenames further right than needed.
        self.guide_depth = 2
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
        # Needed only to cascade a removed samples directory into
        # config_store.remove_samples_under - see
        # action_remove_samples_directory.
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
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
                folder_style = base_style + self.get_component_rich_style(
                    "directory-tree--folder", partial=True
                )
                chevron = (
                    self.ICON_CHEVRON_EXPANDED if node.is_expanded else self.ICON_CHEVRON_COLLAPSED
                )
                icon = self.ICON_NODE_EXPANDED if node.is_expanded else self.ICON_NODE
                prefix = (f"{chevron} {icon} ", folder_style)
                node_label.stylize_before(folder_style)
            else:
                file_style = base_style + self.get_component_rich_style(
                    "directory-tree--file", partial=True
                )
                prefix = (f"{self.ICON_FILE} ", file_style)
                node_label.stylize_before(file_style)
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
        """"a" no longer picks a bank/pad directly - it just adds the
        sample(s) to the configuration's device-agnostic holding area
        (see HoldingArea). Placing a held sample onto an actual pad is a
        separate step, done from the holding area pane itself.

        On a folder, with nothing multi-selected, this instead opens
        FolderAssignModal - there's no single obvious meaning for "hold
        this" applied to a whole subtree, so it asks rather than either
        silently doing nothing (the old behaviour) or guessing. That
        branch doesn't require a pack to already be open (unlike every
        other case here) since "create a new pack from this folder" is
        one of the choices on offer.
        """
        holding = self.app.query_one("#holding", HoldingArea)

        if self.selected:
            if holding.configuration is None:
                self.app.notify(
                    "Pick or create a configuration before adding samples.",
                    severity="warning",
                )
                return
            nodes = list(self.selected)
            added, already_held = holding.add_samples([node.data.path for node in nodes])
            self.selected.clear()
            for node in nodes:
                node.refresh()
            self._notify_added_to_holding(added, already_held)
            return

        node = self.cursor_node
        if node is None or node.data is None:
            return

        if node.allow_expand:
            self._start_folder_assign(node.data.path)
            return

        if holding.configuration is None:
            self.app.notify(
                "Pick or create a configuration before adding samples.",
                severity="warning",
            )
            return
        added, already_held = holding.add_samples([node.data.path])
        self._notify_added_to_holding(added, already_held)

    def _start_folder_assign(self, directory: Path) -> None:
        holding = self.app.query_one("#holding", HoldingArea)
        open_pack_name = (
            holding.configuration.pack.name if holding.configuration is not None else None
        )

        def handle_result(choice: str | None) -> None:
            if choice == "add":
                self.run_worker(
                    self._add_folder_to_holding(directory),
                    exclusive=True,
                    group="folder-assign",
                    name="folder-assign",
                )
            elif choice == "create":
                # Cross-widget, same precedent as HoldingArea reaching
                # into AssignmentGrid directly (action_assign_cursor_item)
                # rather than a round trip through App-level messages -
                # ConfigList already owns the entire "pick a name, scan
                # the folder, save" flow, so this just hands it the folder
                # FileBrowser already has instead of duplicating it here.
                self.app.query_one("#packs", ConfigList).start_new_configuration_from_directory(
                    directory
                )

        self.app.push_screen(FolderAssignModal(directory.name, open_pack_name), handle_result)

    async def _add_folder_to_holding(self, directory: Path) -> None:
        def scan() -> list[Path]:
            # Same rglob("*")+suffix filter as ConfigList._create_from_directory/
            # library_scan.scan_library/auto_tag.tag_folder.
            return sorted(
                p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() == ".wav"
            )

        self.loading = True
        try:
            wav_paths = await asyncio.to_thread(scan)
        finally:
            self.loading = False

        holding = self.app.query_one("#holding", HoldingArea)
        if holding.configuration is None:
            self.app.notify(
                "Pick or create a configuration before adding samples.",
                severity="warning",
            )
            return
        added, already_held = holding.add_samples(wav_paths)
        self._notify_added_to_holding(added, already_held)

    def _notify_added_to_holding(self, added: list[Path], already_held: list[Path]) -> None:
        if not added:
            if already_held:
                subject = (
                    f"'{already_held[0].name}'"
                    if len(already_held) == 1
                    else f"{len(already_held)} samples"
                )
                self.app.notify(f"{subject} already in the holding area.")
            return
        subject = f"'{added[0].name}'" if len(added) == 1 else f"{len(added)} samples"
        message = f"Added {subject} to the holding area."
        if already_held:
            message += f" ({len(already_held)} already there)"
        self.app.notify(message)

    def _root_for(self, node: TreeNode[Entry]) -> Path:
        """The top-level root path `node` descends from - whichever of the
        currently displayed root node(s) is its ancestor. Anchors "how deep
        below the root is this folder" for auto_tag's pack/vendor folder
        tagging (tags_for_path's `root`), so depth is judged against a
        boundary the user actually recognises (a configured samples
        directory, or a "."-focused subfolder), not an arbitrary ancestor.
        """
        while node.parent is not self.root:
            node = node.parent
        return node.data.path

    def action_auto_tag_cursor_node(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        path = node.data.path
        root = self._root_for(node)

        if node.allow_expand:
            # A folder's worth of samples can genuinely take a while (see
            # 01-auto-tagging.md's "long running process" note) - run it
            # off the UI thread with a persistent spinner, same pattern as
            # ConfigList's own device send, rather than freezing the tree
            # for however long the walk takes.
            self.loading = True
            self.border_subtitle = "Auto-tagging..."
            self.run_worker(
                self._auto_tag_folder(path, root), exclusive=True, group="auto-tag", name="auto-tag"
            )
        else:
            tags = auto_tag.tag_file(path, self.db_path, root)
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

    async def _auto_tag_folder(self, path: Path, root: Path) -> None:
        def on_file_tagged(file_path: Path, tags: set[str], index: int, total: int) -> None:
            if index == total or index % self.TAGGING_PROGRESS_INTERVAL == 0:
                # Called from tag_folder's worker thread (asyncio.to_thread
                # runs it entirely off the event loop) - call_from_thread
                # is the only safe way back onto the UI thread from here.
                self.app.call_from_thread(self._set_tagging_progress, index, total)

        try:
            count = await asyncio.to_thread(
                auto_tag.tag_folder, path, self.db_path, on_file_tagged, root
            )
        finally:
            self.loading = False
            self.border_subtitle = ""
        noun = "sample" if count == 1 else "samples"
        self.app.notify(f"Auto-tagged {count} {noun} under '{path.name}'.")
        self.post_message(self.Tagged())

    def _set_tagging_progress(self, index: int, total: int) -> None:
        self.border_subtitle = f"Auto-tagging... {index}/{total}"

    def action_rescan_cursor_node(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None or not node.allow_expand:
            return
        path = node.data.path
        # Deliberately not self.loading = True here (unlike auto-tag above) -
        # Widget.loading covers the whole widget with a plain spinner
        # (Widget.set_loading's self._cover), which hides the border and
        # its subtitle underneath. That's fine for auto-tag (fast enough
        # nobody notices), but it silently swallowed this feature's actual
        # "N/total" progress text, which is the whole point here - a
        # spinner with no numbers is exactly what looked "stuck" to begin
        # with. The border_subtitle text itself already conveys "something
        # is happening", so the spinner isn't needed.
        self.border_subtitle = "Rescanning..."
        self.run_worker(
            self._rescan_folder(path), exclusive=True, group="rescan", name="rescan"
        )

    async def _rescan_folder(self, path: Path) -> None:
        # No throttling interval here unlike auto-tag's TAGGING_PROGRESS_
        # INTERVAL - a rescan decodes/hashes whole files, which dominates
        # the per-file cost far more than a cross-thread UI update does, so
        # every file getting its own progress update is cheap and (per user
        # feedback - a scan looked "stuck" with only sparse updates) is
        # what actually makes progress visible rather than looking hung.
        def on_progress(index: int, total: int) -> None:
            self.app.call_from_thread(self._set_rescan_progress, index, total)

        try:
            count = await asyncio.to_thread(
                library_scan.scan_library, path, self.db_path, on_progress
            )
        finally:
            self.border_subtitle = ""
        noun = "sample" if count == 1 else "samples"
        self.app.notify(f"Rescanned {count} {noun} under '{path.name}'.")
        self.post_message(self.Tagged())

    def _set_rescan_progress(self, index: int, total: int) -> None:
        percent = f" ({index / total:.0%})" if total else ""
        self.border_subtitle = f"Rescanning... {index}/{total}{percent}"

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
        if action == "rescan_cursor_node":
            node = self.cursor_node
            return node is not None and node.data is not None and node.allow_expand
        return True

    def action_remove_samples_directory(self) -> None:
        node = self._cursor_on_root_path()
        if node is None:
            return
        path = node.data.path

        def handle_result(confirmed: bool) -> None:
            if not confirmed:
                return
            self.samples_directories.remove(path)
            self._persist_samples_directories()
            if self._expanded_root_node is node:
                self._expanded_root_node = None
            node.remove()

            # Cascade: a removed path's samples shouldn't leave their tags
            # or their references in a saved pack dangling against paths
            # nothing will ever browse to again (see remove_tags_under/
            # remove_samples_under's own docstrings for exactly what each
            # does and doesn't touch).
            tag_store.remove_tags_under(path, self.db_path)
            updated_packs = config_store.remove_samples_under(path, self.configurations_dir)

            message = f"Removed '{path.name}'."
            if updated_packs:
                noun = "pack" if updated_packs == 1 else "packs"
                message += f" Updated {updated_packs} {noun} that referenced it."
            self.app.notify(message)
            self.post_message(self.PathRemoved())

        self.app.push_screen(ConfirmRemovePathModal(path.name), handle_result)

    def _persist_samples_directories(self) -> None:
        settings_module.save_settings(
            settings_module.Settings(samples_directories=list(self.samples_directories)),
            self.settings_path,
        )

    def go_to_top(self) -> None:
        self.action_scroll_home()

    def go_to_bottom(self) -> None:
        self.action_scroll_end()
