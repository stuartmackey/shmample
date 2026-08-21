from shmample.app import ShmampleApp
from shmample.widgets.file_browser import FileBrowser


def _labels(nodes):
    return [str(n.label) for n in nodes]


def _node(node, name):
    return next(n for n in node.children if name in str(n.label))


async def _expanded_root(browser: FileBrowser, pilot):
    root_node = browser.root.children[0]
    if not root_node.is_expanded:
        root_node.expand()
        await pilot.pause()
    return root_node


def _fixture(tmp_path):
    pack_a = tmp_path / "PackA"
    kick_dir = pack_a / "Kick"
    kick_dir.mkdir(parents=True)
    (kick_dir / "bd.wav").write_bytes(b"")
    pack_b = tmp_path / "PackB"
    pack_b.mkdir()
    (pack_b / "snare.wav").write_bytes(b"")
    return tmp_path


async def test_dot_narrows_the_displayed_root_to_the_highlighted_folder(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "PackA"))
        await pilot.pause()

        await pilot.press(".")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(tmp_path / "PackA")]
        # Focusing auto-expands the new sole root straight away.
        assert browser.root.children[0].is_expanded
        assert browser.cursor_node is browser.root.children[0]


async def test_dot_on_a_file_does_nothing(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        pack_b = _node(root_node, "PackB")
        pack_b.expand()
        await pilot.pause()
        browser.focus()
        browser.move_cursor(_node(pack_b, "snare.wav"))
        await pilot.pause()

        await pilot.press(".")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(tmp_path)]


async def test_dot_on_the_sole_displayed_root_is_a_no_op(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(root_node)
        await pilot.pause()

        await pilot.press(".")
        await pilot.pause()

        assert _labels(browser.root.children) == [str(tmp_path)]
        assert browser._root_focus_stack == []


async def test_h_pops_focus_back_out_one_level_at_a_time(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()

        browser.move_cursor(_node(root_node, "PackA"))
        await pilot.pause()
        await pilot.press(".")  # focus: [tmp_path] -> [PackA]
        await pilot.pause()

        pack_a_root = browser.root.children[0]
        browser.move_cursor(_node(pack_a_root, "Kick"))
        await pilot.pause()
        await pilot.press(".")  # focus: [PackA] -> [Kick]
        await pilot.pause()

        assert _labels(browser.root.children) == [str(tmp_path / "PackA" / "Kick")]

        # Cursor's on the sole displayed root (Kick) - h has nowhere to go
        # within the current scope, so it pops back to [PackA] instead.
        await pilot.press("h")
        await pilot.pause()
        assert _labels(browser.root.children) == [str(tmp_path / "PackA")]

        # One more pop gets back to the original, unfocused, full scope.
        await pilot.press("h")
        await pilot.pause()
        assert _labels(browser.root.children) == [str(tmp_path)]
        assert browser._root_focus_stack == []


async def test_h_still_moves_to_a_real_parent_node_within_a_focused_scope(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "PackA"))
        await pilot.pause()
        await pilot.press(".")
        await pilot.pause()

        pack_a_root = browser.root.children[0]
        kick_node = _node(pack_a_root, "Kick")
        browser.move_cursor(kick_node)
        await pilot.pause()
        await pilot.press("l")  # expand Kick
        await pilot.pause()
        browser.move_cursor(_node(kick_node, "bd.wav"))
        await pilot.pause()

        await pilot.press("h")
        await pilot.pause()

        # Ordinary "up to parent" within the still-focused scope - not a
        # pop, since bd.wav's parent (Kick) isn't the displayed root itself.
        assert browser.cursor_node is kick_node
        assert _labels(browser.root.children) == [str(tmp_path / "PackA")]


async def test_add_and_remove_path_are_disabled_while_focused(tmp_path):
    _fixture(tmp_path)
    app = ShmampleApp(samples_directories=[tmp_path])
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(root_node)
        await pilot.pause()

        assert browser.check_action("add_samples_directory", ()) is True
        assert browser.check_action("remove_samples_directory", ()) is True

        browser.move_cursor(_node(root_node, "PackA"))
        await pilot.pause()
        await pilot.press(".")
        await pilot.pause()
        browser.move_cursor(browser.root.children[0])
        await pilot.pause()

        assert browser.check_action("add_samples_directory", ()) is False
        assert browser.check_action("remove_samples_directory", ()) is False
