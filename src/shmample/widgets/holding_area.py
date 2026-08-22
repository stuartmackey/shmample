from datetime import datetime
from pathlib import Path

from textual.binding import Binding
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from shmample import config_store
from shmample.audio import NoPlayerFoundError, Previewer
from shmample.config_store import Configuration, save_configuration
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.vim_navigation import VimGoToTopAndBottom


class HoldingArea(ListView, VimGoToTopAndBottom):
    """Device-agnostic staging list for the configuration currently being
    edited - the first step towards decoupling a configuration from any
    one device's bank/pad shape. Every sample added via the file
    browser's "a" chord (see
    FileBrowser.action_start_assign) lands here first, as a plain
    ordered list with no device-specific placement decided yet. Placing
    a held sample onto an actual pad (see action_assign_cursor_item
    below, which delegates to AssignmentGrid.start_assign_single) is a
    separate step from here, not something the file browser does
    directly any more.

    `configuration`/`configuration_path` mirror AssignmentGrid's own -
    both are populated from the same ConfigList.Opened message (see
    app.py's on_config_list_opened), sharing the identical Configuration
    object rather than each holding its own copy, so a save from either
    widget always includes the other's latest in-memory changes too.

    Vertical-only, like ConfigList/TagBrowser, so it only needs vim's
    j/k/gg/G plus "d" (remove) and "a" (assign the highlighted sample to
    a pad).
    """

    DEFAULT_CSS = """
    HoldingArea {
        width: 1fr;
        max-width: 33%;
        height: 1fr;
        border: round $foreground;
    }
    HoldingArea:focus {
        border: round $primary;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("p", "preview_cursor_item", "Preview", show=False),
        # Same action as ListView's own built-in "enter" binding
        # (select_cursor) - overridden only to make it visible in the
        # footer, same reasoning as FileBrowser's own override of "enter".
        Binding("enter", "select_cursor", "Preview"),
        Binding("d", "remove_cursor_item", "Remove"),
        Binding("a", "assign_cursor_item", "Assign to pad"),
    ] + VimGoToTopAndBottom.BINDINGS

    class Saved(Message):
        """Posted after every add/remove auto-save (see _save()) - same
        reasoning as AssignmentGrid.Saved: the sibling ConfigList should
        refresh to pick up the change."""

    def __init__(self, configurations_dir: Path | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Resolved at call time, not a mutable default parameter - same
        # reasoning as AssignmentGrid/ConfigList/FileBrowser, so tests
        # can redirect persistence to a tmp_path.
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
        )
        self.configuration: Configuration | None = None
        self.configuration_path: Path | None = None
        self.previewer = Previewer()
        self.last_previewed: Path | None = None

    def on_mount(self) -> None:
        self.refresh_list()

    def load(self, entry: tuple[Path, Configuration] | None) -> None:
        """Populate the list from a saved configuration - or, with
        `entry=None`, deactivate it, same contract as
        AssignmentGrid.load()."""
        if entry is None:
            self.configuration_path = None
            self.configuration = None
        else:
            self.configuration_path, self.configuration = entry
        self.refresh_list()

    def refresh_list(self) -> None:
        previous_index = self.index
        held = self.configuration.holding if self.configuration is not None else []

        self.clear()
        if not held:
            self.append(ListItem(Label("Nothing held yet")))
            return

        for sample_path in held:
            self.append(ListItem(Label(Path(sample_path).name)))

        # ListView only auto-highlights row 0 for free the very first
        # time it ever mounts with children (see ConfigList.refresh_list's
        # own comment on the same quirk) - every later clear()+append()
        # needs it restored by hand, falling back to row 0 rather than
        # leaving the cursor unset when there's nothing valid to restore
        # (e.g. the first sample ever added to a previously-empty list,
        # where the old index was still sitting on the now-gone
        # "Nothing held yet" placeholder row).
        index = previous_index if previous_index is not None and previous_index < len(held) else 0
        self.call_after_refresh(setattr, self, "index", index)

    @property
    def cursor_path(self) -> Path | None:
        if self.configuration is None or self.index is None:
            return None
        held = self.configuration.holding
        if self.index >= len(held):
            return None
        return Path(held[self.index])

    def add_samples(self, sample_paths: list[Path]) -> tuple[list[Path], list[Path]]:
        """Appends every one of `sample_paths` not already held, in
        order - re-adding an already-held path is a no-op rather than a
        duplicate entry (see Configuration.holding's docstring). Returns
        (added, already_held) so the caller (FileBrowser) can report
        both counts back to the user.
        """
        if self.configuration is None:
            return [], []

        already = set(self.configuration.holding)
        added: list[Path] = []
        already_held: list[Path] = []
        for path in sample_paths:
            key = str(path)
            if key in already:
                already_held.append(path)
                continue
            self.configuration.holding.append(key)
            already.add(key)
            added.append(path)

        if added:
            self.refresh_list()
            self._save()
        return added, already_held

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._start_preview(self.cursor_path)

    def action_preview_cursor_item(self) -> None:
        self._start_preview(self.cursor_path)

    def _start_preview(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            return
        self.last_previewed = path
        # exclusive=True: a new preview kills whatever was already
        # playing, rather than queuing behind it (see FileBrowser's own
        # _start_preview).
        self.run_worker(self._play(path), exclusive=True, group="preview", name="preview")

    async def _play(self, path: Path) -> None:
        try:
            await self.previewer.play(path)
        except NoPlayerFoundError:
            pass

    def action_remove_cursor_item(self) -> None:
        if self.configuration is None or self.index is None:
            return
        held = self.configuration.holding
        if self.index >= len(held):
            return
        held.pop(self.index)
        self.refresh_list()
        self._save()

    def action_assign_cursor_item(self) -> None:
        path = self.cursor_path
        if path is None:
            return
        self.app.query_one("#assignments", AssignmentGrid).start_assign_single(path)

    def go_to_top(self) -> None:
        if self.children:
            self.index = 0

    def go_to_bottom(self) -> None:
        if self.children:
            self.index = len(self.children) - 1

    def _save(self) -> None:
        if self.configuration is None or self.configuration_path is None:
            return
        self.configuration.modified_at = datetime.now()
        save_configuration(self.configuration, self.configurations_dir, self.configuration_path)
        self.post_message(self.Saved())
