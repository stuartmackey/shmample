import wave

from shmample import library_scan, sample_store, tag_store
from shmample.app import ShmampleApp
from shmample.widgets.duplicate_review import DuplicateReviewScreen
from shmample.widgets.vim_option_list import VimOptionList


def _write_wav(path, value=1000, n_samples=100, sample_rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(value.to_bytes(2, "little", signed=True) * n_samples)


def test_deleting_one_of_a_pair_removes_the_tag_from_the_survivor(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    a = root / "a.wav"
    b = root / "pack" / "b.wav"
    _write_wav(a, value=1000)
    _write_wav(b, value=1000)
    library_scan.scan_library(root, db_path)
    assert tag_store.tags_for_sample(b, db_path) == {library_scan.DUPLICATE_TAG}

    library_scan.delete_duplicate(a, db_path)

    assert not a.exists()
    assert sample_store.get_cached_preview(a, db_path) is None
    assert tag_store.tags_for_sample(b, db_path) == set()


def test_deleting_one_of_a_trio_leaves_the_other_two_tagged(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    a, b, c = root / "a.wav", root / "b.wav", root / "c.wav"
    for path in (a, b, c):
        _write_wav(path, value=2000)
    library_scan.scan_library(root, db_path)

    library_scan.delete_duplicate(a, db_path)

    assert not a.exists()
    assert tag_store.tags_for_sample(b, db_path) == {library_scan.DUPLICATE_TAG}
    assert tag_store.tags_for_sample(c, db_path) == {library_scan.DUPLICATE_TAG}


def test_deleting_a_file_with_no_remaining_duplicate_is_a_no_op_on_tags(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    lone = root / "lone.wav"
    _write_wav(lone, value=3000)
    library_scan.scan_library(root, db_path)

    library_scan.delete_duplicate(lone, db_path)  # should not raise

    assert not lone.exists()
    assert sample_store.get_cached_preview(lone, db_path) is None


async def test_screen_deletes_a_file_and_updates_tags_and_groups(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    a = root / "a.wav"
    b = root / "pack" / "b.wav"
    unique = root / "unique.wav"
    _write_wav(a, value=1000)
    _write_wav(b, value=1000)
    _write_wav(unique, value=9999)
    library_scan.scan_library(root, db_path)

    app = ShmampleApp(samples_directories=[root], db_path=db_path)
    async with app.run_test() as pilot:
        await pilot.press("U")
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, DuplicateReviewScreen)
        groups_list = screen.query_one("#groups", VimOptionList)
        assert groups_list.option_count == 1  # only the a/b pair is a duplicate group

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")  # confirm delete (first option)
        await pilot.pause()

        assert not a.exists()
        assert tag_store.tags_for_sample(b, db_path) == set()
        # The group collapsed to a single survivor - no groups left.
        assert screen.query_one("#groups", VimOptionList).option_count == 0

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DuplicateReviewScreen)
