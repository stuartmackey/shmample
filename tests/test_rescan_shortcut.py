import wave

import pytest

from shmample import library_scan, migrations
from shmample.app import ShmampleApp
from shmample.tag_store import tags_for_sample
from shmample.widgets.file_browser import FileBrowser


def _write_wav(path, value=1000, n_samples=100, sample_rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(value.to_bytes(2, "little", signed=True) * n_samples)


@pytest.fixture
def samples_dir(tmp_path):
    _write_wav(tmp_path / "kick.wav", value=1000)
    _write_wav(tmp_path / "pack" / "kick-copy.wav", value=1000)
    _write_wav(tmp_path / "snare.wav", value=2000)
    return tmp_path


async def _wait_for_rescan(app):
    workers = [w for w in app.workers if w.group == "rescan"]
    if workers:
        await app.workers.wait_for_complete(workers)


async def test_shift_r_rescans_the_cursor_folder_and_tags_duplicates(samples_dir):
    db_path = samples_dir / "shmample.db"
    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    notifications = []
    async with app.run_test() as pilot:
        app.notify = lambda message, **kwargs: notifications.append(message)
        browser = app.query_one("#files", FileBrowser)
        root_node = browser.root.children[0]
        browser.focus()
        browser.move_cursor(root_node)
        await pilot.pause()

        await pilot.press("R")
        await _wait_for_rescan(app)
        await pilot.pause()

        assert tags_for_sample(samples_dir / "kick.wav", db_path) == {
            library_scan.DUPLICATE_TAG
        }
        assert tags_for_sample(samples_dir / "pack" / "kick-copy.wav", db_path) == {
            library_scan.DUPLICATE_TAG
        }
        assert tags_for_sample(samples_dir / "snare.wav", db_path) == set()
        assert any("Rescanned 3 samples" in message for message in notifications)


async def test_startup_notifies_when_a_rescan_is_pending(samples_dir):
    db_path = samples_dir / "shmample.db"
    connection = migrations._connect(db_path)
    migrations.mark_rescan_pending(connection)
    connection.close()

    app = ShmampleApp(samples_directories=[samples_dir], db_path=db_path)
    notifications = []
    # Set before run_test() mounts the app - on_mount's notify fires as
    # soon as the app mounts, before the body of the `async with` block
    # below gets a chance to run.
    app.notify = lambda message, **kwargs: notifications.append(message)
    async with app.run_test() as pilot:
        await pilot.pause()

    assert any("rescan" in message.lower() for message in notifications)
