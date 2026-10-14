from tests.test_team import member, sample, setup


def request_review(client, doc_id, reviewer_id, version=1):
    return client.post(
        f"/api/documents/{doc_id}/review-requests",
        json={
            "expected_version": version,
            "reviewer_id": reviewer_id,
            "note": "Please check the milestones and success measures.",
        },
    )


def test_review_request_reaches_only_relevant_inboxes(team_app):
    app, owner, directory = team_app
    owner_info = setup(owner, directory).json()["user"]
    reviewer, user = member(app, owner)
    other, _ = member(app, owner, email="other@example.test")
    doc_id = sample(owner)
    requested = request_review(owner, doc_id, user["id"])
    assert requested.status_code == 201
    assigned = reviewer.get("/api/review-inbox").json()["requests"]
    assert len(assigned) == 1
    assert assigned[0]["status"] == "pending"
    assert assigned[0]["requested_by"]["id"] == owner_info["id"]
    assert assigned[0]["reviewer"]["id"] == user["id"]
    assert owner.get("/api/review-inbox").json()["requests"][0]["id"] == requested.json()["id"]
    assert other.get("/api/review-inbox").json()["requests"] == []
    # The inbox is personal, but the document remains shared with the whole team.
    assert len(other.get(f"/api/documents/{doc_id}/review-requests").json()["requests"]) == 1
    assert request_review(owner, doc_id, user["id"]).status_code == 409


def test_request_roles_targets_and_stale_versions_are_validated(team_app):
    app, owner, directory = team_app
    owner_info = setup(owner, directory).json()["user"]
    reviewer, user = member(app, owner)
    editor, edit_user = member(app, owner, "editor", "editor@example.test")
    doc_id = sample(owner)
    assert request_review(reviewer, doc_id, owner_info["id"]).status_code == 403
    assert request_review(owner, doc_id, owner_info["id"]).status_code == 422
    assert request_review(owner, doc_id, edit_user["id"]).status_code == 422
    assert request_review(owner, doc_id, "a" * 32).status_code == 422
    assert request_review(owner, doc_id, user["id"], 999).status_code == 409
    assert request_review(editor, doc_id, user["id"]).status_code == 201


def test_new_version_supersedes_request_and_needs_fresh_handoff(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    reviewer, user = member(app, owner)
    doc_id = sample(owner)
    base = f"/api/documents/{doc_id}"
    assert request_review(owner, doc_id, user["id"]).status_code == 201
    assert (
        reviewer.post(
            base + "/review",
            json={
                "expected_version": 1,
                "decision": "changes_requested",
                "note": "Clarify the budget.",
            },
        ).status_code
        == 200
    )
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "changes_requested"
    doc = owner.get(base).json()
    assert (
        owner.put(
            base + "/draft",
            json={
                "expected_version": 1,
                "title": doc["title"],
                "draft": doc["artifact"]["draft"],
            },
        ).status_code
        == 200
    )
    old = reviewer.get("/api/review-inbox").json()["requests"][0]
    assert old["status"] == "superseded"
    assert old["version"] == 1 and old["current_version"] == 2
    assert request_review(owner, doc_id, user["id"], 2).status_code == 201
    requests = reviewer.get("/api/review-inbox").json()["requests"]
    assert [r["status"] for r in requests] == ["pending", "superseded"]
    assert (
        reviewer.post(
            base + "/review",
            json={
                "expected_version": 2,
                "decision": "approved",
                "note": "Reviewed the new version.",
            },
        ).status_code
        == 200
    )
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "approved"


def test_reopened_feedback_returns_approved_handoff_to_pending(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    reviewer, user = member(app, owner)
    doc_id = sample(owner)
    base = f"/api/documents/{doc_id}"
    request_review(owner, doc_id, user["id"])
    reviewer.post(base + "/review", json={"expected_version": 1, "decision": "approved"})
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "approved"
    owner.post(base + "/comments", json={"expected_version": 1, "body": "A new risk needs review."})
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "pending"


def test_unavailable_reviewer_and_withdrawal_preserve_draft(team_app):
    app, owner, directory = team_app
    setup(owner, directory)
    reviewer, user = member(app, owner)
    doc_id = sample(owner)
    base = f"/api/documents/{doc_id}"
    request_id = request_review(owner, doc_id, user["id"]).json()["id"]
    withdrawal = f"{base}/review-requests/{request_id}/withdraw"
    assert reviewer.post(withdrawal).status_code == 403
    owner.put(f"/api/team/members/{user['id']}", json={"role": "editor", "active": True})
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "unavailable"
    before = owner.get(base).json()
    assert owner.post(withdrawal).status_code == 200
    assert owner.post(withdrawal).status_code == 404
    after = owner.get(base).json()
    assert after["artifact"] == before["artifact"]
    assert after["version"] == before["version"]
    assert owner.get("/api/review-inbox").json()["requests"][0]["status"] == "withdrawn"
    assert request_review(owner, doc_id, user["id"]).status_code == 422
