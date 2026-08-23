import wave

from shmample import library_scan, migrations, sample_store, tag_store


def _write_wav(path, value=1000, n_samples=100, sample_rate=8000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(value.to_bytes(2, "little", signed=True) * n_samples)


def test_scan_gives_every_file_a_content_hash(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "kick.wav")
    _write_wav(root / "pack" / "snare.wav", value=2000)

    library_scan.scan_library(root, db_path)

    kick = sample_store.get_cached_preview(root / "kick.wav", db_path)
    snare = sample_store.get_cached_preview(root / "pack" / "snare.wav", db_path)
    assert kick.content_hash is not None
    assert snare.content_hash is not None
    assert kick.content_hash != snare.content_hash


def test_scan_tags_content_duplicates(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "kick.wav", value=1000)
    _write_wav(root / "pack" / "kick-copy.wav", value=1000)
    _write_wav(root / "snare.wav", value=2000)

    library_scan.scan_library(root, db_path)

    assert tag_store.tags_for_sample(root / "kick.wav", db_path) == {library_scan.DUPLICATE_TAG}
    assert tag_store.tags_for_sample(root / "pack" / "kick-copy.wav", db_path) == {
        library_scan.DUPLICATE_TAG
    }
    assert tag_store.tags_for_sample(root / "snare.wav", db_path) == set()


def test_scan_does_not_tag_same_filename_with_different_content(tmp_path):
    """A shared filename with different content isn't a duplicate - a
    library spanning many packs has huge numbers of unrelated files
    sharing a generic name like "Kick.wav" by coincidence, so filename
    alone isn't a useful duplicate signal at scale."""
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "a" / "kick.wav", value=1000)
    _write_wav(root / "b" / "kick.wav", value=9999)

    library_scan.scan_library(root, db_path)

    assert tag_store.tags_for_sample(root / "a" / "kick.wav", db_path) == set()
    assert tag_store.tags_for_sample(root / "b" / "kick.wav", db_path) == set()


def test_scan_backfills_hash_for_a_previously_previewed_file_without_redoing_the_envelope(
    tmp_path,
):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    path = root / "kick.wav"
    _write_wav(path)

    preview = sample_store.CachedPreview(
        duration_seconds=1.23,
        wav_format=None,
        envelope=[0.1, 0.2, 0.3],
        content_hash=None,
    )
    sample_store.store_preview(path, preview, db_path)

    library_scan.scan_library(root, db_path)

    updated = sample_store.get_cached_preview(path, db_path)
    assert updated.content_hash is not None
    assert updated.envelope == [0.1, 0.2, 0.3]
    assert updated.duration_seconds == 1.23


def test_scan_removes_rows_for_files_deleted_from_disk(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    kept = root / "kick.wav"
    removed = root / "snare.wav"
    _write_wav(kept)
    _write_wav(removed)

    library_scan.scan_library(root, db_path)
    assert sample_store.get_cached_preview(removed, db_path) is not None

    removed.unlink()
    library_scan.scan_library(root, db_path)

    assert sample_store.get_cached_preview(removed, db_path) is None
    assert sample_store.get_cached_preview(kept, db_path) is not None


def test_scan_clears_pending_rescan(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "kick.wav")

    connection = migrations._connect(db_path)
    migrations.mark_rescan_pending(connection)
    connection.close()
    assert migrations.is_rescan_pending(db_path) is True

    library_scan.scan_library(root, db_path)

    assert migrations.is_rescan_pending(db_path) is False


def test_scan_returns_the_count_of_files_walked(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "a.wav")
    _write_wav(root / "b.wav")
    _write_wav(root / "c.wav")

    count = library_scan.scan_library(root, db_path)

    assert count == 3


def test_scan_reports_progress_starting_at_zero_before_any_file_is_processed(tmp_path):
    """The very first callback fires with index=0 as soon as the total is
    known, before any file has actually been hashed - so a caller can show
    "0/N" immediately instead of looking stuck while the first (possibly
    slow) file is still being decoded."""
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    _write_wav(root / "a.wav")
    _write_wav(root / "b.wav")

    calls = []
    library_scan.scan_library(root, db_path, on_progress=lambda index, total: calls.append((index, total)))

    assert calls[0] == (0, 2)
    assert calls[-1] == (2, 2)
    assert len(calls) == 3  # the initial 0/2, then one per file


def test_allow_duplicate_untags_current_members(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    a, b = root / "a.wav", root / "pack" / "b.wav"
    _write_wav(a, value=1000)
    _write_wav(b, value=1000)
    library_scan.scan_library(root, db_path)
    content_hash = sample_store.get_cached_preview(a, db_path).content_hash

    library_scan.allow_duplicate(content_hash, db_path)

    assert tag_store.tags_for_sample(a, db_path) == set()
    assert tag_store.tags_for_sample(b, db_path) == set()


def test_allow_duplicate_excludes_the_group_from_future_rescans(tmp_path):
    db_path = tmp_path / "shmample.db"
    root = tmp_path / "library"
    a, b = root / "a.wav", root / "pack" / "b.wav"
    _write_wav(a, value=1000)
    _write_wav(b, value=1000)
    library_scan.scan_library(root, db_path)
    content_hash = sample_store.get_cached_preview(a, db_path).content_hash
    library_scan.allow_duplicate(content_hash, db_path)

    library_scan.scan_library(root, db_path)  # rescan shouldn't re-tag it

    assert tag_store.tags_for_sample(a, db_path) == set()
    assert tag_store.tags_for_sample(b, db_path) == set()
    assert content_hash not in sample_store.duplicate_hash_groups(db_path)
