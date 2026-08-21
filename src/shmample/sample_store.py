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
            envelope TEXT NOT NULL
        )
        """
    )
    return connection


def get_cached_preview(path: Path, db_path: Path = DEFAULT_DB_PATH) -> CachedPreview | None:
    """Whatever's cached for `path`, or None if it's never been scanned.

    Keyed on the plain absolute path, no mtime/size staleness check - the
    "simplest for now" cache key decided in 01-auto-tagging.md.
    """
    with contextlib.closing(_connect(db_path)) as connection:
        row = connection.execute(
            "SELECT duration_seconds, frame_rate, sample_width_bytes, channels, envelope "
            "FROM samples WHERE path = ?",
            (str(path),),
        ).fetchone()

    if row is None:
        return None

    duration_seconds, frame_rate, sample_width_bytes, channels, envelope = row
    wav_format = (
        WavFormat(frame_rate=frame_rate, sample_width_bytes=sample_width_bytes, channels=channels)
        if frame_rate is not None
        else None
    )
    return CachedPreview(
        duration_seconds=duration_seconds,
        wav_format=wav_format,
        envelope=json.loads(envelope),
    )


def store_preview(path: Path, preview: CachedPreview, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Persists `preview` for `path`, overwriting whatever was cached before -
    including a failed probe (empty envelope/None duration/format), so a
    file that can't be decoded isn't re-attempted on every highlight."""
    wav_format = preview.wav_format
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO samples
                    (path, duration_seconds, frame_rate, sample_width_bytes, channels, envelope)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    duration_seconds = excluded.duration_seconds,
                    frame_rate = excluded.frame_rate,
                    sample_width_bytes = excluded.sample_width_bytes,
                    channels = excluded.channels,
                    envelope = excluded.envelope
                """,
                (
                    str(path),
                    preview.duration_seconds,
                    wav_format.frame_rate if wav_format is not None else None,
                    wav_format.sample_width_bytes if wav_format is not None else None,
                    wav_format.channels if wav_format is not None else None,
                    json.dumps(preview.envelope),
                ),
            )


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
