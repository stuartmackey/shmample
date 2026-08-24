from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Label

from shmample.app import ShmampleApp
from shmample.config_store import Configuration, Pack, list_configurations, save_configuration
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.config_list import ConfigList
from shmample.widgets.holding_area import HoldingArea


class HoldingAreaApp(App):
    def __init__(self, configurations_dir) -> None:
        super().__init__()
        self.configurations_dir = configurations_dir

    def compose(self) -> ComposeResult:
        yield HoldingArea(self.configurations_dir, id="holding")
        yield AssignmentGrid(self.configurations_dir, id="assignments")


def _activate_configuration(
    holding: HoldingArea, name: str = "Kit", holding_paths: list[str] = ()
) -> tuple[Path, Configuration]:
    now = datetime(2026, 1, 1)
    config = Configuration(
        pack=Pack(
            name=name,
            description="",
            created_at=now,
            modified_at=now,
            holding=list(holding_paths),
        )
    )
    path = save_configuration(config, holding.configurations_dir)
    holding.load((path, config))
    return path, config


async def test_starts_with_a_placeholder_row_and_no_configuration(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test():
        holding = app.query_one(HoldingArea)
        assert holding.configuration is None
        assert [str(label.render()) for label in holding.query(Label)] == [
            "Nothing held yet"
        ]


async def test_load_populates_from_an_existing_configuration(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(
            holding, holding_paths=["/samples/kick.wav", "/samples/snare.wav"]
        )
        await pilot.pause()

        labels = [str(label.render()) for label in holding.query(Label)]
        assert labels == ["kick.wav", "snare.wav"]


async def test_load_none_deactivates_and_shows_the_placeholder(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding, holding_paths=["/samples/kick.wav"])
        await pilot.pause()

        holding.load(None)
        await pilot.pause()

        assert holding.configuration is None
        assert holding.configuration_path is None
        assert [str(label.render()) for label in holding.query(Label)] == [
            "Nothing held yet"
        ]


async def test_add_samples_appends_new_ones_in_order(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test():
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding)

        added, already_held = holding.add_samples(
            [Path("/samples/kick.wav"), Path("/samples/snare.wav")]
        )

        assert added == [Path("/samples/kick.wav"), Path("/samples/snare.wav")]
        assert already_held == []
        assert holding.configuration.pack.holding == ["/samples/kick.wav", "/samples/snare.wav"]


async def test_add_samples_skips_already_held_without_duplicating(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test():
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding, holding_paths=["/samples/kick.wav"])

        added, already_held = holding.add_samples(
            [Path("/samples/kick.wav"), Path("/samples/snare.wav")]
        )

        assert added == [Path("/samples/snare.wav")]
        assert already_held == [Path("/samples/kick.wav")]
        assert holding.configuration.pack.holding == ["/samples/kick.wav", "/samples/snare.wav"]


async def test_add_samples_without_an_active_configuration_does_nothing(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test():
        holding = app.query_one(HoldingArea)
        assert holding.configuration is None

        added, already_held = holding.add_samples([Path("/samples/kick.wav")])

        assert added == []
        assert already_held == []


async def test_add_samples_autosaves_to_disk_immediately(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test():
        holding = app.query_one(HoldingArea)
        path, _ = _activate_configuration(holding)

        holding.add_samples([Path("/samples/kick.wav")])

        [(_, loaded)] = list_configurations(tmp_path)
        assert loaded.pack.holding == ["/samples/kick.wav"]


async def test_d_removes_the_cursor_item(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(
            holding, holding_paths=["/samples/kick.wav", "/samples/snare.wav"]
        )
        holding.focus()
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        assert holding.configuration.pack.holding == ["/samples/snare.wav"]
        labels = [str(label.render()) for label in holding.query(Label)]
        assert labels == ["snare.wav"]
        [(_, loaded)] = list_configurations(tmp_path)
        assert loaded.pack.holding == ["/samples/snare.wav"]


async def test_d_with_nothing_held_does_nothing(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding)
        holding.focus()
        await pilot.pause()

        await pilot.press("d")  # should not raise
        await pilot.pause()

        assert holding.configuration.pack.holding == []


async def test_a_opens_the_assign_chord_for_the_cursor_item_and_assigns(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        grid = app.query_one(AssignmentGrid)
        path, config = _activate_configuration(holding, holding_paths=["/samples/kick.wav"])
        grid.load((path, config))  # same shared Configuration, as app.py wires up
        holding.focus()
        await pilot.pause()

        await pilot.press("a")
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()

        assert grid.configuration.assignments[("E", "4")] == "/samples/kick.wav"
        # The held sample itself is untouched by assigning it to a pad -
        # a sample can still be placed on more than one pad later.
        assert holding.configuration.pack.holding == ["/samples/kick.wav"]


async def test_a_with_nothing_held_does_nothing(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding)
        holding.focus()
        await pilot.pause()

        screens_before = len(app.screen_stack)
        await pilot.press("a")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before  # no bank picker appeared


async def test_enter_previews_the_cursor_item(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        kick = tmp_path / "kick.wav"
        kick.write_bytes(b"")
        _activate_configuration(holding, holding_paths=[str(kick)])
        holding.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert holding.last_previewed == kick


async def test_p_key_previews_the_cursor_item(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        kick = tmp_path / "kick.wav"
        kick.write_bytes(b"")
        _activate_configuration(holding, holding_paths=[str(kick)])
        holding.focus()
        await pilot.pause()

        await pilot.press("p")
        await pilot.pause()

        assert holding.last_previewed == kick


async def test_preview_with_nothing_held_does_nothing(tmp_path):
    app = HoldingAreaApp(tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one(HoldingArea)
        _activate_configuration(holding)
        holding.focus()
        await pilot.pause()

        await pilot.press("p")  # should not raise
        await pilot.pause()

        assert holding.last_previewed is None


async def test_adding_to_holding_refreshes_the_configuration_list(tmp_path):
    app = ShmampleApp(samples_directories=[], configurations_dir=tmp_path)
    async with app.run_test() as pilot:
        holding = app.query_one("#holding", HoldingArea)
        configs = app.query_one("#packs", ConfigList)
        # Saved directly to disk, bypassing ConfigList's own "n" - the
        # list hasn't picked it up yet, which is exactly what this test
        # is checking gets fixed by the add below.
        _activate_configuration(holding, name="New Kit")
        assert configs.entries == []

        holding.add_samples([Path("/samples/kick.wav")])
        await pilot.pause()

        assert [c.pack.name for _, c in configs.entries] == ["New Kit"]
