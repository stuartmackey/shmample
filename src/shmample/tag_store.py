import contextlib
import sqlite3
from pathlib import Path

from shmample.sample_store import DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    # WAL + NORMAL synchronous trade a small, acceptable durability window
    # (at most the last uncommitted transaction, on the rare crash-at-
    # exactly-the-wrong-moment) for a large write-throughput win - matters
    # here because tagging a whole sample library can mean tens of
    # thousands of writes in one run (see auto_tag.tag_folder's batched
    # connection). WAL is a property of the database file itself, so this
    # only needs setting once per file, but it's cheap to repeat.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_tags (
            sample_path TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            origin TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (sample_path, tag_id)
        )
        """
    )
    return connection


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Opens a connection with the schema already ensured, for a caller
    that wants to share one connection/transaction across many writes -
    see auto_assign_tag_batch and auto_tag.tag_folder. Callers own the
    connection: commit and close it themselves."""
    return _connect(db_path)


def _auto_assign_tag(connection: sqlite3.Connection, sample_path: Path, tag_name: str) -> bool:
    """The actual rescan-safe assign logic (see auto_assign_tag's
    docstring) - shared by auto_assign_tag (its own connection, commits
    immediately) and auto_assign_tag_batch (caller's connection, caller
    decides when to commit)."""
    tag_row = connection.execute(
        "SELECT id, active FROM tags WHERE name = ?", (tag_name,)
    ).fetchone()

    if tag_row is None:
        tag_id = connection.execute(
            "INSERT INTO tags (name, active) VALUES (?, 1)", (tag_name,)
        ).lastrowid
    else:
        tag_id, tag_active = tag_row
        if not tag_active:
            return False

    existing = connection.execute(
        "SELECT 1 FROM sample_tags WHERE sample_path = ? AND tag_id = ?",
        (str(sample_path), tag_id),
    ).fetchone()
    if existing is not None:
        return False

    connection.execute(
        "INSERT INTO sample_tags (sample_path, tag_id, origin, active) VALUES (?, ?, 'auto', 1)",
        (str(sample_path), tag_id),
    )
    return True


def auto_assign_tag(sample_path: Path, tag_name: str, db_path: Path = DEFAULT_DB_PATH) -> bool:
    """Applies `tag_name` to `sample_path` as an auto-derived tag, unless
    doing so would revive something a user has since removed by hand - the
    rescan rule from 01-auto-tagging.md. Returns whether it actually
    changed anything, so a folder-wide rescan can report how much of it
    was new versus already settled.

    Neither a soft-deleted tag nor a soft-deleted (sample, tag) pairing is
    ever revived here - both are treated as an explicit opt-out, not a gap
    to silently refill. Only a manual (re)assignment revives either.

    Opens and commits its own connection - fine for tagging one file, but
    see auto_assign_tag_batch for tagging many at once without paying a
    full connect+commit per (sample, tag) pair.
    """
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            return _auto_assign_tag(connection, sample_path, tag_name)


def auto_assign_tag_batch(
    connection: sqlite3.Connection, sample_path: Path, tag_name: str
) -> bool:
    """Same rescan-safe logic as auto_assign_tag, but against a connection
    the caller already has open and will commit/close itself - see
    auto_tag.tag_folder, which shares one connection (and a handful of
    periodic commits) across every file in a folder instead of a fresh
    connection and an fsync per tag, the difference between tagging a
    69,000-file library taking seconds versus minutes."""
    return _auto_assign_tag(connection, sample_path, tag_name)


def remove_tag_from_sample(
    sample_path: Path, tag_name: str, db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Soft-deletes one (sample, tag) pairing - the tag stays in place for
    every other sample still carrying it. A no-op if the pairing (or the
    tag itself) doesn't exist."""
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            connection.execute(
                """
                UPDATE sample_tags SET active = 0
                WHERE sample_path = ? AND tag_id = (SELECT id FROM tags WHERE name = ?)
                """,
                (str(sample_path), tag_name),
            )


def delete_tag(tag_name: str, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Soft-deletes a tag and cascades to every sample_tags row referencing
    it - removes it from every sample at once, distinct from
    remove_tag_from_sample's single-sample unassign. A no-op if the tag
    doesn't exist."""
    with contextlib.closing(_connect(db_path)) as connection:
        with connection:
            connection.execute("UPDATE tags SET active = 0 WHERE name = ?", (tag_name,))
            connection.execute(
                """
                UPDATE sample_tags SET active = 0
                WHERE tag_id = (SELECT id FROM tags WHERE name = ?)
                """,
                (tag_name,),
            )


def tag_counts(db_path: Path = DEFAULT_DB_PATH) -> list[tuple[str, int]]:
    """Every active tag with the number of samples currently carrying it
    (soft-deleted tags and soft-deleted pairings both excluded), sorted by
    name - the listing the tag browser pane shows."""
    with contextlib.closing(_connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT tags.name, COUNT(sample_tags.sample_path)
            FROM tags
            LEFT JOIN sample_tags
                ON sample_tags.tag_id = tags.id AND sample_tags.active = 1
            WHERE tags.active = 1
            GROUP BY tags.id
            ORDER BY tags.name
            """
        ).fetchall()
    return [(name, count) for name, count in rows]


def tags_for_sample(sample_path: Path, db_path: Path = DEFAULT_DB_PATH) -> set[str]:
    """Active tag names currently assigned to `sample_path`."""
    with contextlib.closing(_connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT tags.name FROM sample_tags
            JOIN tags ON tags.id = sample_tags.tag_id
            WHERE sample_tags.sample_path = ? AND sample_tags.active = 1 AND tags.active = 1
            """,
            (str(sample_path),),
        ).fetchall()
    return {name for (name,) in rows}
