from datetime import datetime
from pathlib import Path

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DataTable, OptionList, Static
from textual.widgets.option_list import Option

from shmample import config_store, device
from shmample.audio import NoPlayerFoundError, Previewer
from shmample.config_store import Configuration, save_configuration
from shmample.device import BANK_DISPLAY_ORDER, PAD_NUMBERS
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.vim_navigation import VimGoToTopAndBottom
from shmample.widgets.vim_option_list import VimOptionList


class _ChordPickerModal(ModalScreen[str | None]):
    """Shared shape for BankPickerModal/PadPickerModal: a titled
    OptionList of choices, each choice *also* bound directly to its own
    key so typing it alone picks it - closer to the brief's "A then 1"
    chord idea than arrow-navigate-then-enter. Still a normal
    ModalScreen (not a hand-rolled on_key state machine) so the picker
    owns input exclusively while it's up - see 03-skeleton-tui.md's
    "bound keys still bubble" gotcha for why that matters here: a
    focused DataTable/DirectoryTree's own bindings would otherwise fire
    at the same time as this one's.
    """

    DEFAULT_CSS = """
    _ChordPickerModal {
        align: center middle;
    }
    _ChordPickerModal > OptionList {
        width: 90%;
        max-width: 33%;
        height: auto;
        border: round $accent;
    }
    """

    def __init__(self, title: str, choices: list[str]) -> None:
        super().__init__()
        self._title = title
        self._choices = choices

    def compose(self) -> ComposeResult:
        options = VimOptionList(*(Option(choice, id=choice) for choice in self._choices))
        options.border_title = self._title
        yield options

    def on_mount(self) -> None:
        self.query_one(VimOptionList).focus()

    def action_pick(self, choice: str) -> None:
        self.dismiss(choice)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)


class BankPickerModal(_ChordPickerModal):
    """First step of the assign chord - pick a bank letter. Listed in
    BANK_DISPLAY_ORDER (button-pair grouping), not alphabetically.

    `description` is pre-formatted by the caller (e.g. "'kick.wav'" for a
    single sample, "3 selected samples" for a multi-assign) rather than
    always being wrapped in quotes here, since it needs to read
    naturally in both cases.
    """

    BINDINGS = [
        Binding(letter.lower(), f"pick({letter!r})", letter, show=False)
        for letter in BANK_DISPLAY_ORDER
    ] + [Binding("escape", "cancel", "Cancel")]

    def __init__(self, description: str) -> None:
        super().__init__(f"Assign {description} -> bank", list(BANK_DISPLAY_ORDER))


class PadPickerModal(_ChordPickerModal):
    """Second step of the assign chord - pick a pad number, once a bank's
    already been chosen."""

    BINDINGS = [
        Binding(str(number), f"pick({str(number)!r})", str(number), show=False)
        for number in PAD_NUMBERS
    ] + [Binding("escape", "cancel", "Cancel")]

    def __init__(self, sample_name: str, bank: str) -> None:
        super().__init__(f"Assign '{sample_name}' -> Bank {bank}, pad", [str(n) for n in PAD_NUMBERS])


