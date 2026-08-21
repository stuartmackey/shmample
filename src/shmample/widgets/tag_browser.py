from pathlib import Path

from textual.binding import Binding
from textual.widgets import Label, ListItem, ListView

from shmample import sample_store, tag_store
from shmample.widgets.vim_navigation import VimGoToTopAndBottom


class TagBrowser(ListView, VimGoToTopAndBottom):
    """Lists every tag with a count of samples under it
    (01-auto-tagging.md's dedicated tag pane) - for now just the listing;
    selecting a tag to filter the sample list is a later step.

    Scoped to whatever folder the samples pane is currently focused on
    (see FileBrowser's "."/"h" root-focus feature) via set_scope - MainColumn
    calls that whenever the focused root changes. Unscoped (the default)
    shows every tag in the whole library, including ones with no samples
    currently under them; scoped to a folder, a tag with no samples in
    that folder is left off entirely rather than shown as "(0)" (see
    tag_store.tag_counts).

    Vertical-only, like ConfigList, so it only needs vim's j/k/gg/G.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
    ] + VimGoToTopAndBottom.BINDINGS

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

    def on_mount(self) -> None:
        self.refresh_list()

    def set_scope(self, scope: Path | None) -> None:
        self.scope = scope
        self.refresh_list()

    def refresh_list(self) -> None:
        previous_index = self.index
        counts = tag_store.tag_counts(self.db_path, root=self.scope)

        self.clear()
        if not counts:
            self.append(ListItem(Label("No tags yet")))
            return

        for name, count in counts:
            self.append(ListItem(Label(f"{name} ({count})")))

        if previous_index is not None and previous_index < len(counts):
            self.call_after_refresh(setattr, self, "index", previous_index)

    def go_to_top(self) -> None:
        if self.children:
            self.index = 0

    def go_to_bottom(self) -> None:
        if self.children:
            self.index = len(self.children) - 1
