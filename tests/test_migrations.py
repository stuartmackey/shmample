import sqlite3

from shmample import migrations


def _create_legacy_database(db_path):
    """A samples table as it existed before content_hash - user_version
    left at its sqlite default (0), same as any real database predating
    this feature."""
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE samples (
            path TEXT PRIMARY KEY,
            duration_seconds REAL,
            frame_rate INTEGER,
            sample_width_bytes INTEGER,
            channels INTEGER,
            envelope TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()


def test_fresh_database_gets_latest_schema_with_no_rescan_flagged(tmp_path):
    db_path = tmp_path / "shmample.db"

    migrations.run_migrations(db_path)

    connection = sqlite3.connect(db_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(samples)")}
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert "content_hash" in columns
    assert version == migrations.MIGRATIONS[-1].version
    assert migrations.is_rescan_pending(db_path) is False


def test_existing_database_is_migrated_and_flags_a_rescan(tmp_path):
    db_path = tmp_path / "shmample.db"
    _create_legacy_database(db_path)

    migrations.run_migrations(db_path)

    connection = sqlite3.connect(db_path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(samples)")}
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert "content_hash" in columns
    assert version == migrations.MIGRATIONS[-1].version
    assert migrations.is_rescan_pending(db_path) is True


def test_running_migrations_twice_is_a_no_op(tmp_path):
    db_path = tmp_path / "shmample.db"
    _create_legacy_database(db_path)

    migrations.run_migrations(db_path)
    migrations.clear_rescan_pending(db_path)
    migrations.run_migrations(db_path)

    assert migrations.is_rescan_pending(db_path) is False


def test_clear_rescan_pending_is_a_no_op_when_nothing_is_pending(tmp_path):
    db_path = tmp_path / "shmample.db"

    migrations.run_migrations(db_path)
    migrations.clear_rescan_pending(db_path)

    assert migrations.is_rescan_pending(db_path) is False
