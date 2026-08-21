import struct
import wave
from datetime import datetime
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import Input, Static

from shmample import device
from shmample.app import ShmampleApp
from shmample.config_store import Configuration, list_configurations, save_configuration
from shmample.widgets.assignment_grid import AssignmentGrid, BankPickerModal, PadPickerModal
from shmample.widgets.config_list import ConfigList
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.preview_info import PreviewInfo


class AssignmentGridApp(App):
    def __init__(self, configurations_dir) -> None:
        super().__init__()
        self.configurations_dir = configurations_dir

    def compose(self) -> ComposeResult:
        yield AssignmentGrid(self.configurations_dir, id="assignments")
        yield PreviewInfo(id="preview")


@pytest.fixture
def wav_sample(tmp_path):
    path = tmp_path / "kick.wav"
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"".join(struct.pack("<h", 1000) for _ in range(4000)))
    return path


def _status_text(preview: PreviewInfo) -> str:
    return str(preview.query_one("#preview-date").render())


def _cell_name(grid: AssignmentGrid, bank: str, pad: str) -> str:
    """A pad's filename, without the size AssignmentGrid._cell_text now
    appends on a second line - "-" for an empty pad is unaffected (no
    second line to strip)."""
    return grid.get_cell(bank, pad).split("\n")[0]


def _activate_configuration(grid: AssignmentGrid, name: str = "Kit") -> tuple[Path, Configuration]:
    """Creates, saves, and loads a configuration into `grid` - assignments
    can no longer be made without one active (see AssignmentGrid's
    docstring), so most tests need this before they can call assign()."""
    now = datetime(2026, 1, 1)
    config = Configuration(name=name, description="", created_at=now, modified_at=now)
    path = save_configuration(config, grid.configurations_dir)
    grid.load((path, config))
    return path, config


