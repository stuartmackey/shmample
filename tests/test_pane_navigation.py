from shmample.app import ShmampleApp
from shmample.widgets.assignment_grid import AssignmentGrid
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.holding_area import HoldingArea
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.tag_browser import TagBrowser


async def test_ctrl_hjkl_walks_the_full_pane_layout():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        app.query_one("#device").focus()
        await pilot.pause()

        await pilot.press("ctrl+j")
        assert isinstance(app.focused, ConfigList)

        await pilot.press("ctrl+j")
        assert isinstance(app.focused, FileBrowser)

        await pilot.press("ctrl+l")
        assert isinstance(app.focused, TagBrowser)

        await pilot.press("ctrl+l")
        assert isinstance(app.focused, HoldingArea)

        await pilot.press("ctrl+l")
        assert isinstance(app.focused, AssignmentGrid)

        await pilot.press("ctrl+h")
        assert isinstance(app.focused, HoldingArea)

        await pilot.press("ctrl+h")
        assert isinstance(app.focused, TagBrowser)

        await pilot.press("ctrl+j")
        assert isinstance(app.focused, PreviewInfo)

        await pilot.press("ctrl+k")
        assert isinstance(app.focused, TagBrowser)

        await pilot.press("ctrl+h")
        assert isinstance(app.focused, FileBrowser)

        await pilot.press("ctrl+k")
        assert isinstance(app.focused, ConfigList)

        await pilot.press("ctrl+k")
        assert isinstance(app.focused, DevicePanel)


async def test_ctrl_hjkl_is_a_noop_at_layout_edges():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        app.query_one("#device").focus()
        await pilot.pause()

        await pilot.press("ctrl+k")
        assert isinstance(app.focused, DevicePanel)

        await pilot.press("ctrl+h")
        assert isinstance(app.focused, DevicePanel)


async def test_backspace_also_moves_left():
    # Most terminals send the same byte for ctrl+h and plain backspace,
    # which Textual's legacy ANSI decoding reports as the "backspace" key
    # rather than "ctrl+h" - so real ctrl+h keypresses arrive here as
    # "backspace" far more often than as "ctrl+h" itself.
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        app.query_one("#assignments").focus()
        await pilot.pause()

        await pilot.press("backspace")
        assert isinstance(app.focused, HoldingArea)


async def test_ctrl_hjkl_does_not_clash_with_pane_own_hjkl_bindings():
    # ConfigList/FileBrowser bind plain h/j/k/l for in-pane movement, so
    # the ctrl-modified variants need to keep reaching the App-level
    # fallback rather than being swallowed as unmodified keys.
    app = ShmampleApp(samples_directories=[])
    async with app.run_test() as pilot:
        configs = app.query_one(ConfigList)
        configs.focus()
        await pilot.pause()
        await pilot.press("ctrl+j")
        assert isinstance(app.focused, FileBrowser)
