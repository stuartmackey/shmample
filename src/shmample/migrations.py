import contextlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from shmample import sample_store, tag_store

_PENDING_RESCAN_KEY = "pending_rescan"


@dataclass
class Migration:
    version: int
    description: str
    requires_rescan: bool
    sql: str


# Ordered oldest-first. A fresh database never runs any of these (see
# run_migrations) - sample_store/tag_store's own CREATE TABLE statements
# already reflect the current baseline schema, so this list only exists to
# carry an *existing* database forward.
MIGRATIONS: list[Migration] = [
    Migration(
        version=1,
        description="Add content_hash to samples for duplicate detection",
        sql="ALTER TABLE samples ADD COLUMN content_hash TEXT",
        requires_rescan=True,
    ),
]


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    return connection


def run_migrations(db_path: Path | None = None) -> None:
    """Brings the database schema up to date, then runs once at app startup
    (see __main__.main) before the UI renders - the ALTER TABLE this
    currently applies is near-instant, unlike the rescan it may flag as
    needed (see mark_rescan_pending below).

    A brand-new database (no file on disk yet) is created straight at the
    latest schema via sample_store/tag_store's own CREATE TABLE statements,
    with no migrations applied and no rescan flagged - there's nothing to
    carry forward and nothing to rescan for a library that hasn't been
    scanned yet. Only a database that already existed before this version
    goes through the numbered migration list, since that's the only case
    where a column can genuinely be missing.

    Deliberately doesn't catch exceptions - a failed migration should stop
    startup rather than leave a half-migrated schema running silently.
    """
    resolved_db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH
    is_new_database = not resolved_db_path.exists()

    sample_store.ensure_schema(resolved_db_path)
    tag_store.ensure_schema(resolved_db_path)

    with contextlib.closing(_connect(resolved_db_path)) as connection:
        latest_version = MIGRATIONS[-1].version if MIGRATIONS else 0

        if is_new_database:
            connection.execute(f"PRAGMA user_version = {latest_version}")
            connection.commit()
            return

        current_version = connection.execute("PRAGMA user_version").fetchone()[0]
        pending = [m for m in MIGRATIONS if m.version > current_version]
        if not pending:
            return

        needs_rescan = False
        for migration in pending:
            connection.executescript(migration.sql)
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
            needs_rescan = needs_rescan or migration.requires_rescan

        if needs_rescan:
            mark_rescan_pending(connection)


def mark_rescan_pending(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value = '1'",
        (_PENDING_RESCAN_KEY,),
    )
    connection.commit()


def is_rescan_pending(db_path: Path | None = None) -> bool:
    resolved_db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH
    with contextlib.closing(_connect(resolved_db_path)) as connection:
        row = connection.execute(
            "SELECT value FROM app_meta WHERE key = ?", (_PENDING_RESCAN_KEY,)
        ).fetchone()
    return row is not None and row[0] == "1"


def clear_rescan_pending(db_path: Path | None = None) -> None:
    resolved_db_path = db_path if db_path is not None else sample_store.DEFAULT_DB_PATH
    with contextlib.closing(_connect(resolved_db_path)) as connection:
        connection.execute("DELETE FROM app_meta WHERE key = ?", (_PENDING_RESCAN_KEY,))
        connection.commit()
