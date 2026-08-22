from shmample.app import ShmampleApp
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.holding_area import HoldingArea
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.tag_browser import TagBrowser


async def test_number_keys_jump_focus_to_named_panes():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        await pilot.press("2")
        assert isinstance(app.focused, ConfigList)

        await pilot.press("3")
        assert isinstance(app.focused, FileBrowser)

        await pilot.press("4")
        assert isinstance(app.focused, TagBrowser)

        await pilot.press("5")
        assert isinstance(app.focused, PreviewInfo)

        await pilot.press("6")
        assert isinstance(app.focused, HoldingArea)

        await pilot.press("7")
        assert isinstance(app.focused, AssignmentGrid)

        await pilot.press("1")
        assert isinstance(app.focused, DevicePanel)


async def test_digit_keys_do_not_clash_with_pane_own_bindings():
    # ConfigList/FileBrowser's own BINDINGS (j/k/n/d/h/l/p) contain no
    # digits, so the App-level fallback should always win for 1-4
    # regardless of which pane currently has focus.
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("3")
        assert isinstance(app.focused, FileBrowser)


async def test_every_pane_highlights_its_border_when_focused():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        selectors = [
            "#device",
            "#configurations",
            "#files",
            "#tags",
            "#preview",
            "#holding",
            "#assignments",
        ]
        for selector in selectors:
            widget = app.query_one(selector)
            widget.focus()
            await pilot.pause()
            focused_border = widget.styles.border_top
            for other in selectors:
                if other == selector:
                    continue
                assert app.query_one(other).styles.border_top != focused_border