async def test_grid_starts_with_all_pads_empty(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        assert grid.row_count == 8
        assert len(grid.columns) == 6
        assert _cell_name(grid, "A", "1") == "-"
        assert _cell_name(grid, "H", "6") == "-"


async def test_rows_are_ordered_by_the_device_button_pairing_not_alphabetically(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        ordered_letters = [row.key.value for row in grid.ordered_rows]
        assert ordered_letters == list("AEBFCGDH")


def _row_heights(grid: AssignmentGrid) -> set[int]:
    return {row.height for row in grid.rows.values()}


def _column_render_widths(grid: AssignmentGrid) -> set[int]:
    return {column.get_render_width(grid) for column in grid.columns.values()}


async def test_grid_rows_and_columns_stretch_on_a_large_terminal(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test(size=(220, 60)):
        grid = app.query_one(AssignmentGrid)
        # 8 rows/6 columns sharing a much bigger pane than their minimum
        # size needs - both should have grown well past their floors.
        assert min(_row_heights(grid)) > 1
        assert min(_column_render_widths(grid)) > grid.MIN_PAD_COLUMN_WIDTH


async def test_grid_columns_stay_at_the_minimum_on_a_narrow_terminal(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test(size=(80, 24)):
        grid = app.query_one(AssignmentGrid)
        # Not enough width for 6 comfortably-wide columns - clamps to the
        # floor (which still fits a typical filename) rather than
        # shrinking further and clipping sample names again.
        for column in grid.columns.values():
            assert column.get_render_width(grid) == grid.MIN_PAD_COLUMN_WIDTH + 2 * grid.cell_padding


async def test_assignments_and_cursor_survive_a_terminal_resize(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test(size=(140, 40)) as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("E", "4", Path("/samples/kick.wav"))
        grid.cursor_coordinate = Coordinate(4, 3)  # arbitrary cell - the row/bank it lands on doesn't matter here

        small_heights = _row_heights(grid)
        await pilot.resize_terminal(220, 60)
        await pilot.pause()

        assert _row_heights(grid) != small_heights  # actually relaid out
        assert _cell_name(grid, "E", "4") == "kick.wav"  # data survived the rebuild
        assert grid.cursor_coordinate == Coordinate(4, 3)  # cursor position restored


async def test_assign_updates_cell_and_configuration(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("E", "4", Path("/samples/kick.wav"))
        assert _cell_name(grid, "E", "4") == "kick.wav"
        assert grid.configuration.assignments[("E", "4")] == "/samples/kick.wav"


async def test_assign_shows_the_samples_size_beneath_its_name(tmp_path):
    sample = tmp_path / "kick.wav"
    sample.write_bytes(b"x" * 2000)
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("E", "4", sample)
        assert grid.get_cell("E", "4") == f"kick.wav\n{device.human_bytes(2000)}"


async def test_assign_falls_back_to_the_name_alone_when_the_file_is_missing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("E", "4", Path("/samples/gone.wav"))
        assert grid.get_cell("E", "4") == "gone.wav"


async def test_assign_without_an_active_configuration_does_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        assert grid.configuration is None
        grid.assign("E", "4", Path("/samples/kick.wav"))  # should be a no-op
        assert _cell_name(grid, "E", "4") == "-"


async def test_assign_to_the_same_pad_twice_last_one_wins(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.assign("A", "1", Path("/samples/snare.wav"))
        assert _cell_name(grid, "A", "1") == "snare.wav"
        assert grid.configuration.assignments[("A", "1")] == "/samples/snare.wav"


async def test_load_populates_cells_from_an_existing_configuration(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(
        name="Kit A",
        description="",
        created_at=now,
        modified_at=now,
        assignments={("A", "1"): "/samples/kick.wav", ("B", "2"): "/samples/snare.wav"},
    )
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        grid.load((tmp_path / "kit-a.json", config))
        assert _cell_name(grid, "A", "1") == "kick.wav"
        assert _cell_name(grid, "B", "2") == "snare.wav"
        assert _cell_name(grid, "C", "3") == "-"
        assert grid.configuration_path == tmp_path / "kit-a.json"
        assert grid.configuration is config


async def test_load_none_deactivates_the_grid(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", Path("/samples/kick.wav"))

        grid.load(None)

        assert _cell_name(grid, "A", "1") == "-"
        assert grid.configuration_path is None
        assert grid.configuration is None


async def test_d_clears_the_assignment_under_the_cursor(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.focus()
        grid.cursor_coordinate = Coordinate(0, 0)  # Bank A, pad 1
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert _cell_name(grid, "A", "1") == "-"
        assert ("A", "1") not in grid.configuration.assignments


async def test_d_on_an_empty_pad_does_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        grid.focus()
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert _cell_name(grid, "A", "1") == "-"


async def test_p_previews_the_sample_assigned_to_the_cursor_pad(tmp_path, wav_sample):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", wav_sample)
        grid.focus()
        grid.cursor_coordinate = Coordinate(0, 0)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert grid.last_previewed == wav_sample


async def test_i_shows_file_info_for_the_cursor_pad(tmp_path, wav_sample):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", wav_sample)
        grid.focus()
        grid.cursor_coordinate = Coordinate(0, 0)
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        preview = app.query_one("#preview", PreviewInfo)
        assert "kick.wav" in _status_text(preview)


async def test_i_on_an_empty_pad_clears_the_info_pane(tmp_path, wav_sample):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)  # active but empty - "i" should still clear the pane
        preview = app.query_one("#preview", PreviewInfo)
        preview.show(wav_sample)
        grid.focus()
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        assert _status_text(preview) == ""


async def test_assign_autosaves_to_disk_immediately(tmp_path):
    # No "s" any more (see AssignmentGrid's docstring) - assigning alone,
    # with no further keypress, must be enough to reach disk.
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        path, config = _activate_configuration(grid, name="Kit A")
        original_modified_at = config.modified_at

        grid.assign("A", "1", Path("/samples/kick.wav"))

        saved = list_configurations(tmp_path)
        assert len(saved) == 1  # written in place, not a second file
        assert saved[0][0] == path
        assert saved[0][1].assignments == {("A", "1"): "/samples/kick.wav"}
        assert saved[0][1].modified_at > original_modified_at


async def test_clear_autosaves_to_disk_immediately(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid, name="Kit A")
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.focus()
        grid.cursor_coordinate = Coordinate(0, 0)  # Bank A, pad 1
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        saved = list_configurations(tmp_path)
        assert saved[0][1].assignments == {}


async def test_assign_many_fills_pads_in_order_and_clears_the_rest(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("A", "1", Path("/samples/old.wav"))  # should not survive assign_many

        grid.assign_many("A", [Path("/samples/kick.wav"), Path("/samples/snare.wav")])

        assert _cell_name(grid, "A", "1") == "kick.wav"
        assert _cell_name(grid, "A", "2") == "snare.wav"
        for number in range(3, 7):
            assert _cell_name(grid, "A", str(number)) == "-"
        assert grid.configuration.assignments == {
            ("A", "1"): "/samples/kick.wav",
            ("A", "2"): "/samples/snare.wav",
        }


async def test_assign_many_drops_samples_past_the_sixth_pad(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        paths = [Path(f"/samples/s{i}.wav") for i in range(8)]

        grid.assign_many("B", paths)

        for number in range(1, 7):
            assert _cell_name(grid, "B", str(number)) == f"s{number - 1}.wav"
        assert len(grid.configuration.assignments) == 6


async def test_assign_many_without_an_active_configuration_does_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        assert grid.configuration is None
        grid.assign_many("B", [Path("/samples/kick.wav")])
        assert _cell_name(grid, "B", "1") == "-"


async def test_capital_d_with_no_assignments_does_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid)
        grid.focus()
        screens_before = len(app.screen_stack)

        await pilot.press("D")
        await pilot.pause()

        # no confirmation modal should have appeared - nothing to clear
        assert len(app.screen_stack) == screens_before


async def test_capital_d_asks_for_confirmation_before_clearing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid, name="Kit A")
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.assign("B", "1", Path("/samples/snare.wav"))
        grid.focus()

        await pilot.press("D")
        await pilot.pause()

        detail = app.screen.query_one("#detail", Static)
        assert "cannot be undone" in str(detail.render())
        assert _cell_name(grid, "A", "1") == "kick.wav"  # not cleared yet


async def test_capital_d_then_confirm_clears_every_pad(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid, name="Kit A")
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.assign("B", "1", Path("/samples/snare.wav"))
        grid.focus()

        await pilot.press("D")
        await pilot.pause()
        await pilot.press("enter")  # "Clear all pads in ..." is the first, highlighted option
        await pilot.pause()

        assert grid.configuration.assignments == {}
        assert _cell_name(grid, "A", "1") == "-"
        assert _cell_name(grid, "B", "1") == "-"
        saved = list_configurations(tmp_path)
        assert saved[0][1].assignments == {}


async def test_capital_d_then_cancel_clears_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one(AssignmentGrid)
        _activate_configuration(grid, name="Kit A")
        grid.assign("A", "1", Path("/samples/kick.wav"))
        grid.focus()

        await pilot.press("D")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert grid.configuration.assignments == {("A", "1"): "/samples/kick.wav"}
        assert _cell_name(grid, "A", "1") == "kick.wav"


async def test_set_assignments_without_an_active_configuration_does_nothing(tmp_path):
    app = AssignmentGridApp(tmp_path)
    async with app.run_test():
        grid = app.query_one(AssignmentGrid)
        assert grid.configuration is None
        grid.set_assignments({})  # should not raise despite nothing loaded
        assert _cell_name(grid, "A", "1") == "-"


async def test_bank_picker_direct_key_picks_immediately():
    app = App()
    async with app.run_test() as pilot:
        result = None

        def capture(value):
            nonlocal result
            result = value

        app.push_screen(BankPickerModal("kick.wav"), capture)
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        assert result == "E"


async def test_bank_picker_escape_cancels():
    app = App()
    async with app.run_test() as pilot:
        result = "unset"

        def capture(value):
            nonlocal result
            result = value

        app.push_screen(BankPickerModal("kick.wav"), capture)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert result is None


async def test_pad_picker_direct_key_picks_immediately():
    app = App()
    async with app.run_test() as pilot:
        result = None

        def capture(value):
            nonlocal result
            result = value

        app.push_screen(PadPickerModal("kick.wav", "E"), capture)
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        assert result == "4"


@pytest.fixture
def samples_dir(tmp_path):
    (tmp_path / "kick.wav").write_bytes(b"")
    return tmp_path


@pytest.fixture
def multi_samples_dir(tmp_path):
    for number in range(8):
        (tmp_path / f"sample{number}.wav").write_bytes(b"")
    return tmp_path


async def _node(browser, pilot, name):
    """Finds a sample/folder node by name - each configured samples
    directory is now its own root-level node (11-sample-paths.md), one
    level deeper than these fixtures' files used to sit when there was
    only ever a single samples_directory, and lazily loaded so it needs
    expanding (and a pause for that to land) before its children exist
    at all. Assumes exactly one configured directory, as every user of
    this helper's fixtures does."""
    root_node = browser.root.children[0]
    if not root_node.is_expanded:
        root_node.expand()
        await pilot.pause()
    return next(n for n in root_node.children if name in str(n.label))


async def test_a_then_bank_then_pad_assigns_the_highlighted_sample(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        kick_node = await _node(browser, pilot, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()

        assert _cell_name(grid, "E", "4") == "kick.wav"
        assert grid.configuration.assignments[("E", "4")] == str(samples_dir / "kick.wav")


async def test_a_without_an_active_configuration_notifies_and_opens_no_picker(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        kick_node = await _node(browser, pilot, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()

        screens_before = len(app.screen_stack)
        await pilot.press("a")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before  # no bank picker appeared
        assert len(notifications) == 1


async def test_a_then_escape_at_bank_step_assigns_nothing(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        kick_node = await _node(browser, pilot, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert grid.configuration.assignments == {}


async def test_a_then_escape_at_pad_step_assigns_nothing(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        kick_node = await _node(browser, pilot, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert grid.configuration.assignments == {}


async def test_opening_a_configuration_loads_it_into_the_assignment_grid(tmp_path):
    now = datetime(2026, 1, 1)
    config = Configuration(
        name="Kit A",
        description="",
        created_at=now,
        modified_at=now,
        assignments={("A", "1"): "/samples/kick.wav"},
    )
    save_configuration(config, tmp_path)

    app = ShmampleApp(samples_directories=[], configurations_dir=tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one("#configurations", ConfigList)
        grid = app.query_one("#assignments", AssignmentGrid)
        configs.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert _cell_name(grid, "A", "1") == "kick.wav"
        assert grid.configuration.name == "Kit A"


async def test_creating_a_configuration_activates_it_in_the_assignment_grid(tmp_path):
    # "n" is the only way to get a *brand new* configuration - it must
    # become the grid's active one immediately, or there'd be no way to
    # assign anything to it without a separate Enter afterwards.
    app = ShmampleApp(samples_directories=[], configurations_dir=tmp_path)
    async with app.run_test() as pilot:
        configs = app.query_one("#configurations", ConfigList)
        grid = app.query_one("#assignments", AssignmentGrid)
        assert grid.configuration is None

        configs.focus()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#name-input", Input).value = "Brand New Kit"
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert grid.configuration is not None
        assert grid.configuration.name == "Brand New Kit"
        assert grid.configuration_path is not None

        grid.assign("A", "1", Path("/samples/kick.wav"))
        assert _cell_name(grid, "A", "1") == "kick.wav"


async def test_autosaving_refreshes_the_configuration_list(tmp_path):
    app = ShmampleApp(samples_directories=[], configurations_dir=tmp_path)
    async with app.run_test() as pilot:
        grid = app.query_one("#assignments", AssignmentGrid)
        configs = app.query_one("#configurations", ConfigList)
        # Saved directly to disk, bypassing ConfigList's own "n" - the
        # list hasn't picked it up yet, which is exactly what this test
        # is checking gets fixed by the assign below.
        _activate_configuration(grid, name="New Kit")
        assert configs.entries == []

        grid.assign("A", "1", Path("/samples/kick.wav"))
        await pilot.pause()

        assert [c.name for _, c in configs.entries] == ["New Kit"]


async def test_a_with_a_multi_selection_assigns_to_pads_in_selection_order(multi_samples_dir):
    app = ShmampleApp(samples_directories=[multi_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        browser.focus()
        await pilot.pause()

        # Select sample1 then sample0 (reverse order) - assignment should
        # follow that pick order, not tree/alphabetical order.
        browser.move_cursor(await _node(browser, pilot, "sample1.wav"))
        await pilot.pause()
        await pilot.press("space")
        browser.move_cursor(await _node(browser, pilot, "sample0.wav"))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()

        assert _cell_name(grid, "B", "1") == "sample1.wav"
        assert _cell_name(grid, "B", "2") == "sample0.wav"
        assert grid.configuration.assignments == {
            ("B", "1"): str(multi_samples_dir / "sample1.wav"),
            ("B", "2"): str(multi_samples_dir / "sample0.wav"),
        }


async def test_a_with_a_multi_selection_clears_selection_markers_after_assigning(
    multi_samples_dir,
):
    app = ShmampleApp(samples_directories=[multi_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        node = await _node(browser, pilot, "sample0.wav")
        browser.focus()
        browser.move_cursor(node)
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert browser.selected == [node]

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert browser.selected == []


async def test_a_with_a_multi_selection_replaces_the_whole_bank(multi_samples_dir):
    app = ShmampleApp(samples_directories=[multi_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        grid.assign("D", "1", Path("/samples/old.wav"))
        browser.focus()
        browser.move_cursor(await _node(browser, pilot, "sample0.wav"))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        assert _cell_name(grid, "D", "1") == "sample0.wav"
        assert ("D", "1") in grid.configuration.assignments
        assert grid.configuration.assignments[("D", "1")] != "/samples/old.wav"


async def test_a_with_exactly_six_selected_fills_every_pad(multi_samples_dir):
    app = ShmampleApp(samples_directories=[multi_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        browser.focus()
        await pilot.pause()

        for number in range(6):
            browser.move_cursor(await _node(browser, pilot, f"sample{number}.wav"))
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("f")
        await pilot.pause()

        for number in range(6):
            assert _cell_name(grid, "F", str(number + 1)) == f"sample{number}.wav"
        assert len(grid.configuration.assignments) == 6


async def test_a_with_an_active_selection_ignores_the_cursor_file(multi_samples_dir):
    # Regression check for the branch in action_start_assign: with a
    # selection active, "a" must go through the multi-assign path even
    # though the cursor is sitting on a *different*, unselected file.
    app = ShmampleApp(samples_directories=[multi_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        grid = app.query_one("#assignments", AssignmentGrid)
        _activate_configuration(grid)
        browser.focus()
        browser.move_cursor(await _node(browser, pilot, "sample0.wav"))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        browser.move_cursor(await _node(browser, pilot, "sample1.wav"))  # cursor moves, selection doesn't
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()

        assert _cell_name(grid, "G", "1") == "sample0.wav"
        assert grid.configuration.assignments == {("G", "1"): str(multi_samples_dir / "sample0.wav")}
