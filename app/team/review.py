from __future__ import annotations

import json
from uuid import uuid4

from app.workspace.store import ConflictError, WorkspaceStore, now


def actor_info(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"]}


class ReviewStore:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    def initialize(self):
        with self.store.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS review_threads (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    version INTEGER NOT NULL, section INTEGER, section_title TEXT NOT NULL,
                    body TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL,
                    resolved INTEGER NOT NULL DEFAULT 0, resolved_by TEXT
                );
                CREATE INDEX IF NOT EXISTS review_threads_document ON review_threads(document_id, version);
                CREATE TABLE IF NOT EXISTS review_replies (
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES review_threads(id),
                    body TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_decisions (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    version INTEGER NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL,
                    author TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def current(conn, doc_id: str, version: int) -> dict:
        row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise KeyError(doc_id)
        doc = json.loads(row[0])
        if (
            not doc["artifact"]
            or doc["version"] != version
            or doc["status"] in {"queued", "running"}
        ):
            raise ConflictError("This draft changed. Reload before reviewing the current version.")
        return doc

    def get(self, doc_id: str) -> dict:
        with self.store.connection() as conn:
            threads = conn.execute(
                "SELECT * FROM review_threads WHERE document_id=? ORDER BY created_at", (doc_id,)
            ).fetchall()
            replies = conn.execute(
                "SELECT r.* FROM review_replies r JOIN review_threads t ON r.thread_id=t.id WHERE t.document_id=? ORDER BY r.created_at",
                (doc_id,),
            ).fetchall()
            decisions = conn.execute(
                "SELECT * FROM review_decisions WHERE document_id=? ORDER BY created_at DESC LIMIT 100",
                (doc_id,),
            ).fetchall()

        def decoded(row):
            data = dict(row)
            data["author"] = json.loads(data["author"])
            if "resolved_by" in data:
                data["resolved_by"] = (
                    json.loads(data["resolved_by"]) if data["resolved_by"] else None
                )
            return data

        return {
            "threads": [
                {
                    **decoded(t),
                    "replies": [decoded(r) for r in replies if r["thread_id"] == t["id"]],
                }
                for t in threads
            ],
            "decisions": [decoded(d) for d in decisions],
        }

    def comment(
        self, doc_id: str, version: int, section: int | None, body: str, actor: dict
    ) -> str:
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            doc = self.current(conn, doc_id, version)
            sections = doc["artifact"]["draft"]["sections"]
            if section is not None and section >= len(sections):
                raise ValueError("That section does not exist in this version.")
            title = sections[section]["heading"] if section is not None else "Whole document"
            thread_id = uuid4().hex
            conn.execute(
                "INSERT INTO review_threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                (thread_id, doc_id, version, section, title, body, json.dumps(actor), now()),
            )
            # New unresolved feedback means an earlier approval needs attention.
            doc["approved_version"], doc["approved_by"], doc["status"] = None, None, "needs_review"
            self.store._write(conn, doc)
            self.store._event(
                conn,
                doc_id,
                "comment_added",
                {"version": version, "thread_id": thread_id, "actor": actor},
            )
            return thread_id

    def reply(self, doc_id: str, thread_id: str, body: str, actor: dict):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            thread = conn.execute(
                "SELECT * FROM review_threads WHERE id=? AND document_id=?", (thread_id, doc_id)
            ).fetchone()
            if not thread:
                raise KeyError(thread_id)
            if thread["resolved"]:
                raise ConflictError("Reopen this discussion before replying.")
            conn.execute(
                "INSERT INTO review_replies VALUES (?, ?, ?, ?, ?)",
                (uuid4().hex, thread_id, body, json.dumps(actor), now()),
            )
            self.store._event(
                conn, doc_id, "comment_replied", {"thread_id": thread_id, "actor": actor}
            )

    def resolve(self, doc_id: str, thread_id: str, resolved: bool, actor: dict):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            thread = conn.execute(
                "SELECT * FROM review_threads WHERE id=? AND document_id=?", (thread_id, doc_id)
            ).fetchone()
            if not thread:
                raise KeyError(thread_id)
            conn.execute(
                "UPDATE review_threads SET resolved=?, resolved_by=? WHERE id=?",
                (int(resolved), json.dumps(actor) if resolved else None, thread_id),
            )
            if not resolved:
                row = conn.execute("SELECT payload FROM documents WHERE id=?", (doc_id,)).fetchone()
                doc = json.loads(row[0])
                if doc["version"] == thread["version"]:
                    doc["approved_version"], doc["approved_by"], doc["status"] = (
                        None,
                        None,
                        "needs_review",
                    )
                    self.store._write(conn, doc)
            self.store._event(
                conn,
                doc_id,
                "comment_resolved" if resolved else "comment_reopened",
                {"thread_id": thread_id, "actor": actor},
            )

    def decide(self, doc_id: str, version: int, decision: str, note: str, actor: dict):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            doc = self.current(conn, doc_id, version)
            if decision == "approved":
                unresolved = conn.execute(
                    "SELECT COUNT(*) FROM review_threads WHERE document_id=? AND version=? AND resolved=0",
                    (doc_id, version),
                ).fetchone()[0]
                if unresolved:
                    raise ConflictError(
                        "Resolve open discussions on this version before approving it."
                    )
            conn.execute(
                "INSERT INTO review_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid4().hex, doc_id, version, decision, note, json.dumps(actor), now()),
            )
            approved = decision == "approved"
            doc["approved_version"] = version if approved else None
            doc["approved_by"] = actor if approved else None
            doc["status"] = "completed" if approved else "needs_review"
            self.store._write(conn, doc)
            self.store._event(
                conn,
                doc_id,
                "review_" + decision,
                {"version": version, "note": note, "actor": actor},
            )
            return doc
