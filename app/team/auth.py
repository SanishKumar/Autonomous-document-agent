from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from uuid import uuid4

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from app.workspace.store import ConflictError, WorkspaceStore, now

COOKIE = "briefroom_session"
PASSWORDS = PasswordHash.recommended()
# Equal-cost verification for unknown accounts avoids an obvious account-existence timing signal.
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
LOCAL_USER = {"id": "local", "name": "Local user", "email": "", "role": "owner", "active": True}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def identity(request: Request) -> dict:
    return request.state.user


def require_role(request: Request, *roles: str) -> dict:
    user = identity(request)
    if user["role"] not in roles:
        raise HTTPException(403, "Your workspace role does not allow this action.")
    return user


class AuthStore:
    def __init__(self, store: WorkspaceStore, session_hours: int = 12):
        self.store = store
        self.session_seconds = session_hours * 3600
        self.setup_path = store.path.parent / ".setup-token"

    def initialize(self) -> None:
        with self.store.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS team_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    password_hash TEXT NOT NULL, role TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES members(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, email TEXT NOT NULL,
                    role TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES members(id),
                    expires REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_attempts (bucket TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS auth_attempts_bucket ON auth_attempts(bucket, at);
                CREATE TABLE IF NOT EXISTS team_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL
                );
            """)
            if not conn.execute("SELECT 1 FROM members LIMIT 1").fetchone():
                # Never print this secret or expose it through an API. The operator reads it locally.
                if not self.setup_path.exists():
                    with self.setup_path.open("x", encoding="utf-8") as token_file:
                        token_file.write(secrets.token_urlsafe(32))
                conn.execute(
                    "INSERT OR REPLACE INTO team_settings VALUES ('setup_hash', ?)",
                    (digest(self.setup_path.read_text(encoding="utf-8").strip()),),
                )

    @staticmethod
    def public(row) -> dict:
        return {k: row[k] for k in ("id", "email", "name", "role", "active", "created_at")}

    @staticmethod
    def audit(conn, actor: str, action: str, detail: dict) -> None:
        conn.execute(
            "INSERT INTO team_audit(at, actor, action, detail) VALUES (?, ?, ?, ?)",
            (now(), actor, action, json.dumps(detail)),
        )

    def setup_required(self) -> bool:
        with self.store.connection() as conn:
            return conn.execute("SELECT 1 FROM members LIMIT 1").fetchone() is None

    def workspace_name(self) -> str:
        with self.store.connection() as conn:
            row = conn.execute("SELECT value FROM team_settings WHERE key='name'").fetchone()
            return row[0] if row else "Your workspace"

    def setup(self, email: str, name: str, password_hash: str, token: str, workspace: str) -> dict:
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            setting = conn.execute(
                "SELECT value FROM team_settings WHERE key='setup_hash'"
            ).fetchone()
            if conn.execute("SELECT 1 FROM members LIMIT 1").fetchone():
                raise ConflictError("This workspace already has an owner. Sign in instead.")
            if not setting or not secrets.compare_digest(setting[0], digest(token)):
                raise ValueError("The setup key is not valid.")
            user_id = uuid4().hex
            conn.execute(
                "INSERT INTO members VALUES (?, ?, ?, ?, 'owner', 1, ?)",
                (user_id, email, name, password_hash, now()),
            )
            conn.execute("INSERT OR REPLACE INTO team_settings VALUES ('name', ?)", (workspace,))
            conn.execute("DELETE FROM team_settings WHERE key='setup_hash'")
            self.audit(conn, user_id, "workspace_created", {"name": workspace})
            row = conn.execute("SELECT * FROM members WHERE id=?", (user_id,)).fetchone()
        try:
            self.setup_path.unlink(missing_ok=True)
        except OSError:
            logging.getLogger(__name__).warning(
                "Owner created; remove the unused setup key file manually."
            )
        return self.public(row)

    def reserve_attempt(self, host: str, email: str) -> None:
        current = time.time()
        buckets = [(digest("ip:" + host), 60), (digest(host + ":" + email), 10)]
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM auth_attempts WHERE at<?", (current - 900,))
            for bucket, limit in buckets:
                count = conn.execute(
                    "SELECT COUNT(*) FROM auth_attempts WHERE bucket=?", (bucket,)
                ).fetchone()[0]
                if count >= limit:
                    raise HTTPException(
                        429,
                        "Too many authentication attempts. Try again in 15 minutes.",
                        headers={"Retry-After": "900"},
                    )
            conn.executemany(
                "INSERT INTO auth_attempts VALUES (?, ?)", [(b, current) for b, _ in buckets]
            )

    def account(self, email: str):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None

    def session(self, user_id: str) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            conn.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (digest(token), user_id, csrf, time.time() + self.session_seconds),
            )
        return token, csrf

    def resolve(self, token: str | None) -> dict | None:
        if not token or len(token) > 200:
            return None
        with self.store.connection() as conn:
            row = conn.execute(
                """SELECT m.*, s.csrf FROM sessions s JOIN members m ON m.id=s.user_id
                WHERE s.token_hash=? AND s.expires>? AND m.active=1""",
                (digest(token), time.time()),
            ).fetchone()
            return {"user": self.public(row), "csrf_token": row["csrf"]} if row else None

    def logout(self, token: str) -> None:
        with self.store.connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (digest(token),))

    def invite(self, email: str, role: str, actor: dict) -> tuple[dict, str]:
        token, invite_id = secrets.token_urlsafe(32), uuid4().hex
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM members WHERE email=?", (email,)).fetchone():
                raise ConflictError(
                    "This email already belongs to a member. Manage their access instead."
                )
            conn.execute(
                "UPDATE invitations SET status='revoked' WHERE email=? AND status='pending'",
                (email,),
            )
            conn.execute(
                "INSERT INTO invitations VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (invite_id, digest(token), email, role, actor["id"], time.time() + 604800, now()),
            )
            self.audit(
                conn,
                actor["id"],
                "invitation_created",
                {"id": invite_id, "email": email, "role": role},
            )
        return {"id": invite_id, "email": email, "role": role}, token

    def accept(self, token: str, email: str, name: str, password_hash: str) -> dict:
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            invite = conn.execute(
                "SELECT * FROM invitations WHERE token_hash=? AND email=? AND status='pending' AND expires>?",
                (digest(token), email, time.time()),
            ).fetchone()
            if not invite:
                raise ValueError(
                    "The invitation is invalid, expired, or does not match this email."
                )
            if conn.execute("SELECT 1 FROM members WHERE email=?", (email,)).fetchone():
                raise ConflictError("This account already exists. Sign in instead.")
            user_id = uuid4().hex
            conn.execute(
                "INSERT INTO members VALUES (?, ?, ?, ?, ?, 1, ?)",
                (user_id, email, name, password_hash, invite["role"], now()),
            )
            conn.execute("UPDATE invitations SET status='accepted' WHERE id=?", (invite["id"],))
            self.audit(conn, user_id, "invitation_accepted", {"id": invite["id"]})
            return self.public(
                conn.execute("SELECT * FROM members WHERE id=?", (user_id,)).fetchone()
            )

    def members(self) -> list[dict]:
        with self.store.connection() as conn:
            return [
                self.public(row)
                for row in conn.execute("SELECT * FROM members ORDER BY created_at")
            ]

    def invitations(self) -> list[dict]:
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT id, email, role, expires, status, created_at FROM invitations ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            return [
                {
                    **dict(row),
                    "status": "expired"
                    if row["status"] == "pending" and row["expires"] < time.time()
                    else row["status"],
                }
                for row in rows
            ]

    def revoke_invite(self, invite_id: str, actor: dict) -> None:
        with self.store.connection() as conn:
            changed = conn.execute(
                "UPDATE invitations SET status='revoked' WHERE id=? AND status='pending'",
                (invite_id,),
            ).rowcount
            if not changed:
                raise KeyError(invite_id)
            self.audit(conn, actor["id"], "invitation_revoked", {"id": invite_id})

    def update_member(self, user_id: str, role: str, active: bool, actor: dict) -> None:
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM members WHERE id=?", (user_id,)).fetchone()
            if not user:
                raise KeyError(user_id)
            if user["role"] == "owner" and user["active"] and (role != "owner" or not active):
                owners = conn.execute(
                    "SELECT COUNT(*) FROM members WHERE role='owner' AND active=1"
                ).fetchone()[0]
                if owners <= 1:
                    raise ConflictError("Keep at least one active owner in the workspace.")
            conn.execute(
                "UPDATE members SET role=?, active=? WHERE id=?", (role, int(active), user_id)
            )
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            if not active:
                conn.execute(
                    "UPDATE invitations SET status='revoked' WHERE created_by=? AND status='pending'",
                    (user_id,),
                )
            self.audit(
                conn,
                actor["id"],
                "member_access_changed",
                {"id": user_id, "role": role, "active": active},
            )

    def change_password(self, user_id: str, password_hash: str) -> None:
        with self.store.connection() as conn:
            conn.execute("UPDATE members SET password_hash=? WHERE id=?", (password_hash, user_id))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.audit(conn, user_id, "password_changed", {})
