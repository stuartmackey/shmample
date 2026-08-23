import contextlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from shmample.waveform import WavFormat

DEFAULT_DB_PATH = Path.home() / ".config" / "shmample" / "shmample.db"

# Resolution the waveform envelope is cached at - deliberately independent
# of any particular pane width (01-auto-tagging.md, "waveform storage"), so
# the same cached envelope serves any pane size via resample_envelope
# below, comfortably above typical terminal widths.
ENVELOPE_RESOLUTION = 400


@dataclass
class CachedPreview:
    duration_seconds: float | None
    wav_format: WavFormat | None
    envelope: list[float]
    # None means "not yet hashed" (e.g. a row from before this column
    # existed, or a preview taken before a rescan got to it) - distinct
    # from a failed-probe row, which still gets a hash attempt of its own.
    content_hash: str | None = None


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    # Same reasoning as tag_store's own _connect (same physical database
    # file) - WAL/NORMAL trade a small durability window for a large
    # write-throughput win, worth it once browsing starts populating this
    # cache for a large sample library.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS samples (
            path TEXT PRIMARY KEY,
            duration_seconds REAL,
            frame_rate INTEGER,
            sample_width_bytes INTEGER,
            channels INTEGER,
            envelope TEXT NOT NULL,
            content_hash TEXT
        )
        """
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS allowed_duplicates (content_hash TEXT PRIMARY KEY)"
    )
    return connection


def ensure_schema(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Ensures the samples table exists at the current baseline schema -
    for callers (migrations.py) that need the table present before doing
    anything else, without reaching into the private _connect."""
    with contextlib.closing(_connect(db_path)):
        pass


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Opens a connection with the schema already ensured, for a caller
    that wants to share one connection/transaction across many writes -
    see store_preview_batch/store_content_hash_batch. Callers own the
    connection: commit and close it themselves."""
    return _connect(db_path)


def _get_cached_preview(connection: sqlite3.Connection, path: Path) -> CachedPreview | None:
    row = connection.execute(
        "SELECT duration_seconds, frame_rate, sample_width_bytes, channels, envelope, "
        "content_hash FROM samples WHERE path = ?",
        (str(path),),
    ).fetchone()

    if row is None:
        return None

    duration_seconds, frame_rate, sample_width_bytes, channels, envelope, content_hash = row
    wav_format = (
        WavFormat(frame_rate=frame_rate, sample_width_bytes=sample_width_bytes, channels=channels)
        if frame_rate is not None
        else None
    )
    return CachedPreview(
        duration_seconds=duration_seconds,
        wav_format=wav_format,
        envelope=json.loads(envelope),
        content_hash=content_hash,
    )


def get_cached_preview(path: Path, db_path: Path = DEFAULT_DB_PATH) -> CachedPreview | None:
    """Whatever's cached for `path`, or None if it's never been scanned.

    Keyed on the plain absolute path, no mtime/size staleness check - the
    "simplest for now" cache key decided in 01-auto-tagging.md.
    """
    with contextlib.closing(_connect(db_path)) as connection:
        return _get_cached_preview(connection, path)


def get_cached_preview_batch(connection: sqlite3.Connection, path: Path) -> CachedPreview | None:
    """Same lookup as get_cached_preview, but against a connection the
    caller already has open - see library_scan.scan_library."""
    return _get_cached_preview(connection, path)


def _store_preview(connection: sqlite3.Connection, path: Path, preview: CachedPreview) -> None:
    wav_format = preview.wav_format
    connection.execute(
        """
        INSERT INTO samples
            (path, duration_seconds, frame_rate, sample_width_bytes, channels, envelope,
             content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            duration_seconds = excluded.duration_seconds,
            frame_rate = excluded.frame_rate,
            sample_width_bytes = excluded.sample_width_bytes,
            channels = excluded.channels,
            envelope = excluded.envelope,
            content_hash = excluded.content_hash
        """,
        (
            str(path),
            preview.duration_seconds,
            wav_format.frame_rate if wav_format is not None else None,
            wav_format.sample_width_bytes if wav_format is not None else None,
            wav_format.channels if wav_format is not None else None,
            json.dumps(preview.envelope),
            preview.content_hash,
        ),
    )


def store_preview(path: Path, preview: CachedPreview, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Persists `preview` for `path`, overwriting whatever was cached before -
    including a failed probe (empty envelope/None duration/format), so a
    file that can't be decoded isn't re-attempted on every highlight."""
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            _store_preview(connection, path, preview)


def store_preview_batch(connection: sqlite3.Connection, path: Path, preview: CachedPreview) -> None:
    """Same upsert as store_preview, but against a connection the caller
    already has open and will commit/close itself - see library_scan.
    scan_library, which shares one connection across an entire folder scan
    instead of a fresh connection (and fsync) per file."""
    _store_preview(connection, path, preview)


def store_content_hash_batch(
    connection: sqlite3.Connection, path: Path, content_hash: str | None
) -> None:
    """Backfills just the content_hash on a row a previous preview already
    populated with duration/format/envelope - avoids redundantly re-
    decoding the waveform envelope for a file that was cached before this
    column existed (see library_scan.scan_library)."""
    connection.execute(
        "UPDATE samples SET content_hash = ? WHERE path = ?", (content_hash, str(path))
    )


def duplicate_hash_groups(db_path: Path = DEFAULT_DB_PATH) -> dict[str, list[Path]]:
    """Every set of 2+ paths sharing a non-null content_hash, across the
    whole library - not scoped to any particular root, since a match
    against a file ingested from a different configured samples directory
    should still be caught. Excludes any hash marked allowed (see
    mark_duplicate_allowed) - this is the one place both the duplicate
    review screen and library_scan._tag_duplicates read groups from, so
    excluding here is what keeps a rescan from re-flagging something the
    user already decided to keep (e.g. a kit vs. its own individual hits)."""
    with contextlib.closing(_connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT content_hash, path FROM samples
            WHERE content_hash IS NOT NULL
                AND content_hash NOT IN (SELECT content_hash FROM allowed_duplicates)
            ORDER BY content_hash
            """
        ).fetchall()

    groups: dict[str, list[Path]] = {}
    for content_hash, path in rows:
        groups.setdefault(content_hash, []).append(Path(path))
    return {key: paths for key, paths in groups.items() if len(paths) > 1}


def mark_duplicate_allowed(content_hash: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Marks `content_hash` as an intentionally-kept duplicate - excluded
    from duplicate_hash_groups (and so from tagging/the review screen)
    from now on, until this row is removed (no UI for that yet)."""
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO allowed_duplicates (content_hash) VALUES (?)",
                (content_hash,),
            )


def paths_with_hash(content_hash: str, db_path: Path = DEFAULT_DB_PATH) -> list[Path]:
    """Every path currently sharing `content_hash` - used after a delete to
    decide whether whatever's left still counts as a duplicate group (see
    library_scan.delete_duplicate)."""
    with contextlib.closing(_connect(db_path)) as connection:
        rows = connection.execute(
            "SELECT path FROM samples WHERE content_hash = ?", (content_hash,)
        ).fetchall()
    return [Path(path) for (path,) in rows]


def delete_sample(path: Path, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Removes `path`'s row entirely - unlike everything else in this
    module, which only ever inserts/updates. Used when the file itself has
    been deleted from disk (see library_scan.delete_duplicate), not for
    the "file went missing" case (02-find-duplicates.md deliberately
    doesn't treat that as a feature - see scan_library's own orphan
    cleanup)."""
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            connection.execute("DELETE FROM samples WHERE path = ?", (str(path),))


def resample_envelope(envelope: list[float], width: int) -> list[float]:
    """Downsamples a cached envelope to `width` points for display - same
    bucket-max approach as waveform.load_waveform_peaks, just operating on
    an already-decoded envelope instead of raw audio samples."""
    total = len(envelope)
    if total == 0 or width <= 0:
        return []
    if width >= total:
        return list(envelope)

    bucket_size = max(1, total // width)
    resampled = []
    for start in range(0, total, bucket_size):
        chunk = envelope[start:start + bucket_size]
        if chunk:
            resampled.append(max(chunk))
    return resampled
