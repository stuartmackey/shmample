from pathlib import Path

import pytest
from rich.style import Style

from shmample.app import ShmampleApp
from shmample.settings import load_settings
from shmample.widgets.config_list import ConfigList
from shmample.widgets.device_panel import DevicePanel
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.main_column import MainColumn
from shmample.widgets.preview_info import PreviewInfo


@pytest.fixture
def samples_dir(tmp_path):
    (tmp_path / "kick.wav").write_bytes(b"")
    (tmp_path / "notes.txt").write_bytes(b"")
    drums = tmp_path / "Drums"
    drums.mkdir()
    (drums / "snare.WAV").write_bytes(b"")  # mixed-case extension
    (drums / "readme.md").write_bytes(b"")
    empty = tmp_path / "Empty"  # contains nothing valid anywhere - should be hidden
    empty.mkdir()
    (empty / "readme.txt").write_bytes(b"")
    # nothing directly inside Nested, but Sub (two levels down) has a wav -
    # Nested should still show, proving the check is recursive, not just
    # a peek at immediate children
    nested = tmp_path / "Nested"
    sub = nested / "Sub"
    sub.mkdir(parents=True)
    (sub / "tom.wav").write_bytes(b"")
    return tmp_path


@pytest.fixture
def many_samples_dir(tmp_path):
    for number in range(7):
        (tmp_path / f"sample{number}.wav").write_bytes(b"")
    return tmp_path


def _labels(nodes):
    return [str(n.label) for n in nodes]


async def _root(browser: FileBrowser, pilot, directory: Path):
    """The root-level node for `directory`, expanded and loaded - each
    configured samples directory is its own root-level node
    (11-sample-paths.md, "each path appears as a root node")."""
    root_node = next(n for n in browser.root.children if str(directory) in str(n.label))
    if not root_node.is_expanded:
        root_node.expand()
        await pilot.pause()
    return root_node


def _node(root_node, name):
    return next(n for n in root_node.children if name in str(n.label))


