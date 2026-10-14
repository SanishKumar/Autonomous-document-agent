from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(UTC).isoformat()


class ConflictError(ValueError):
    pass


class WorkspaceStore:
    """SQLite repository. Snapshots, revisions and events commit in one transaction."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, at TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_document ON events(document_id, seq);
                CREATE TABLE IF NOT EXISTS versions (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, at TEXT NOT NULL, note TEXT NOT NULL,
                    title TEXT NOT NULL, draft TEXT NOT NULL, author TEXT,
                    PRIMARY KEY (document_id, number)
                );
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(versions)")}
            if "author" not in columns:
                backup = self.path.with_name("workspace.before-team.sqlite3")
                if not backup.exists():
                    target = sqlite3.connect(backup)
                    try:
                        conn.backup(target)
                    finally:
                        target.close()
                conn.execute("ALTER TABLE versions ADD COLUMN author TEXT")

    @staticmethod
    def _write(conn: sqlite3.Connection, doc: dict) -> None:
        doc["updated_at"] = now()
        conn.execute(
            "UPDATE documents SET title=?, status=?, updated_at=?, payload=? WHERE id=?",
            (doc["title"], doc["status"], doc["updated_at"], json.dumps(doc), doc["id"]),
        )

    @staticmethod
    def _event(conn: sqlite3.Connection, doc_id: str, kind: str, data: dict) -> None:
        conn.execute(
            "INSERT INTO events(document_id, kind, at, data) VALUES (?, ?, ?, ?)",
            (doc_id, kind, now(), json.dumps(data)),
        )

    def create(
        self, payload: dict, *, sample: bool = False, actor: dict | None = None
    ) -> tuple[dict, bool]:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            key = payload.get("idempotency_key")
            fingerprint = hashlib.sha256(
                json.dumps(
                    {k: v for k, v in payload.items() if k != "idempotency_key"},
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            existing = (
                conn.execute(
                    "SELECT payload FROM documents WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if key
                else None
            )
            if existing:
                doc = json.loads(existing[0])
                if doc.get("submission_hash", fingerprint) != fingerprint:
                    raise ConflictError(
                        "This submission key was already used for a different brief."
                    )
                return doc, False
            timestamp = now()
            doc = {
                "id": uuid4().hex,
                "title": payload["title"],
                "status": "completed" if sample else "queued",
                "sample": sample,
                "created_at": timestamp,
                "updated_at": timestamp,
                "brief": payload.get("request", ""),
                "audience": payload.get("audience", ""),
                "document_type": payload.get("document_type", "proposal"),
                "context": payload.get("context", ""),
                "version": 0,
                "approved_version": None,
                "approved_by": None,
                "created_by": actor,
                "artifact": None,
                "result": None,
                "tasks": [],
                "plan": None,
                "error": None,
                "submission_hash": fingerprint,
            }
            conn.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc["id"],
                    doc["title"],
                    doc["status"],
                    timestamp,
                    timestamp,
                    key,
                    json.dumps(doc),
                ),
            )
            self._event(conn, doc["id"], "sample_created" if sample else "queued", {})
            return doc, True

    def has_submission(self, key: str) -> bool:
        with self.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM documents WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                is not None
            )

    def get(self, doc_id: str) -> dict:
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
            if row is None:
                raise KeyError(doc_id)
            return json.loads(row[0])

    def list(self, query: str = "", status: str = "all") -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute("SELECT payload FROM documents ORDER BY updated_at DESC").fetchall()
        docs = [json.loads(row[0]) for row in rows]
        return [
            {
                key: doc[key]
                for key in (
                    "id",
                    "title",
                    "status",
                    "created_at",
                    "updated_at",
                    "sample",
                    "document_type",
                    "version",
                    "approved_version",
                    "audience",
                )
            }
            | {"brief": doc["brief"][:240], "score": (doc.get("result") or {}).get("quality_score")}
            for doc in docs
            if (not query or query.casefold() in (doc["title"] + doc["brief"]).casefold())
            and (status == "all" or doc["status"] == status)
        ]

    def record(self, doc_id: str, kind: str, data: dict) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                raise KeyError(doc_id)
            doc = json.loads(row[0])
            if doc["status"] in {"cancelled", "interrupted"} and kind != "cancelled":
                return
            if kind == "planning_started":
                doc["status"] = "running"
            elif kind == "plan_ready":
                doc["plan"] = data["plan"]
                doc["title"] = data["plan"]["title"]
                doc["tasks"] = [task | {"status": "pending"} for task in data["plan"]["tasks"]]
            elif kind in {"task_started", "task_completed", "task_failed"}:
                entry = data.get("task") or data["entry"]
                task_id = entry.get("id") or entry["task_id"]
                for task in doc["tasks"]:
                    if task["id"] == task_id:
                        task.update(entry)
                        task["status"] = "running" if kind == "task_started" else entry["status"]
            elif kind == "artifact_ready":
                doc["artifact"] = data
                doc["plan"] = data["plan"]
                doc["title"] = data["plan"]["title"]
                doc["version"] = 1
                conn.execute(
                    "INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        1,
                        now(),
                        "Sample document" if doc["sample"] else "Initial generation",
                        doc["title"],
                        json.dumps(data["draft"]),
                        json.dumps(doc.get("created_by")),
                    ),
                )
            elif kind == "completed":
                doc["result"] = data
                doc["status"] = "completed" if data.get("review_passed") else "needs_review"
            elif kind in {"failed", "cancelled", "interrupted"}:
                doc["status"] = kind
                doc["error"] = data.get("message")
                for task in doc["tasks"]:
                    if task["status"] == "running":
                        task["status"] = kind
                    elif task["status"] == "pending":
                        task["status"] = "skipped"
            self._write(conn, doc)
            # Draft content lives in the snapshot. Events retain useful metadata only.
            event_data = {"version": 1} if kind == "artifact_ready" else data
            self._event(conn, doc_id, kind, event_data)

    def events(self, doc_id: str, after: int = 0, limit: int = 100) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE document_id=? AND seq>? ORDER BY seq LIMIT ?",
                (doc_id, after, limit),
            ).fetchall()
        return [
            {
                "id": row["seq"],
                "kind": row["kind"],
                "at": row["at"],
                "data": json.loads(row["data"]),
            }
            for row in rows
        ]

    def versions(self, doc_id: str) -> list[dict]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT number, at, note, title, author FROM versions WHERE document_id=? ORDER BY number DESC",
                (doc_id,),
            ).fetchall()
        return [
            {**dict(row), "author": json.loads(row["author"]) if row["author"] else None}
            for row in rows
        ]

    def revision(self, doc_id: str, number: int) -> dict:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM versions WHERE document_id=? AND number=?",
                (
                    doc_id,
                    number,
                ),
            ).fetchone()
        if row is None:
            raise KeyError(number)
        return {**dict(row), "draft": json.loads(row["draft"])}

    def save(
        self,
        doc_id: str,
        title: str,
        draft: dict,
        expected: int,
        note: str,
        actor: dict | None = None,
    ) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                raise KeyError(doc_id)
            doc = json.loads(row[0])
            if (
                doc["version"] != expected
                or not doc["artifact"]
                or doc["status"] in {"queued", "running"}
            ):
                raise ConflictError(
                    "This document changed. Reload before saving to preserve both versions."
                )
            doc["version"] += 1
            doc["title"] = title
            doc["artifact"]["plan"]["title"] = title
            doc["plan"]["title"] = title
            doc["artifact"]["draft"] = draft
            doc["approved_version"] = None
            doc["approved_by"] = None
            doc["status"] = "needs_review"
            self._write(conn, doc)
            conn.execute(
                "INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    doc_id,
                    doc["version"],
                    now(),
                    note,
                    title,
                    json.dumps(draft),
                    json.dumps(actor),
                ),
            )
            self._event(
                conn,
                doc_id,
                "version_saved",
                {"version": doc["version"], "note": note, "actor": actor},
            )
            return doc

    def approve(self, doc_id: str, expected: int, approved: bool) -> dict:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
            if not row:
                raise KeyError(doc_id)
            doc = json.loads(row[0])
            if doc["version"] != expected or not doc["artifact"]:
                raise ConflictError("Approval must target the current document version.")
            doc["approved_version"] = expected if approved else None
            doc["status"] = "completed" if approved else "needs_review"
            self._write(conn, doc)
            self._event(
                conn,
                doc_id,
                "approved" if approved else "approval_withdrawn",
                {"version": expected},
            )
            return doc

    def recover(self) -> None:
        for doc in self.list():
            if doc["status"] in {"queued", "running"}:
                self.record(
                    doc["id"],
                    "interrupted",
                    {
                        "message": "The server restarted during this run. Start a new run to try again.",
                    },
                )
