from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from shmample import sample_store, tag_store
from shmample.widgets.vim_navigation import VimGoToTopAndBottom


class TagBrowser(ListView, VimGoToTopAndBottom):
    """Lists every tag with a count of samples under it
    (01-auto-tagging.md's dedicated tag pane). Space toggles the
    highlighted tag as a filter (styled `bold green`, same convention as
    FileBrowser's own multi-select) - selected tags are AND'ed (a sample
    has to carry all of them) and applied to the samples pane via
    FileBrowser.set_tag_filter, which MainColumn wires up on
    SelectionChanged.

    Scoped to whatever folder the samples pane is currently focused on
    (see FileBrowser's "."/"h" root-focus feature) via set_scope - MainColumn
    calls that whenever the focused root changes. Unscoped (the default)
    shows every tag in the whole library, including ones with no samples
    currently under them; scoped to a folder, a tag with no samples in
    that folder is left off entirely rather than shown as "(0)" (see
    tag_store.tag_counts). Scope and selection are independent - a
    selected tag keeps filtering the samples pane even if a later scope
    change (or the filter it's itself applying) means it's not currently
    listed here.

    Vertical-only, like ConfigList, so it only needs vim's j/k/gg/G.
    """

    # Sits in #tags-holding-row (app.py's compose) side by side with
    # HoldingArea, not nested inside MainColumn's "samples-row" any more -
    # so, like AssignmentGrid/HoldingArea, it needs to size and border
    # itself rather than relying on a parent's CSS. No max-width cap (as
    # ConfigList/MainColumn still have, being one of three top-level
    # columns) - here it's one of only two children sharing that row, so
    # an even 1fr:1fr split is exactly what's wanted.
    DEFAULT_CSS = """
    TagBrowser {
        width: 1fr;
        height: 1fr;
        border: round $foreground;
    }
    TagBrowser:focus {
        border: round $primary;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("space", "toggle_selected_tag", "Filter"),
    ] + VimGoToTopAndBottom.BINDINGS

    SELECTED_STYLE = "bold green"

    class SelectionChanged(Message):
        """Posted whenever space toggles a tag in/out of `selected_tags` -
        lets MainColumn apply the new AND filter to the samples pane."""

    def __init__(self, db_path: Path | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Resolved at call time, not a mutable default parameter - same
        # reasoning as PreviewInfo's own db_path, so tests can redirect
        # persistence to a tmp_path. Falls back to sample_store's own
        # DEFAULT_DB_PATH (not a local copy) since tags live in the same
        # database file as the sample preview cache - one attribute for
        # tests to monkeypatch, not two that could drift apart.
        self.db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH
        self.scope: Path | None = None
        self.selected_tags: set[str] = set()
        # Snapshot of what refresh_list last showed - lets
        # action_toggle_selected_tag map the highlighted row back to a
        # tag name, same idea as ConfigList's own `entries`.
        self.counts: list[tuple[str, int]] = []

    def on_mount(self) -> None:
        self.refresh_list()

    def set_scope(self, scope: Path | None) -> None:
        self.scope = scope
        self.refresh_list()

    def action_toggle_selected_tag(self) -> None:
        if self.index is None or not self.counts:
            return
        name, _ = self.counts[self.index]
        if name in self.selected_tags:
            self.selected_tags.discard(name)
        else:
            self.selected_tags.add(name)
        self.refresh_list()
        self.post_message(self.SelectionChanged())

    def refresh_list(self) -> None:
        previous_index = self.index
        self.counts = tag_store.tag_counts(self.db_path, root=self.scope)

        self.clear()
        if not self.counts:
            self.append(ListItem(Label("No tags yet")))
            return

        for name, count in self.counts:
            text = f"{name} ({count})"
            label = Label(Text(text, style=self.SELECTED_STYLE) if name in self.selected_tags else text)
            self.append(ListItem(label))

        if previous_index is not None and previous_index < len(self.counts):
            self.call_after_refresh(setattr, self, "index", previous_index)

    def go_to_top(self) -> None:
        if self.children:
            self.index = 0

    def go_to_bottom(self) -> None:
        if self.children:
            self.index = len(self.children) - 1