async def test_root_nodes_are_labelled_by_full_path_and_start_collapsed(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test():
        browser = app.query_one("#files", FileBrowser)
        assert _labels(browser.root.children) == [str(samples_dir)]
        assert not browser.root.children[0].is_expanded


async def test_focusing_the_browser_highlights_the_first_root_node(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        assert browser.cursor_line == -1  # untouched, nothing highlighted yet

        browser.focus()
        await pilot.pause()

        assert browser.cursor_node is browser.root.children[0]


async def test_refocusing_the_browser_keeps_an_already_moved_cursor(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = ShmampleApp(samples_directories=[first, second])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        configs = app.query_one("#configurations")

        browser.focus()
        await pilot.pause()
        browser.move_cursor(browser.root.children[1])
        await pilot.pause()

        configs.focus()  # away...
        await pilot.pause()
        browser.focus()  # ...and back
        await pilot.pause()

        assert browser.cursor_node is browser.root.children[1]


async def test_multiple_configured_directories_each_get_their_own_root_node(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "kick.wav").write_bytes(b"")
    (second / "snare.wav").write_bytes(b"")
    app = ShmampleApp(samples_directories=[first, second])
    async with app.run_test():
        browser = app.query_one("#files", FileBrowser)
        assert _labels(browser.root.children) == [str(first), str(second)]


async def test_filters_to_directories_and_wav_files_case_insensitive(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        top_level = _labels(root_node.children)
        assert any("kick.wav" in l for l in top_level)
        assert any("Drums" in l for l in top_level)
        assert not any("notes.txt" in l for l in top_level)


async def test_folder_with_no_wav_anywhere_in_its_subtree_is_hidden(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        top_level = _labels(root_node.children)
        assert not any("Empty" in l for l in top_level)


async def test_folder_with_wav_only_in_a_nested_subfolder_is_shown(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        top_level = _labels(root_node.children)
        assert any("Nested" in l for l in top_level)

        nested_node = _node(root_node, "Nested")
        browser.focus()
        browser.move_cursor(nested_node)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        sub_labels = _labels(nested_node.children)
        assert any("Sub" in l for l in sub_labels)


async def test_enter_on_folder_toggles_expand_not_preview(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert drums_node.is_expanded
        assert _labels(drums_node.children) == ["snare.WAV"]
        assert browser.last_previewed is None
        await pilot.press("enter")
        await pilot.pause()
        assert not drums_node.is_expanded


async def test_enter_on_file_previews_it(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert browser.last_previewed == samples_dir / "kick.wav"


async def test_p_key_previews_file_but_not_folder(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()
        await pilot.press("p")
        assert browser.last_previewed is None  # no-op on a folder

        kick_node = _node(root_node, "kick.wav")
        browser.move_cursor(kick_node)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert browser.last_previewed == samples_dir / "kick.wav"


async def test_vim_keys_navigate_and_toggle(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()

        await pilot.press("l")  # vim expand
        await pilot.pause()
        assert drums_node.is_expanded

        await pilot.press("j")  # vim down, onto snare.WAV
        await pilot.pause()
        assert str(browser.cursor_node.label) == "snare.WAV"

        await pilot.press("h")  # vim "up a level" -> parent
        await pilot.pause()
        assert browser.cursor_node is drums_node

        await pilot.press("k")  # vim up
        await pilot.pause()
        assert browser.cursor_node is root_node


async def test_gg_then_shift_g_jump_to_top_and_bottom_root(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "kick.wav").write_bytes(b"")
    (second / "snare.wav").write_bytes(b"")
    app = ShmampleApp(samples_directories=[first, second])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        browser.focus()
        await pilot.pause()

        await pilot.press("G")
        await pilot.pause()
        assert browser.cursor_node is browser.root.children[1]

        await pilot.press("g")
        await pilot.press("g")
        await pilot.pause()
        assert browser.cursor_node is browser.root.children[0]


async def test_expanding_a_root_collapses_the_previously_expanded_root(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "kick.wav").write_bytes(b"")
    (second / "snare.wav").write_bytes(b"")
    app = ShmampleApp(samples_directories=[first, second])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        first_node, second_node = browser.root.children
        browser.focus()
        browser.move_cursor(first_node)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert first_node.is_expanded

        browser.move_cursor(second_node)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()

        assert second_node.is_expanded
        assert not first_node.is_expanded


async def test_expanding_a_nested_subfolder_does_not_collapse_its_own_root(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()

        await pilot.press("l")  # expand the nested Drums folder
        await pilot.pause()

        assert drums_node.is_expanded
        assert root_node.is_expanded  # accordion only applies at the root level


def _is_selected_styled(browser, node) -> bool:
    label = browser.render_label(node, Style(), Style())
    return any(span.style == FileBrowser.SELECTED_STYLE for span in label.spans)


async def test_space_selects_and_deselects_a_file(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()
        unselected_plain = browser.render_label(kick_node, Style(), Style()).plain

        await pilot.press("space")
        await pilot.pause()
        assert browser.selected == [kick_node]
        label = browser.render_label(kick_node, Style(), Style())
        assert label.plain == unselected_plain  # recoloured, not prefixed - text doesn't shift
        assert _is_selected_styled(browser, kick_node)

        await pilot.press("space")
        await pilot.pause()
        assert browser.selected == []
        assert not _is_selected_styled(browser, kick_node)


async def test_space_on_a_folder_still_toggles_expand_not_select(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        drums_node = _node(root_node, "Drums")
        browser.focus()
        browser.move_cursor(drums_node)
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()
        assert drums_node.is_expanded
        assert browser.selected == []


async def test_space_refuses_a_seventh_selection(many_samples_dir):
    app = ShmampleApp(samples_directories=[many_samples_dir])
    notifications = []
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, many_samples_dir)
        browser.focus()
        await pilot.pause()

        for number in range(7):
            browser.move_cursor(_node(root_node, f"sample{number}.wav"))
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()

        assert len(browser.selected) == 6
        assert _node(root_node, "sample6.wav") not in browser.selected
        assert len(notifications) == 1
        assert "6" in notifications[0]


async def test_deselecting_makes_room_for_another_selection(many_samples_dir):
    app = ShmampleApp(samples_directories=[many_samples_dir])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, many_samples_dir)
        browser.focus()
        await pilot.pause()

        for number in range(6):
            browser.move_cursor(_node(root_node, f"sample{number}.wav"))
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()

        browser.move_cursor(_node(root_node, "sample0.wav"))
        await pilot.pause()
        await pilot.press("space")  # deselect, freeing a slot
        await pilot.pause()

        browser.move_cursor(_node(root_node, "sample6.wav"))
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

        assert len(browser.selected) == 6
        assert _node(root_node, "sample6.wav") in browser.selected
        assert _node(root_node, "sample0.wav") not in browser.selected


async def test_no_directories_configured_shows_an_empty_tree():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test():
        browser = app.query_one("#files", FileBrowser)
        assert list(browser.root.children) == []


async def test_missing_directory_shows_as_a_root_with_no_children(tmp_path):
    missing = tmp_path / "does-not-exist"
    app = ShmampleApp(samples_directories=[missing])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, missing)
        assert list(root_node.children) == []


async def test_shift_a_adds_a_new_root_and_persists_it(tmp_path, monkeypatch):
    home = tmp_path / "home"
    new_samples = home / "MySamples"
    new_samples.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)

    settings_path = tmp_path / "settings.json"
    app = ShmampleApp(samples_directories=[], settings_path=settings_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        browser.focus()
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

        tree = app.screen.query_one("_DirsOnlyDirectoryTree")
        my_samples_node = next(n for n in tree.root.children if "MySamples" in str(n.label))
        tree.move_cursor(my_samples_node)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(new_samples)]
        assert browser.samples_directories == [new_samples]
        assert load_settings(settings_path).samples_directories == [new_samples]


async def test_shift_a_then_escape_adds_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    settings_path = tmp_path / "settings.json"
    app = ShmampleApp(samples_directories=[], settings_path=settings_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        browser.focus()
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert list(browser.root.children) == []
        assert not settings_path.exists()


async def test_shift_d_on_a_root_removes_it_and_persists(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    settings_path = tmp_path / "settings.json"
    app = ShmampleApp(samples_directories=[first, second], settings_path=settings_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        browser.focus()
        browser.move_cursor(browser.root.children[0])
        await pilot.pause()

        await pilot.press("D")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(second)]
        assert browser.samples_directories == [second]
        assert load_settings(settings_path).samples_directories == [second]


async def test_shift_d_on_a_file_or_folder_does_nothing(samples_dir, tmp_path):
    settings_path = tmp_path / "settings.json"
    app = ShmampleApp(samples_directories=[samples_dir], settings_path=settings_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()
        browser.move_cursor(kick_node)
        await pilot.pause()

        await pilot.press("D")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(samples_dir)]
        assert browser.samples_directories == [samples_dir]


async def test_check_action_hides_remove_path_off_a_root(samples_dir, tmp_path):
    settings_path = tmp_path / "settings.json"
    app = ShmampleApp(samples_directories=[samples_dir], settings_path=settings_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _root(browser, pilot, samples_dir)
        kick_node = _node(root_node, "kick.wav")
        browser.focus()

        browser.move_cursor(root_node)
        await pilot.pause()
        assert browser.check_action("remove_samples_directory", ()) is True

        browser.move_cursor(kick_node)
        await pilot.pause()
        assert browser.check_action("remove_samples_directory", ()) is False


async def test_shift_d_collapsing_the_expanded_root_clears_the_accordion_state(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = ShmampleApp(samples_directories=[first, second])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        first_node, second_node = browser.root.children
        browser.focus()
        browser.move_cursor(first_node)
        await pilot.pause()
        await pilot.press("l")  # expand it
        await pilot.pause()

        browser.move_cursor(first_node)
        await pilot.pause()
        await pilot.press("D")
        await pilot.pause()

        # Removing the previously-expanded root shouldn't leave stale
        # accordion state pointing at a node that no longer exists -
        # expanding the remaining root must still work.
        browser.move_cursor(second_node)
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        assert second_node.is_expanded


async def test_column_takes_a_third_of_the_width_and_full_height(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test(size=(120, 40)):
        column = app.query_one(MainColumn)
        # outer_size is the full allocated box (border included); .size
        # would be a few columns/rows smaller once the border and any
        # scrollbar are subtracted, which isn't what "1/3 width, full
        # height" is asking about. Full height is 40 minus the docked
        # Footer's one row.
        assert column.outer_size.height == 39
        assert 39 <= column.outer_size.width <= 40


async def test_panes_split_the_column_height_one_three_one(samples_dir):
    app = ShmampleApp(samples_directories=[samples_dir])
    async with app.run_test(size=(120, 40)):
        device_panel = app.query_one(DevicePanel)
        configs = app.query_one(ConfigList)
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        heights = (
            device_panel.outer_size.height
            + configs.outer_size.height
            + browser.outer_size.height
            + preview.outer_size.height
        )
        assert heights == 39  # 40 minus the docked Footer's one row
        # DevicePanel is fixed-height (3, not a share) - the remaining
        # 1:3:1 split happens over whatever's left afterwards.
        assert device_panel.outer_size.height == 3
        assert configs.outer_size.height == 7
        assert browser.outer_size.height == 21
        assert preview.outer_size.height == 8