class ConfirmClearAllModal(ModalScreen[bool]):
    """Confirmation before "D" wipes every pad in the loaded configuration
    - same OptionList + detail-pane shape as config_list.py's
    ConfirmDeleteModal/ConfirmSendModal, styled $error since (unlike
    ConfirmSendModal's IMPORT-folder wipe) this discards assignments the
    user hasn't necessarily sent to the device yet."""

    DEFAULT_CSS = """
    ConfirmClearAllModal {
        align: center middle;
    }
    ConfirmClearAllModal > Vertical {
        width: 90%;
        max-width: 33%;
        height: auto;
    }
    ConfirmClearAllModal OptionList {
        border: round $error;
        height: auto;
    }
    ConfirmClearAllModal #detail {
        border: round $error;
        height: auto;
        margin-top: 1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config_name: str, pad_count: int) -> None:
        super().__init__()
        self.config_name = config_name
        noun = "pad" if pad_count == 1 else "pads"
        self._details = (
            f"Clear all {pad_count} assigned {noun} in '{self.config_name}'. "
            "This cannot be undone.",
            "Keep the current assignments as they are.",
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            options = VimOptionList(
                Option(f"Clear all pads in '{self.config_name}'", id="confirm"),
                Option("Cancel", id="cancel"),
            )
            options.border_title = "Clear all pads"
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


class AssignmentGrid(DataTable, VimGoToTopAndBottom):
    """8 (bank) x 6 (pad) grid of the configuration currently being
    edited - the settled design from 03-skeleton-tui.md. Row label is
    the bank letter, in BANK_DISPLAY_ORDER (the device's 4-button
    A/E-B/F-C/G-D/H pairing, not alphabetical - see device.py); each cell
    shows the assigned sample's filename, or "-" if that pad is empty.

    `configuration`/`configuration_path` are both None until `load()` is
    given a real (path, Configuration) pair (ConfigList's "n"/Enter, via
    ConfigList.Opened) - there's no implicit blank scratch configuration
    to assign into. FileBrowser.action_start_assign checks `configuration
    is not None` before starting the assign chord at all, so an
    assignment can never be made without landing in a real, named,
    disk-backed configuration.

    Every assignment/clear writes straight to disk (see _save()) - no
    separate save step, and so no ambiguity about whether "saving" means
    the one pad you're looking at or the whole configuration (it's always
    the whole configuration, immediately). Rejected an explicit `s`
    binding for this on request: a user who never actually visits this
    pane (assigning entirely from the file browser's "a" chord) would
    have no reason to know it existed, let alone press it.

    Cursor-navigable (arrows, or vim h/j/k/l); d/p/i act on whichever pad
    the cursor is on. *Creating* an assignment doesn't happen here
    though - that starts from the file browser's "a" chord (see
    FileBrowser.action_start_assign) and this pane just receives the
    result via assign().
    """

    DEFAULT_CSS = """
    AssignmentGrid {
        width: 1fr;
        height: 1fr;
        border: round $foreground;
    }
    AssignmentGrid:focus {
        border: round $primary;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
        Binding("h", "cursor_left", "Left (vim)", show=False),
        Binding("l", "cursor_right", "Right (vim)", show=False),
        Binding("d", "clear_cursor_pad", "Clear"),
        Binding("D", "clear_all_pads", "Clear all"),
        Binding("p", "preview_cursor_pad", "Preview"),
        Binding("i", "info_cursor_pad", "Info"),
    ] + VimGoToTopAndBottom.BINDINGS

    def go_to_top(self) -> None:
        self.action_scroll_top()

    def go_to_bottom(self) -> None:
        self.action_scroll_bottom()

    class Saved(Message):
        """Posted after every auto-save (see _save()) - the sibling
        ConfigList (see ConfigList.Opened for why this isn't just a
        direct call) should refresh its list to pick up the change."""

    def __init__(self, configurations_dir: Path | None = None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cursor_type = "cell"
        # Resolved at call time, not a mutable default parameter - same
        # reasoning as ConfigList/FileBrowser, so tests can monkeypatch
        # config_store.DEFAULT_CONFIGURATIONS_DIR.
        self.configurations_dir = (
            configurations_dir
            if configurations_dir is not None
            else config_store.DEFAULT_CONFIGURATIONS_DIR
        )
        self.configuration: Configuration | None = None
        self.configuration_path: Path | None = None
        self.previewer = Previewer()
        self.last_previewed: Path | None = None

    # Floor, not a fixed value: update_cell() (used by assign()/
    # _refresh_cells() below) defaults to update_width=False, so a column
    # sized to the "1".."6" header would clip every real sample name to
    # one character. _layout_grid stretches columns/rows wider/taller
    # than this to fill whatever space the pane actually has.
    MIN_PAD_COLUMN_WIDTH = 14
    # DataTable doesn't expose the row-label ("A".."H") column's rendered
    # width other than by measuring it after a layout pass - this is that
    # measurement's whole point, so it can't be used to compute the space
    # available for the pad columns before that pass has happened. A
    # single letter plus its default 1-cell padding on each side, from
    # inspecting the rendered output, is close enough that any error just
    # shows up as a few characters of horizontal slack, not overflow.
    ROW_LABEL_COLUMN_WIDTH_ESTIMATE = 3
    # Also a floor, same reasoning as MIN_PAD_COLUMN_WIDTH above but for
    # height: _cell_text() below renders a sample's size on a second
    # line beneath its filename, which a single-line row would just
    # clip off entirely (DataTable top-aligns cell content).
    MIN_ROW_HEIGHT = 2

    def on_mount(self) -> None:
        self._layout_grid()

    def on_resize(self, event: events.Resize) -> None:
        self._layout_grid()

    def _layout_grid(self) -> None:
        """(Re)builds the grid's rows/columns sized to fill the pane,
        rather than the DataTable default of content-sized rows/columns
        leaving the rest blank. Rebuilds from scratch (clear + re-add)
        since DataTable has no public API to resize an existing row/column
        - cell contents are restored from self.configuration afterwards.

        Deliberately reads self.size fresh rather than trusting the
        triggering Resize event's own `size` attribute - that turned out
        to report the widget's outer (bordered) size, 2 cells wider/taller
        than self.size's content-box size, which would otherwise size
        every row/column 2 cells too generously.
        """
        previous_cursor = self.cursor_coordinate if self.row_count else None

        row_height = max(
            self.MIN_ROW_HEIGHT, (self.size.height - self.header_height) // len(BANK_DISPLAY_ORDER)
        )
        # add_column's own `width` is the *content* width - DataTable pads
        # cell_padding cells on each side on top of that when actually
        # rendering, so the on-screen space a column occupies is
        # width + 2*cell_padding, not width itself.
        available_width = self.size.width - self.ROW_LABEL_COLUMN_WIDTH_ESTIMATE
        rendered_width_per_column = available_width // len(PAD_NUMBERS)
        column_width = max(
            self.MIN_PAD_COLUMN_WIDTH, rendered_width_per_column - 2 * self.cell_padding
        )

        self.clear(columns=True)
        for number in PAD_NUMBERS:
            self.add_column(str(number), key=str(number), width=column_width)
        for letter in BANK_DISPLAY_ORDER:
            self.add_row(*(["-"] * len(PAD_NUMBERS)), key=letter, label=letter, height=row_height)
        self._refresh_cells()

        if previous_cursor is not None:
            self.cursor_coordinate = previous_cursor

    def load(self, entry: tuple[Path, Configuration] | None) -> None:
        """Populate the grid from a saved configuration - or, with
        `entry=None`, deactivate it (no configuration loaded at all,
        rather than falling back to some unnamed scratch one)."""
        if entry is None:
            self.configuration_path = None
            self.configuration = None
        else:
            self.configuration_path, self.configuration = entry
        self._refresh_cells()

    def _cell_text(self, sample_path: Path | None) -> str:
        """A pad's cell content: "-" empty, else the filename plus its
        size on its own line beneath ("kick.wav\n218KB") - MIN_ROW_HEIGHT
        exists specifically so that second line has somewhere to go.
        Falls back to the filename alone if the file's gone missing (no
        size to report - same "don't crash over it" spirit as
        send_configuration's own missing-source handling, just a display
        concern here rather than a copy one).
        """
        if sample_path is None:
            return "-"
        sample_path = Path(sample_path)
        try:
            size = sample_path.stat().st_size
        except OSError:
            return sample_path.name
        return f"{sample_path.name}\n{device.human_bytes(size)}"

    def _refresh_cells(self) -> None:
        for letter in BANK_DISPLAY_ORDER:
            for number in PAD_NUMBERS:
                sample_path = None
                if self.configuration is not None:
                    sample_path = self.configuration.assignments.get((letter, str(number)))
                self.update_cell(letter, str(number), self._cell_text(sample_path))

    def assign(self, bank: str, pad: str, sample_path: Path) -> None:
        # Callers (start_assign_single below, HoldingArea's own "a")
        # already refuse to start the assign chord without an active
        # configuration - this guard is just so assign() itself can't be
        # misused to write into nothing.
        if self.configuration is None:
            return
        self.configuration.assignments[(bank, pad)] = str(sample_path)
        self.update_cell(bank, pad, self._cell_text(sample_path))
        self._save()

    def start_assign_single(self, sample_path: Path) -> None:
        """Runs the bank-then-pad picker chord for one sample and calls
        assign() with the result - the chord itself only needs to live
        here, the one place that actually owns the grid it writes into.
        Used by HoldingArea's own "a" binding (assigning something
        already held onto a real pad).
        """

        def handle_bank(bank: str | None) -> None:
            if bank is None:
                return

            def handle_pad(pad: str | None) -> None:
                if pad is None:
                    return
                self.assign(bank, pad, sample_path)

            self.app.push_screen(PadPickerModal(sample_path.name, bank), handle_pad)

        self.app.push_screen(BankPickerModal(f"'{sample_path.name}'"), handle_bank)

    def set_assignments(self, assignments: dict[tuple[str, str], Path]) -> None:
        """Replaces the whole configuration's pad assignments in one shot
        and saves once - the basis for action_clear_all_pads
        (set_assignments({})) and any other bulk-replace flow, rather than
        looping calls to assign() and triggering a save per pad.
        """
        if self.configuration is None:
            return
        self.configuration.assignments = {key: str(path) for key, path in assignments.items()}
        self._refresh_cells()
        self._save()

    @property
    def cursor_pad(self) -> tuple[str, str]:
        row_key, column_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        return row_key.value, column_key.value

    def action_clear_cursor_pad(self) -> None:
        if self.configuration is None:
            return
        bank, pad = self.cursor_pad
        if self.configuration.assignments.pop((bank, pad), None) is not None:
            self.update_cell(bank, pad, "-")
            self._save()

    def action_clear_all_pads(self) -> None:
        if self.configuration is None or not self.configuration.assignments:
            return

        def handle_result(confirmed: bool) -> None:
            if confirmed:
                self.set_assignments({})

        self.app.push_screen(
            ConfirmClearAllModal(
                self.configuration.pack.name, len(self.configuration.assignments)
            ),
            handle_result,
        )

    def action_preview_cursor_pad(self) -> None:
        if self.configuration is None:
            return
        bank, pad = self.cursor_pad
        sample_path = self.configuration.assignments.get((bank, pad))
        if sample_path is not None:
            self.last_previewed = Path(sample_path)
            self.run_worker(
                self._play(self.last_previewed), exclusive=True, group="preview", name="preview"
            )

    async def _play(self, path: Path) -> None:
        try:
            await self.previewer.play(path)
        except NoPlayerFoundError:
            pass

    def action_info_cursor_pad(self) -> None:
        if self.configuration is None:
            return
        bank, pad = self.cursor_pad
        sample_path = self.configuration.assignments.get((bank, pad))
        preview = self.app.query_one("#preview", PreviewInfo)
        preview.show(Path(sample_path) if sample_path is not None else None)

    def _save(self) -> None:
        """Writes the active configuration to disk immediately - called
        after every assign/clear, not on any explicit user action (see
        class docstring for why there's no "s" any more). Every caller
        already checked `self.configuration is not None` first; per the
        class invariant, `configuration_path` is then always set too.
        """
        if self.configuration is None or self.configuration_path is None:
            return
        self.configuration.pack.modified_at = datetime.now()
        save_configuration(self.configuration, self.configurations_dir, self.configuration_path)
        self.post_message(self.Saved())
