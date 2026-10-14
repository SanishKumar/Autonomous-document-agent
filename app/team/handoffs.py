from __future__ import annotations

import json
from uuid import uuid4

from app.team.review import ReviewStore
from app.workspace.store import ConflictError, WorkspaceStore, now


class HandoffStore:
    """Review assignments refer to immutable versions, not a moving document target."""

    def __init__(self, store: WorkspaceStore):
        self.store = store

    def initialize(self):
        with self.store.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS review_requests (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                    version INTEGER NOT NULL, reviewer_id TEXT NOT NULL REFERENCES members(id),
                    requested_by TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
                    withdrawn INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS review_request_current
                    ON review_requests(document_id, version) WHERE withdrawn=0;
                CREATE INDEX IF NOT EXISTS review_request_reviewer ON review_requests(reviewer_id);
            """)

    def request(self, doc_id: str, version: int, reviewer_id: str, note: str, actor: dict):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            doc = ReviewStore.current(conn, doc_id, version)
            reviewer = conn.execute(
                "SELECT id, name, role, active FROM members WHERE id=?", (reviewer_id,)
            ).fetchone()
            if (
                not reviewer
                or not reviewer["active"]
                or reviewer["role"] not in {"owner", "reviewer"}
            ):
                raise ValueError("Choose an active owner or reviewer.")
            if reviewer_id == actor["id"]:
                raise ValueError("Choose a teammate for this review, not yourself.")
            previous = conn.execute(
                "SELECT * FROM review_requests WHERE document_id=? AND version=? AND withdrawn=0",
                (doc_id, version),
            ).fetchone()
            if previous:
                raise ConflictError(
                    "This version already has a review request. Withdraw it before requesting another review."
                )
            request_id = uuid4().hex
            conn.execute(
                "INSERT INTO review_requests VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (request_id, doc_id, version, reviewer_id, json.dumps(actor), note, now()),
            )
            doc["approved_version"], doc["approved_by"], doc["status"] = None, None, "needs_review"
            self.store._write(conn, doc)
            self.store._event(
                conn,
                doc_id,
                "review_requested",
                {
                    "request_id": request_id,
                    "version": version,
                    "actor": actor,
                    "reviewer": {"id": reviewer_id, "name": reviewer["name"]},
                    "note": note,
                },
            )
            return request_id

    def withdraw(self, doc_id: str, request_id: str, actor: dict):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                "UPDATE review_requests SET withdrawn=1 WHERE id=? AND document_id=? AND withdrawn=0",
                (request_id, doc_id),
            ).rowcount
            if not updated:
                raise KeyError(request_id)
            self.store._event(
                conn,
                doc_id,
                "review_request_withdrawn",
                {
                    "request_id": request_id,
                    "actor": actor,
                },
            )

    def list(self, *, user_id: str | None = None, doc_id: str | None = None) -> list[dict]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, d.payload, m.name AS reviewer_name, m.active AS reviewer_active,
                    m.role AS reviewer_role,
                    (SELECT decision FROM review_decisions decision
                     WHERE decision.document_id=r.document_id AND decision.version=r.version
                        AND decision.created_at>=r.created_at
                     ORDER BY decision.created_at DESC, decision.rowid DESC LIMIT 1) AS decision
                FROM review_requests r JOIN documents d ON d.id=r.document_id
                JOIN members m ON m.id=r.reviewer_id
                WHERE (? IS NULL OR r.document_id=?)
                  AND (? IS NULL OR r.reviewer_id=? OR json_extract(r.requested_by, '$.id')=?)
                ORDER BY r.created_at DESC
                LIMIT 200
            """,
                (doc_id, doc_id, user_id, user_id, user_id),
            ).fetchall()
        result = []
        for row in rows:
            doc = json.loads(row["payload"])
            status = "pending"
            if row["withdrawn"]:
                status = "withdrawn"
            elif doc["version"] != row["version"]:
                status = "superseded"
            elif doc["approved_version"] == row["version"]:
                status = "approved"
            elif row["decision"] == "changes_requested":
                status = "changes_requested"
            elif not row["reviewer_active"] or row["reviewer_role"] not in {"owner", "reviewer"}:
                status = "unavailable"
            result.append(
                {
                    "id": row["id"],
                    "document_id": row["document_id"],
                    "title": doc["title"],
                    "version": row["version"],
                    "current_version": doc["version"],
                    "reviewer": {"id": row["reviewer_id"], "name": row["reviewer_name"]},
                    "requested_by": json.loads(row["requested_by"]),
                    "note": row["note"],
                    "created_at": row["created_at"],
                    "status": status,
                    "approved_by": doc.get("approved_by") if status == "approved" else None,
                }
            )
        return result
