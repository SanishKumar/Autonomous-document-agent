"""Run from the project root: python -m scripts.workspace_backup --help."""

import argparse
import json
import sqlite3
from pathlib import Path

from app.workspace.backup import create_backup, restore_backup, verify_backup


def main():
    parser = argparse.ArgumentParser(description="Local Briefroom backup and safe recovery")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("create", help="Snapshot a stopped workspace into a new directory")
    backup.add_argument("--source", type=Path, default=Path("outputs"))
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument("--server-stopped", action="store_true", required=True,
                        help="Confirm Uvicorn is stopped, so Word files cannot change during copying")
    verify = sub.add_parser("verify", help="Check manifest hashes and SQLite integrity")
    verify.add_argument("source", type=Path)
    restore = sub.add_parser("restore", help="Restore into a NEW directory, never overwrite")
    restore.add_argument("source", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            manifest = create_backup(args.source, args.destination)
        elif args.command == "verify":
            manifest = verify_backup(args.source)
        else:
            manifest = restore_backup(args.source, args.destination)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        parser.exit(1, f"Backup operation failed: {exc}\n")
    print(json.dumps({"operation": args.command, "status": "complete",
                      "files": len(manifest["files"]), "created_at": manifest["created_at"]}))


if __name__ == "__main__":
    main()
