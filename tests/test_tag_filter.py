from shmample.app import ShmampleApp
from shmample.tag_store import auto_assign_tag
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.tag_browser import TagBrowser


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


async def _wait_for_tag_filter(app, pilot):
    workers = [w for w in app.workers if w.group == "tag-filter"]
    if workers:
        await app.workers.wait_for_complete(workers)
    await pilot.pause()


def _fixture(tmp_path):
    """Two packs: PackA has a kick tagged "kick"+"808" and a plain snare;
    PackB has only a snare tagged "808" (no kick anywhere) - enough to
    exercise AND, hiding an empty folder, and a folder that survives with
    only some of its contents matching."""
    pack_a = tmp_path / "PackA"
    pack_a.mkdir()
    (pack_a / "kick.wav").write_bytes(b"")
    (pack_a / "snare.wav").write_bytes(b"")
    pack_b = tmp_path / "PackB"
    pack_b.mkdir()
    (pack_b / "snare.wav").write_bytes(b"")
    return pack_a, pack_b


async def test_selecting_a_tag_filters_the_sample_tree_to_matching_files(tmp_path):
    pack_a, pack_b = _fixture(tmp_path)
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)

    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        await _expanded_root(browser, pilot)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")  # select "kick"
        await pilot.pause()

        root_node = browser.root.children[0]
        # PackB has no kick anywhere - hidden entirely, not shown empty.
        assert _labels(root_node.children) == ["PackA"]
        pack_a_node = root_node.children[0]
        pack_a_node.expand()
        await pilot.pause()
        assert _labels(pack_a_node.children) == ["kick.wav"]


async def test_multiple_selected_tags_are_anded(tmp_path):
    pack_a, pack_b = _fixture(tmp_path)
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)
    auto_assign_tag(pack_a / "kick.wav", "808", db_path)
    auto_assign_tag(pack_b / "snare.wav", "808", db_path)

    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        await _expanded_root(browser, pilot)
        tags.focus()
        await pilot.pause()

        # tags list, sorted: "808", "kick" - select both.
        await pilot.press("space")
        await pilot.press("j")
        await pilot.press("space")
        await pilot.pause()
        assert tags.selected_tags == {"808", "kick"}

        root_node = browser.root.children[0]
        # Only PackA/kick.wav carries both tags together - PackB's snare
        # only has "808", not "kick", so PackB is hidden entirely.
        assert _labels(root_node.children) == ["PackA"]
        pack_a_node = root_node.children[0]
        pack_a_node.expand()
        await pilot.pause()
        assert _labels(pack_a_node.children) == ["kick.wav"]


async def test_deselecting_every_tag_restores_the_full_tree(tmp_path):
    pack_a, pack_b = _fixture(tmp_path)
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)

    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        root_node = await _expanded_root(browser, pilot)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()
        assert _labels(browser.root.children[0].children) == ["PackA"]

        await pilot.press("space")  # deselect again
        await pilot.pause()

        assert _labels(browser.root.children[0].children) == ["PackA", "PackB"]


async def test_a_folder_with_some_but_not_all_matching_contents_still_shows(tmp_path):
    pack_a, _pack_b = _fixture(tmp_path)
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)
    # pack_a/snare.wav is deliberately left untagged.

    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        await _expanded_root(browser, pilot)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()

        pack_a_node = browser.root.children[0].children[0]
        pack_a_node.expand()
        await pilot.pause()
        # PackA itself still shows (it has a match), but only the matching
        # file inside it - the untagged snare is filtered out.
        assert _labels(pack_a_node.children) == ["kick.wav"]


async def test_clearing_the_filter_does_not_collapse_an_already_expanded_root(tmp_path):
    """Regression test: toggling a filter on and off used to tear the
    whole tree down and rebuild it, which only ever auto-re-expanded a
    root when there was exactly one configured samples directory -
    otherwise a root the user had already expanded came back collapsed,
    looking like the browser "lost" samples that should still be there
    once the filter cleared."""
    first = tmp_path / "First"
    first.mkdir()
    (first / "kick.wav").write_bytes(b"")
    second = tmp_path / "Second"
    second.mkdir()
    (second / "snare.wav").write_bytes(b"")
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(first / "kick.wav", "kick", db_path)

    app = ShmampleApp(samples_directories=[first, second], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        first_root = await _expanded_root(browser, pilot)
        assert _labels(first_root.children) == ["kick.wav"]

        tags.focus()
        await pilot.pause()
        await pilot.press("space")  # select "kick" - filters, Second stays collapsed
        await _wait_for_tag_filter(app, pilot)

        await pilot.press("space")  # deselect again - back to no filter
        await _wait_for_tag_filter(app, pilot)

        assert first_root.is_expanded
        assert _labels(first_root.children) == ["kick.wav"]


async def test_toggling_a_filter_preserves_a_nested_folders_expanded_state(tmp_path):
    """Same regression, one level deeper: a subfolder the user had
    expanded before toggling the filter should still be expanded (showing
    its own, freshly re-filtered contents) afterwards, not collapsed back
    up to the root."""
    pack_a, _pack_b = _fixture(tmp_path)
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)

    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tags = app.query_one("#tags", TagBrowser)
        root_node = await _expanded_root(browser, pilot)
        pack_a_node = _node(root_node, "PackA")
        pack_a_node.expand()
        await pilot.pause()
        assert _labels(pack_a_node.children) == ["kick.wav", "snare.wav"]

        tags.focus()
        await pilot.pause()
        await pilot.press("space")  # select "kick"
        await _wait_for_tag_filter(app, pilot)
        # A filter re-scan replaces a refreshed node's children with fresh
        # TreeNode objects (see FileBrowser._load) - re-fetch rather than
        # reuse the pre-filter reference, which is now a detached node.
        pack_a_node = _node(root_node, "PackA")
        assert pack_a_node.is_expanded
        assert _labels(pack_a_node.children) == ["kick.wav"]

        await pilot.press("space")  # deselect again
        await _wait_for_tag_filter(app, pilot)

        pack_a_node = _node(root_node, "PackA")
        assert pack_a_node.is_expanded
        assert _labels(pack_a_node.children) == ["kick.wav", "snare.wav"]
