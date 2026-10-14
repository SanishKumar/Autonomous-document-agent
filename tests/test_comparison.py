from copy import deepcopy

from fastapi.testclient import TestClient

from app.workspace.comparison import compare
from tests.test_workspace import workspace


def revision():
    return {"number": 1, "title": "Proposal", "draft": {
        "executive_summary": "Original summary", "conclusion": "Next steps",
        "sections": [{"heading": "Budget", "paragraphs": ["First paragraph"],
                      "bullets": ["Review"], "numbered_items": ["Start"],
                      "table": {"headers": ["Item", "Cost"], "rows": [["Pilot", "100"]]}}]}}


def test_comparison_tracks_title_text_and_table_changes_without_mutating():
    old = revision()
    new = deepcopy(old)
    new["number"] = 2
    new["title"] = "New proposal"
    new["draft"]["sections"][0]["table"]["rows"][0][1] = "200"
    result = compare(old, new)
    assert result["added"] == result["removed"] == 2
    assert result["from_version"] == 1 and result["to_version"] == 2
    assert old == revision()
    assert compare(old, old)["added"] == 0
    assert compare(new, old)["removed"] == 2


def test_comparison_preserves_section_order_and_literal_markup():
    old = revision()
    new = deepcopy(old)
    new["draft"]["sections"].append({"heading": "<script>alert(1)</script>", "paragraphs": ["New section"]})
    result = compare(old, new)
    assert result["added"] == 2
    assert result["removed"] == 0


def test_comparison_api_validation_and_saved_version(tmp_path):
    app = workspace(tmp_path)
    with TestClient(app) as client:
        doc = client.get("/api/documents").json()["documents"][0]
        path = f"/api/documents/{doc['id']}/compare"
        response = client.get(path, params={"from_version": 1, "to_version": 1})
        assert response.status_code == 200
        assert response.json()["added"] == response.json()["removed"] == 0
        assert client.get(path, params={"from_version": 1, "to_version": 999}).status_code == 404
        assert client.get(path, params={"from_version": 0, "to_version": 1}).status_code == 422
        assert client.get("/api/documents/missing/compare?from_version=1&to_version=1").status_code == 404
