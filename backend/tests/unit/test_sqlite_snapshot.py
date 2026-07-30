"""시연용 SQLite Snapshot의 일관된 Backup·복원을 검증한다."""

import sqlite3
from pathlib import Path

from app.sqlite_snapshot import backup_database, restore_database


def _write_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES (?)", (value,))


def test_sqlite_snapshot_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    snapshot = tmp_path / "nas" / "snapshot.db"
    restored = tmp_path / "restored.db"
    _write_database(source, "demo-state")

    assert backup_database(source, snapshot) is True
    assert restore_database(snapshot, restored) is True
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("demo-state",)


def test_sqlite_snapshot_skips_missing_source(tmp_path: Path) -> None:
    assert backup_database(tmp_path / "missing.db", tmp_path / "snapshot.db") is False
    assert restore_database(tmp_path / "missing.db", tmp_path / "restored.db") is False
