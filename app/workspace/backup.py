"""Portable local snapshots with integrity checks and non-destructive restoration."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

FORMAT = 1


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_database(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"documents", "versions", "events"} <= tables:
            raise ValueError("This is not a Briefroom workspace database")


def create_backup(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Backup destination already exists; choose a new directory")
    if destination.is_relative_to(source):
        raise ValueError("Keep backups outside the workspace output directory")
    database = source / "workspace.sqlite3"
    if not database.is_file() or database.is_symlink():
        raise ValueError("Workspace database not found or is a symbolic link")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".briefroom-backup-", dir=destination.parent) as temp:
        staging = Path(temp)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(staging / "workspace.sqlite3")) as snapshot:
                original.backup(snapshot)
                tables = {r[0] for r in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                # A restored workspace must not revive old sessions or invite links.
                for table in ("sessions", "invitations"):
                    if table in tables:
                        snapshot.execute(f"DELETE FROM {table}")
                snapshot.commit()
                snapshot.execute("VACUUM")
                # Publish a standalone database, not WAL sidecars tied to a connection.
                snapshot.execute("PRAGMA journal_mode=DELETE")
        check_database(staging / "workspace.sqlite3")
        paths = [*source.glob("*.docx"), *(source / "exports").glob("*.docx")]
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("Symbolic links are not supported in backup files")
            target = staging / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        manifest = {
            "format": FORMAT,
            "created_at": datetime.now(UTC).isoformat(),
            "sessions_and_invitations": "excluded",
            "files": {p.relative_to(staging).as_posix(): digest(p)
                      for p in sorted(staging.rglob("*")) if p.is_file()},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Rename publishes only a complete snapshot; never merge with an old backup.
        staging.rename(destination)
    return manifest


def verify_backup(source: Path) -> dict:
    source = source.resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported backup manifest")
    if not isinstance(manifest.get("created_at"), str):
        raise ValueError("Backup manifest is missing its creation time")
    files = manifest["files"]
    if "workspace.sqlite3" not in files:
        raise ValueError("Backup does not include a workspace database")
    for name, checksum in files.items():
        if not isinstance(checksum, str) or len(checksum) != 64 or any(
            character not in "0123456789abcdef" for character in checksum
        ):
            raise ValueError("Invalid checksum in backup manifest")
        relative = Path(name)
        allowed = name == "workspace.sqlite3" or (
            relative.suffix == ".docx" and
            (len(relative.parts) == 1 or
             (len(relative.parts) == 2 and relative.parts[0] == "exports"))
        )
        path = source / relative
        if not allowed or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe file path in backup manifest")
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("Backup contains a symbolic link")
        if not path.is_file() or digest(path) != checksum:
            raise ValueError(f"Missing or damaged backup file: {name}")
    check_database(source / "workspace.sqlite3")
    return manifest


def restore_backup(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("Restore destination must not exist; the current workspace is never overwritten")
    manifest = verify_backup(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".briefroom-restore-", dir=destination.parent) as temp:
        staging = Path(temp)
        for name, checksum in manifest["files"].items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
            if digest(target) != checksum:
                raise ValueError("Backup changed during restoration")
        check_database(staging / "workspace.sqlite3")
        staging.rename(destination)
    return manifest
