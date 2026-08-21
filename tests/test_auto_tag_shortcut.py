import asyncio
import threading

import pytest

from shmample import auto_tag
from shmample.app import ShmampleApp
from shmample.tag_store import tags_for_sample
from shmample.widgets.file_browser import FileBrowser
from shmample.widgets.preview_info import PreviewInfo
from shmample.widgets.tag_browser import TagBrowser


@pytest.fixture
def samples_dir(tmp_path):
    (tmp_path / "BD 808.wav").write_bytes(b"")
    drums = tmp_path / "Drums"
    drums.mkdir()
    (drums / "SD 808.wav").write_bytes(b"")
    return tmp_path


async def _wait_for_auto_tag(app):
    workers = [w for w in app.workers if w.group == "auto-tag"]
    if workers:
        await app.workers.wait_for_complete(workers)


async def _expanded_root(browser: FileBrowser, pilot):
    root_node = browser.root.children[0]
    root_node.expand()
    await pilot.pause()
    return root_node


def _node(root_node, name):
    return next(n for n in root_node.children if name in str(n.label))


async def test_t_tags_the_highlighted_file(samples_dir):
    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    notifications = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: notifications.append(message)
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "BD 808.wav"))
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()

        assert tags_for_sample(samples_dir / "BD 808.wav", db_path) == {"kick"}
        assert any("kick" in message for message in notifications)


async def test_t_on_a_file_with_no_naming_convention_match_notifies_and_tags_nothing(tmp_path):
    (tmp_path / "mystery.wav").write_bytes(b"")
    db_path = tmp_path / "shmample.db"
    app = ShmampleApp(samples_directories=[tmp_path], db_path=db_path)
    notifications = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: notifications.append(message)
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "mystery.wav"))
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()

        assert tags_for_sample(tmp_path / "mystery.wav", db_path) == set()
        assert any("No naming-convention tags" in message for message in notifications)


async def test_t_on_a_folder_recursively_tags_everything_beneath_it(samples_dir):
    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    notifications = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: notifications.append(message)
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        # The root node itself represents samples_dir - tagging it should
        # recurse into Drums too, without ever tagging a folder itself.
        browser.move_cursor(root_node)
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        await _wait_for_auto_tag(app)
        await pilot.pause()

        assert tags_for_sample(samples_dir / "BD 808.wav", db_path) == {"kick"}
        assert tags_for_sample(samples_dir / "Drums" / "SD 808.wav", db_path) == {"snare"}
        assert any("Auto-tagged 2 samples" in message for message in notifications)


async def test_t_shows_a_persistent_loading_indicator_while_a_folder_is_processing(
    samples_dir, monkeypatch
):
    # Same "deterministic, not timing-guessed" approach as ConfigList's own
    # persistent-loading-indicator test (test_config_list.py) - a real
    # threading.Event so this can check mid-flight state without a race.
    release = threading.Event()
    real_tag_folder = auto_tag.tag_folder

    def _blocking_tag_folder(path, db_path=None, on_file_tagged=None):
        release.wait(timeout=5)
        return real_tag_folder(path, db_path, on_file_tagged)

    monkeypatch.setattr(auto_tag, "tag_folder", _blocking_tag_folder)

    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(root_node)
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        assert browser.loading is True  # still running - release not set yet

        release.set()
        await _wait_for_auto_tag(app)
        await pilot.pause()
        assert browser.loading is False


async def test_t_on_a_folder_shows_progress_partway_through(samples_dir, monkeypatch):
    # Deterministic mid-run check, same Event-based approach as the
    # loading-indicator test above: pause right after the first file's
    # progress callback has already run, so the subtitle update is
    # guaranteed to have happened before we assert on it.
    release = threading.Event()
    reached_first_file = threading.Event()
    real_tag_folder = auto_tag.tag_folder

    def _tag_folder_pausing_after_first_file(path, db_path=None, on_file_tagged=None):
        def wrapped(file_path, tags, index, total):
            if on_file_tagged is not None:
                on_file_tagged(file_path, tags, index, total)
            if index == 1:
                reached_first_file.set()
                release.wait(timeout=5)

        return real_tag_folder(path, db_path, wrapped)

    monkeypatch.setattr(auto_tag, "tag_folder", _tag_folder_pausing_after_first_file)
    monkeypatch.setattr(FileBrowser, "TAGGING_PROGRESS_INTERVAL", 1)

    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(root_node)
        await pilot.pause()

        await pilot.press("t")
        await asyncio.to_thread(reached_first_file.wait, 5)
        await pilot.pause()

        assert browser.border_subtitle == "Auto-tagging... 1/2"

        release.set()
        await _wait_for_auto_tag(app)
        await pilot.pause()
        assert browser.border_subtitle == ""


async def test_tagging_refreshes_the_tag_pane(samples_dir):
    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        tag_browser = app.query_one("#tags", TagBrowser)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "BD 808.wav"))
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()

        labels = [str(label.render()) for label in tag_browser.query("Label")]
        assert labels == ["kick (1)"]


async def test_tagging_the_currently_previewed_file_updates_the_preview_pane(samples_dir):
    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    async with app.run_test() as pilot:
        browser = app.query_one("#files", FileBrowser)
        preview = app.query_one(PreviewInfo)
        root_node = await _expanded_root(browser, pilot)
        browser.focus()
        browser.move_cursor(_node(root_node, "BD 808.wav"))
        await pilot.pause(0.2)  # past PREVIEW_DEBOUNCE_SECONDS

        await pilot.press("t")
        await pilot.pause()

        date_text = str(preview.query_one("#preview-date").render())
        assert "kick" in date_text
