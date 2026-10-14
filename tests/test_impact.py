from copy import deepcopy

from fastapi.testclient import TestClient

from app.team.impact import changed_sections
from tests.test_workspace import workspace


def test_section_matching_flags_moves_and_edits():
    before = {"sections": [{"heading": "Scope", "paragraphs": ["Original"]},
                           {"heading": "Budget", "paragraphs": ["100"]}]}
    after = deepcopy(before)
    after["sections"].reverse()
    after["sections"][1]["paragraphs"] = ["Updated"]
    assert [c["kind"] for c in changed_sections(before, after)] == ["moved", "changed"]
    assert changed_sections(before, before) == []


def test_review_delta_uses_earlier_approval_and_preserves_feedback(tmp_path):
    with TestClient(workspace(tmp_path)) as client:
        doc_id = client.get("/api/documents").json()["documents"][0]["id"]
        base = f"/api/documents/{doc_id}"
        doc = client.get(base).json()
        assert client.get(base + "/review-impact").json()["baseline_version"] is None
        assert client.post(base + "/approval", json={"expected_version": 1, "approved": True}).status_code == 200
        assert client.post(base + "/comments", json={"expected_version": 1, "section": None,
                                                     "body": "Recheck the budget."}).status_code == 201
        draft = deepcopy(doc["artifact"]["draft"])
        draft["sections"][0]["paragraphs"] = ["Updated scope requiring a fresh review."]
        assert client.put(base + "/draft", json={"expected_version": 1, "title": doc["title"],
                                                 "draft": draft, "note": "Updated scope"}).status_code == 200
        report = client.get(base + "/review-impact").json()
        assert report["baseline_version"] == 1 and report["current_version"] == 2
        assert report["changes"][0]["kind"] == "changed"
        assert report["text_changes"]["added"] > 0
        assert any("Updated scope requiring a fresh review." in change["after"]
                   for change in report["text_changes"]["changes"])
        assert report["open_feedback"][0]["body"] == "Recheck the budget."
        assert client.get(base).json()["approved_version"] is None
