from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from shmample import library_scan, sample_store
from shmample.audio import NoPlayerFoundError, Previewer
from shmample.widgets.main_column import PREVIEW_DEBOUNCE_SECONDS
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.vim_option_list import VimOptionList


class ConfirmDeleteSampleModal(ModalScreen[bool]):
    """Same OptionList + detail-pane shape as config_list.ConfirmDeleteModal -
    but the wording says "permanently", since unlike everything else this
    app has ever deleted (a configuration, a device pad file), there's no
    trash/recovery for a sample file removed this way."""

    DEFAULT_CSS = """
    ConfirmDeleteSampleModal {
        align: center middle;
    }
    ConfirmDeleteSampleModal > Vertical {
        width: 90%;
        max-width: 60%;
        height: auto;
    }
    ConfirmDeleteSampleModal OptionList {
        border: round $error;
        height: auto;
    }
    ConfirmDeleteSampleModal #detail {
        border: round $error;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._details = (
            f"Permanently delete '{self.path}'. This cannot be undone.",
            "Keep the file as it is.",
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Delete '{self.path.name}'", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Delete sample"
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


class DuplicateReviewScreen(Screen):
    """Browse content-hash duplicate groups, preview/play each candidate,
    and permanently delete one - the tag-filter pane alone doesn't scale to
    thousands of duplicate files with no grouping or way to compare
    candidates against each other (see docs/tasks/02-find-duplicates.md).
    """

    DEFAULT_CSS = """
    DuplicateReviewScreen #groups {
        width: 40%;
        height: 1fr;
        border: round $primary;
    }
    DuplicateReviewScreen #right {
        width: 1fr;
        height: 1fr;
    }
    DuplicateReviewScreen #files {
        border: round $primary;
        height: 50%;
    }
    DuplicateReviewScreen PreviewInfo {
        border: round $primary;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back", show=False),
        Binding("p", "play_cursor_file", "Play"),
        Binding("d", "delete_cursor_file", "Delete"),
        Binding("a", "allow_cursor_group", "Allow"),
        # Numbered pane jump, same convention as ShmampleApp's own "[1]
        # Device" etc. (app.py) - not shown in the footer since the border
        # titles below already carry the number.
        Binding("1", "focus_pane('#groups')", "Groups", show=False),
        Binding("2", "focus_pane('#files')", "Copies", show=False),
        Binding("3", "focus_pane('#preview')", "Preview", show=False),
    ]

    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path
        # (content_hash, paths) rather than just paths - "allow" acts on
        # the hash, not any one file in the group.
        self._groups: list[tuple[str, list[Path]]] = list(
            sample_store.duplicate_hash_groups(db_path).items()
        )
        self.previewer = Previewer()
        self._preview_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            groups = VimOptionList(id="groups")
            groups.border_title = "[1] Duplicate groups"
            yield groups
            with Vertical(id="right"):
                files = VimOptionList(id="files")
                files.border_title = "[2] Copies"
                yield files
                preview = PreviewInfo(self.db_path, id="preview")
                preview.border_title = "[3] Preview"
                yield preview
        # Unlike the small confirm/pick modals elsewhere (self-explanatory
        # from their two visible option labels), this is a full working
        # screen with several keybindings that aren't shown anywhere else
        # in the UI - a Footer is the only thing that makes them
        # discoverable at all.
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_groups(select_index=0)
        self.query_one("#groups", VimOptionList).focus()

    def action_focus_pane(self, selector: str) -> None:
        self.query_one(selector).focus()

    def _refresh_groups(self, select_index: int) -> None:
        groups_list = self.query_one("#groups", VimOptionList)
        groups_list.clear_options()
        if not self._groups:
            groups_list.border_subtitle = "0 of 0"
            self._refresh_files()
            return
        groups_list.add_options(
            Option(f"Group {i + 1}: {len(paths)} files")
            for i, (_, paths) in enumerate(self._groups)
        )
        groups_list.border_subtitle = f"{len(self._groups)} groups"
        groups_list.highlighted = max(0, min(select_index, len(self._groups) - 1))
        self._refresh_files()

    def _current_group_index(self) -> int | None:
        return self.query_one("#groups", VimOptionList).highlighted

    def _current_group_hash(self) -> str | None:
        index = self._current_group_index()
        if index is None or not self._groups:
            return None
        return self._groups[index][0]

    def _current_files(self) -> list[Path]:
        index = self._current_group_index()
        if index is None or not self._groups:
            return []
        return self._groups[index][1]

    def _refresh_files(self) -> None:
        files_list = self.query_one("#files", VimOptionList)
        files_list.clear_options()
        files = self._current_files()
        preview = self.query_one(PreviewInfo)
        if not files:
            files_list.border_subtitle = "0 of 0"
            preview.show(None)
            return
        files_list.add_options(Option(str(path)) for path in files)
        files_list.border_subtitle = f"{len(files)} files"
        files_list.highlighted = 0
        preview.show(files[0])

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "groups":
            self._refresh_files()
        elif event.option_list.id == "files":
            self._debounced_preview(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "files":
            self.action_play_cursor_file()

    def _debounced_preview(self, index: int) -> None:
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None
        files = self._current_files()
        if index >= len(files):
            return
        path = files[index]
        self._preview_timer = self.set_timer(
            PREVIEW_DEBOUNCE_SECONDS, lambda: self.query_one(PreviewInfo).show(path)
        )

    def _highlighted_file(self) -> Path | None:
        index = self.query_one("#files", VimOptionList).highlighted
        files = self._current_files()
        if index is None or index >= len(files):
            return None
        return files[index]

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_play_cursor_file(self) -> None:
        path = self._highlighted_file()
        if path is not None:
            self.run_worker(self._play(path), exclusive=True, group="preview", name="preview")

    async def _play(self, path: Path) -> None:
        try:
            await self.previewer.play(path)
        except NoPlayerFoundError as error:
            self.app.notify(str(error), severity="error")

    def action_delete_cursor_file(self) -> None:
        path = self._highlighted_file()
        if path is None:
            return

        def handle_result(confirmed: bool) -> None:
            if confirmed:
                self._delete_file(path)

        self.app.push_screen(ConfirmDeleteSampleModal(path), handle_result)

    def _delete_file(self, path: Path) -> None:
        try:
            library_scan.delete_duplicate(path, self.db_path)
        except OSError as error:
            self.app.notify(f"Could not delete '{path.name}': {error}", severity="error")
            return

        index = self._current_group_index()
        if index is None:
            return
        content_hash, paths = self._groups[index]
        paths.remove(path)
        if len(paths) < 2:
            self._groups.pop(index)
        self._refresh_groups(select_index=index)
        self.app.notify(f"Deleted '{path.name}'.")

    def action_allow_cursor_group(self) -> None:
        index = self._current_group_index()
        content_hash = self._current_group_hash()
        if index is None or content_hash is None:
            return
        library_scan.allow_duplicate(content_hash, self.db_path)
        self._groups.pop(index)
        self._refresh_groups(select_index=index)
        self.app.notify("Marked as an allowed duplicate - won't be flagged again.")
