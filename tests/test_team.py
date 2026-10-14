import sqlite3
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.team.auth import COOKIE
from app.workspace.store import WorkspaceStore

PASSWORD = "offline-test-password-only"


def setup(owner, directory):
    result = owner.post(
        "/api/auth/setup",
        json={
            "email": "OWNER@example.test",
            "name": "Workspace Owner",
            "password": PASSWORD,
            "workspace_name": "Fieldwork Studio",
            "setup_token": (directory / ".setup-token").read_text(),
        },
    )
    assert result.status_code == 201, result.text
    owner.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result


def member(app, owner, role="reviewer", email="reviewer@example.test"):
    invitation = owner.post("/api/team/invitations", json={"email": email, "role": role})
    assert invitation.status_code == 201
    token = invitation.json()["join_path"].split("/")[-1]
    client = TestClient(app)
    joined = client.post(
        "/api/auth/join",
        json={"token": token, "email": email, "name": role.title(), "password": PASSWORD},
    )
    assert joined.status_code == 201, joined.text
    client.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    return client, joined.json()["user"]


def sample(client):
    return client.get("/api/documents").json()["documents"][0]["id"]


def test_private_setup_and_every_document_surface_requires_login(team_app):
    app, owner, directory = team_app
    assert owner.get("/api/auth/session").json()["setup_required"] is True
    for path in ["/api/config", "/api/documents", "/api/team", "/documents/12345678.docx"]:
        assert owner.get(path).status_code == 401
    assert (
        owner.post(
            "/agent", json={"request": "Create a client onboarding plan please."}
        ).status_code
        == 401
    )
    invalid = owner.post(
        "/api/auth/setup",
        json={
            "email": "test@example.test",
            "name": "Owner",
            "password": PASSWORD,
            "workspace_name": "Workspace",
            "setup_token": "wrong-key-" * 4,
        },
    )
    assert invalid.status_code == 403
    result = setup(owner, directory)
    assert not (directory / ".setup-token").exists()
    cookie = result.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert result.json()["user"]["email"] == "owner@example.test"
    assert owner.get("/api/documents").status_code == 200
    assert "password_hash" not in owner.get("/api/team").text
    assert (
        owner.post(
            "/api/auth/setup",
            json={
                "email": "new@example.test",
                "name": "Other Owner",
                "password": PASSWORD,
                "workspace_name": "Workspace",
                "setup_token": "wrong-key-" * 4,
            },
        ).status_code
        == 409
    )


