import contextlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

from shmample import migrations, sample_store, tag_store
from shmample.sample_store import DEFAULT_DB_PATH, CachedPreview
from shmample.waveform import (
    compute_content_hash,
    get_duration_seconds,
    get_format_info,
    load_waveform_peaks,
)

DUPLICATE_TAG = "Potential-Duplicate"

# Same reasoning as auto_tag.COMMIT_BATCH_SIZE - a fresh connection/fsync
# per file is the difference between ingesting a large library in seconds
# versus minutes; a crash mid-run only loses the current uncommitted batch,
# fine since re-running just picks up where it left off.
COMMIT_BATCH_SIZE = 200


def _ingest_file(connection: sqlite3.Connection, path: Path) -> None:
    """Ensures `path` has a full database row (duration/format/envelope/
    hash), doing the least work needed to get there - a file with no row
    at all gets the full probe, a file already previewed before this
    feature shipped (has everything but a hash) only gets the hash
    computed, and a file already fully ingested is left untouched so a
    repeat rescan is fast."""
    existing = sample_store.get_cached_preview_batch(connection, path)

    if existing is None:
        preview = CachedPreview(
            duration_seconds=get_duration_seconds(path),
            wav_format=get_format_info(path),
            envelope=load_waveform_peaks(path, target_width=sample_store.ENVELOPE_RESOLUTION),
            content_hash=compute_content_hash(path),
        )
        sample_store.store_preview_batch(connection, path, preview)
    elif existing.content_hash is None:
        sample_store.store_content_hash_batch(connection, path, compute_content_hash(path))


def _remove_orphaned_rows(connection: sqlite3.Connection, root: Path, seen: set[Path]) -> None:
    """Deletes samples-table rows under `root` for files no longer on
    disk - quiet cleanup so a deleted file's stale hash/filename doesn't
    keep tagging its old sibling as a duplicate of something that no
    longer exists anywhere (02-find-duplicates.md: not a user-facing
    "missing file" feature, just correctness plumbing for duplicate
    detection)."""
    rows = connection.execute("SELECT path FROM samples").fetchall()
    orphaned = [
        path
        for (path,) in rows
        if Path(path).is_relative_to(root) and Path(path) not in seen
    ]
    connection.executemany("DELETE FROM samples WHERE path = ?", [(path,) for path in orphaned])


def _tag_duplicates(db_path: Path) -> None:
    # Content-hash matches only - same filename with different content is
    # coincidence, not duplication (a real library with tens of thousands
    # of samples across many packs turns out to have huge numbers of
    # unrelated files sharing a generic name like "Kick.wav"; folding that
    # into the same signal as an actual content match made the tag mean
    # "maybe nothing" more often than "maybe something", see the find-
    # duplicates task doc).
    groups = sample_store.duplicate_hash_groups(db_path).values()

    with contextlib.closing(tag_store.connect(db_path)) as connection:
        for group in groups:
            for path in group:
                tag_store.auto_assign_tag_batch(connection, path, DUPLICATE_TAG)
        connection.commit()


def delete_duplicate(path: Path, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Permanently deletes `path` from disk and its database row, then
    untags whatever's left sharing its content_hash if fewer than 2 remain -
    a pair collapsing to one survivor is no longer a duplicate of anything.
    No trash/recovery - the file is gone the moment this returns.

    Deliberately doesn't catch the unlink itself - a failed delete
    (permissions, already gone) is a real error the caller (the duplicate
    review screen) should surface, not swallow.
    """
    preview = sample_store.get_cached_preview(path, db_path)
    content_hash = preview.content_hash if preview is not None else None

    path.unlink()
    sample_store.delete_sample(path, db_path)

    if content_hash is not None:
        remaining = sample_store.paths_with_hash(content_hash, db_path)
        if len(remaining) < 2:
            for survivor in remaining:
                tag_store.remove_tag_from_sample(survivor, DUPLICATE_TAG, db_path)


def allow_duplicate(content_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Marks `content_hash` as an intentionally-kept duplicate (e.g. a kit
    vs. its own individual hits - same content, deliberately present in
    both places) and untags every path currently sharing it. Reads the
    current member list from the database rather than trusting a caller's
    in-memory group, so it stays correct even if that's gone stale."""
    sample_store.mark_duplicate_allowed(content_hash, db_path)
    for path in sample_store.paths_with_hash(content_hash, db_path):
        tag_store.remove_tag_from_sample(path, DUPLICATE_TAG, db_path)


def scan_library(
    root: Path,
    db_path: Path = DEFAULT_DB_PATH,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """Recursively ingests every .wav under `root` not yet fully ingested,
    removes samples-table rows under `root` for files no longer on disk,
    then re-runs duplicate detection across the whole library (not just
    this root) and tags every path in a duplicate group Potential-
    Duplicate. Clears the pending_rescan flag on completion - rescanning
    even one subfolder counts as "the user completed a rescan", it doesn't
    need to cover the whole library. Returns the count of files walked
    under `root`, for a progress indicator/summary message.

    `on_progress(index, total)` fires once with `index=0` as soon as the
    file count is known (before any file is actually processed - hashing a
    whole library can take long enough that a caller showing "0/total"
    straight away, rather than staying silent until the first file
    finishes, is the difference between "still working" and "looks stuck"),
    then again after every file (1-based index, out of total).
    """
    wav_paths = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")
    total = len(wav_paths)

    if on_progress is not None:
        on_progress(0, total)

    with contextlib.closing(sample_store.connect(db_path)) as connection:
        for index, path in enumerate(wav_paths, start=1):
            _ingest_file(connection, path)
            if index % COMMIT_BATCH_SIZE == 0:
                connection.commit()
            if on_progress is not None:
                on_progress(index, total)
        _remove_orphaned_rows(connection, root, set(wav_paths))
        connection.commit()

    _tag_duplicates(db_path)
    migrations.clear_rescan_pending(db_path)
    return total
