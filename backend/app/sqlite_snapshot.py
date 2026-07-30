"""시연용 SQLite를 NAS Snapshot으로 안전하게 Backup·복원한다."""

import argparse
import os
import shutil
import sqlite3
from pathlib import Path


def _check_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
    if result != ("ok",):
        raise RuntimeError(f"SQLite integrity check failed for {path}.")


def backup_database(source: Path, destination: Path) -> bool:
    """실행 중인 SQLite의 일관된 Snapshot을 원자적으로 교체한다."""
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(temporary) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        _check_database(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def restore_database(source: Path, destination: Path) -> bool:
    """유효한 NAS Snapshot이 있으면 빈 Pod의 SQLite 경로에 복원한다."""
    if not source.is_file():
        return False
    _check_database(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source, temporary)
        _check_database(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    operation = backup_database if arguments.operation == "backup" else restore_database
    changed = operation(arguments.source, arguments.destination)
    print(f"sqlite_{arguments.operation}={'completed' if changed else 'skipped'}")


if __name__ == "__main__":
    main()