def test_csrf_logout_and_validation_never_echo_passwords(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    csrf = owner.headers.pop("X-CSRF-Token")
    assert owner.post("/api/auth/logout").status_code == 403
    owner.headers["X-CSRF-Token"] = "wrong"
    assert owner.post("/api/auth/logout").status_code == 403
    owner.headers["X-CSRF-Token"] = csrf
    assert (
        owner.post("/api/auth/logout", headers={"Origin": "https://another.example"}).status_code
        == 403
    )
    old_cookie = owner.cookies.get(COOKIE)
    assert owner.post("/api/auth/logout").status_code == 200
    owner.cookies.set(COOKIE, old_cookie)
    assert owner.get("/api/documents").status_code == 401
    invalid = owner.post(
        "/api/auth/join",
        json={
            "email": "test@example.test",
            "name": "Test",
            "password": "sensitive",
            "token": "x" * 40,
        },
    )
    assert invalid.status_code == 422
    assert "sensitive" not in invalid.text
    assert (
        owner.post(
            "/api/auth/login", content="{}", headers={"Content-Type": "text/plain"}
        ).status_code
        == 415
    )


def test_roles_protect_actions_not_just_controls(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    reviewer, _ = member(app, owner)
    editor, _ = member(app, owner, "editor", "editor@example.test")
    doc_id = sample(owner)
    url = f"/api/documents/{doc_id}"
    doc = reviewer.get(url).json()
    edit = {"title": doc["title"], "draft": doc["artifact"]["draft"], "expected_version": 1}
    assert reviewer.get(url + "/export").status_code == 200
    assert reviewer.put(url + "/draft", json=edit).status_code == 403
    assert (
        reviewer.post(url + "/versions/1/restore", json={"expected_version": 1}).status_code == 403
    )
    assert reviewer.post(url + "/cancel").status_code == 403
    assert (
        reviewer.post(
            "/api/jobs",
            json={
                "request": "Create an internal project plan please.",
                "idempotency_key": uuid4().hex,
            },
        ).status_code
        == 403
    )
    assert (
        reviewer.post(
            "/agent", json={"request": "Create an internal project plan please."}
        ).status_code
        == 403
    )
    assert (
        editor.post("/api/team/invitations", json={"email": "no@example.test"}).status_code == 403
    )
    assert (
        editor.post(url + "/approval", json={"expected_version": 1, "approved": True}).status_code
        == 403
    )
    assert editor.put(url + "/draft", json=edit).status_code == 200
    history = editor.get(url + "/history").json()
    assert history["versions"][0]["author"]["name"] == "Editor"


def test_version_bound_discussion_and_review_decisions(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    reviewer, _ = member(app, owner)
    doc_id = sample(owner)
    url = f"/api/documents/{doc_id}"
    comment = reviewer.post(
        url + "/comments",
        json={"expected_version": 1, "section": 0, "body": "Please validate the baseline."},
    )
    assert comment.status_code == 201
    thread = comment.json()["id"]
    approval = {"expected_version": 1, "decision": "approved", "note": "Reviewed the proposal."}
    assert reviewer.post(url + "/review", json=approval).status_code == 409
    assert (
        owner.post(
            url + f"/comments/{thread}/replies", json={"body": "Added this to the kickoff agenda."}
        ).status_code
        == 201
    )
    assert (
        reviewer.post(url + f"/comments/{thread}/resolve", json={"resolved": True}).status_code
        == 200
    )
    approved = reviewer.post(url + "/review", json=approval).json()
    assert approved["approved_by"]["name"] == "Reviewer"
    assert approved["approved_version"] == 1
    changed = reviewer.post(url + f"/comments/{thread}/resolve", json={"resolved": False})
    assert changed.status_code == 200
    assert owner.get(url).json()["approved_version"] is None
    doc = owner.get(url).json()
    saved = owner.put(
        url + "/draft",
        json={"title": doc["title"], "draft": doc["artifact"]["draft"], "expected_version": 1},
    )
    assert saved.json()["version"] == 2
    assert saved.json()["approved_by"] is None
    assert (
        reviewer.post(
            url + "/comments", json={"expected_version": 1, "body": "Stale feedback"}
        ).status_code
        == 409
    )
    assert reviewer.post(url + "/review", json=approval).status_code == 409
    assert (
        reviewer.post(url + "/review", json={**approval, "expected_version": 2}).status_code == 200
    )
    review = owner.get(url + "/review").json()
    assert review["threads"][0]["version"] == 1
    assert review["threads"][0]["replies"][0]["author"]["name"] == "Workspace Owner"
    assert len(review["decisions"]) == 2
    assert (
        reviewer.post(
            url + "/review", json={"expected_version": 2, "decision": "changes_requested"}
        ).status_code
        == 422
    )
    changes = reviewer.post(
        url + "/review",
        json={
            "expected_version": 2,
            "decision": "changes_requested",
            "note": "Revisit the timeline.",
        },
    )
    assert changes.json()["status"] == "needs_review"


def test_invites_bound_to_email_expire_and_cannot_be_reused(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    invite = owner.post(
        "/api/team/invitations", json={"email": "join@example.test", "role": "reviewer"}
    ).json()
    token = invite["join_path"].split("/")[-1]
    data = {
        "token": token,
        "email": "wrong@example.test",
        "name": "New Member",
        "password": PASSWORD,
    }
    guest = TestClient(app)
    assert guest.post("/api/auth/join", json=data).status_code == 400
    data["email"] = "join@example.test"
    with app.state.workspace.connection() as conn:
        conn.execute("UPDATE invitations SET expires=? WHERE id=?", (time.time() - 1, invite["id"]))
    assert guest.post("/api/auth/join", json=data).status_code == 400
    fresh = owner.post(
        "/api/team/invitations", json={"email": data["email"], "role": "editor"}
    ).json()
    data["token"] = fresh["join_path"].split("/")[-1]
    assert guest.post("/api/auth/join", json=data).status_code == 201
    assert guest.post("/api/auth/join", json=data).status_code == 400
    assert "token_hash" not in owner.get("/api/team").text
    assert (
        owner.post(
            "/api/team/invitations", json={"email": "bad@example.test", "role": "owner"}
        ).status_code
        == 422
    )


def test_access_revocation_and_last_owner_protection(team_app):
    app, owner, directory = team_app
    result = setup(owner, directory)
    reviewer, user = member(app, owner)
    assert (
        owner.put(
            f"/api/team/members/{user['id']}", json={"role": "reviewer", "active": False}
        ).status_code
        == 200
    )
    assert reviewer.get("/api/documents").status_code == 401
    owner_id = result.json()["user"]["id"]
    assert (
        owner.put(
            f"/api/team/members/{owner_id}", json={"role": "editor", "active": True}
        ).status_code
        == 409
    )


def test_password_change_revokes_other_sessions_and_expiry_is_server_side(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    other = TestClient(app)
    assert (
        other.post(
            "/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}
        ).status_code
        == 200
    )
    changed = owner.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "new-offline-test-password"},
    )
    assert changed.status_code == 200
    assert other.get("/api/documents").status_code == 401
    assert owner.get("/api/documents").status_code == 200
    with app.state.workspace.connection() as conn:
        conn.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert owner.get("/api/documents").status_code == 401


def test_authentication_throttled_and_revoke_invite(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    invitation = owner.post("/api/team/invitations", json={"email": "revoked@example.test"}).json()
    assert owner.post(f"/api/team/invitations/{invitation['id']}/revoke").status_code == 200
    guest = TestClient(app)
    assert (
        guest.post(
            "/api/auth/join",
            json={
                "email": "revoked@example.test",
                "name": "Guest",
                "password": PASSWORD,
                "token": invitation["join_path"].split("/")[-1],
            },
        ).status_code
        == 400
    )
    for _ in range(10):
        response = guest.post(
            "/api/auth/login", json={"email": "unknown@example.test", "password": PASSWORD}
        )
        assert response.status_code == 401
    assert (
        guest.post(
            "/api/auth/login", json={"email": "unknown@example.test", "password": PASSWORD}
        ).status_code
        == 429
    )


def test_existing_version_database_is_backed_up_and_migrated(team_app):
    _, _, directory = team_app
    legacy = directory / "legacy.sqlite3"
    connection = sqlite3.connect(legacy)
    connection.execute(
        "CREATE TABLE versions(document_id TEXT, number INTEGER, at TEXT, note TEXT, title TEXT, draft TEXT, PRIMARY KEY(document_id,number))"
    )
    connection.execute("INSERT INTO versions VALUES ('old', 1, 'then', 'Saved', 'Old title', '{}')")
    connection.commit()
    connection.close()
    repository = WorkspaceStore(legacy)
    repository.initialize()
    assert repository.versions("old")[0]["author"] is None
    assert (directory / "workspace.before-team.sqlite3").is_file()
