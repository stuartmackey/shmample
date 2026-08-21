from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree

from shmample.widgets.directory_picker import DirectoryPickerModal


class PickerApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.result: Path | None | str = "unset"

    def compose(self) -> ComposeResult:
        yield from ()

    def open_picker(self, start_directory: Path) -> None:
        def handle_result(result: Path | None) -> None:
            self.result = result

        self.push_screen(DirectoryPickerModal(start_directory), handle_result)


def _make_tree(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_bytes(b"")
    return tmp_path


async def test_files_are_filtered_out(tmp_path):
    directory = _make_tree(tmp_path)
    app = PickerApp()
    async with app.run_test() as pilot:
        app.open_picker(directory)
        await pilot.pause()
        tree = app.screen.query_one(DirectoryTree)
        labels = [str(n.label) for n in tree.root.children]
        assert labels == ["sub"]


async def test_ctrl_s_chooses_the_highlighted_directory(tmp_path):
    directory = _make_tree(tmp_path)
    app = PickerApp()
    async with app.run_test() as pilot:
        app.open_picker(directory)
        await pilot.pause()
        tree = app.screen.query_one(DirectoryTree)
        sub_node = next(n for n in tree.root.children if str(n.label) == "sub")
        tree.move_cursor(sub_node)
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.result == directory / "sub"


async def test_escape_cancels_with_none(tmp_path):
    directory = _make_tree(tmp_path)
    app = PickerApp()
    async with app.run_test() as pilot:
        app.open_picker(directory)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert app.result is None


async def test_vim_keys_navigate(tmp_path):
    directory = _make_tree(tmp_path)
    app = PickerApp()
    async with app.run_test() as pilot:
        app.open_picker(directory)
        await pilot.pause()
        tree = app.screen.query_one(DirectoryTree)
        tree.focus()
        await pilot.pause()

        await pilot.press("j")  # -1 -> root
        await pilot.press("j")  # root -> sub
        await pilot.pause()
        assert str(tree.cursor_node.label) == "sub"

        await pilot.press("l")  # vim expand
        await pilot.pause()
        assert tree.cursor_node.is_expanded

        await pilot.press("h")  # vim "up a level" -> parent
        await pilot.pause()
        assert tree.cursor_node is tree.root
