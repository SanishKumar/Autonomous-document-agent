import asyncio
import io
import shutil
import time
from pathlib import Path
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.agent import AgentService
from app.config import Settings
from app.document_builder import DocumentBuilder
from app.main import create_app
from app.schemas import DocumentDraft, ExecutionPlan
from app.tools import AgentState, AgentTools
from app.workspace.store import WorkspaceStore
from tests.fake_llm import FakeLLM


@pytest.fixture
def directory():
    path = Path("outputs") / f".test-{uuid4().hex}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def workspace(path, service=None, **options):
    settings = Settings(outputs_dir=path, auth_enabled=False, **options)
    return create_app(settings=settings, service=service or AgentService(settings, llm=FakeLLM()))


def brief(**changes):
    return {
        "title": "Employee support rollout",
        "document_type": "project_plan",
        "audience": "Operations team",
        "request": "Create a 90-day plan for an internal employee helpdesk chatbot.",
        "idempotency_key": uuid4().hex,
        **changes,
    }


def test_history_cursor_reaches_all_events_without_duplicates(directory):
    app = workspace(directory)
    with TestClient(app) as client:
        doc_id = client.get("/api/documents").json()["documents"][0]["id"]
        store = app.state.workspace
        with store.connection() as conn:
            for number in range(205):
                store._event(conn, doc_id, "review_note", {"note": str(number)})
        expected = store.events(doc_id, limit=1000)
        collected = []
        cursor = 0
        while True:
            response = client.get(f"/api/documents/{doc_id}/history", params={"after": cursor})
            assert response.status_code == 200
            page = response.json()
            assert len(page["events"]) <= 100
            collected.extend(page["events"])
            if page["next_cursor"] is None:
                break
            assert page["next_cursor"] > cursor
            cursor = page["next_cursor"]
        assert collected == expected
        assert len({event["id"] for event in collected}) == len(collected)
        for params in ({"after": -1}, {"limit": 0}, {"limit": 101}):
            assert client.get(f"/api/documents/{doc_id}/history", params=params).status_code == 422
        assert client.get("/api/documents/missing/history").status_code == 404
        empty = client.get(f"/api/documents/{doc_id}/history", params={"after": collected[-1]["id"]}).json()
        assert empty["events"] == []
        assert empty["next_cursor"] is None


def wait_for(client, doc_id, statuses):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in statuses:
            return doc
        time.sleep(0.01)
    pytest.fail(f"Run did not reach {statuses}: {doc}")


def test_onboarding_and_settings_do_not_call_model(directory):
    class NeverCalled:
        async def run(self, *args, **kwargs):
            raise AssertionError("Opening the workspace must not call a model")

    with TestClient(workspace(directory, NeverCalled())) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Briefroom" in response.text
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert client.get("/static/app.js").status_code == 200
        config = client.get("/api/config").json()
        assert len(config["templates"]) == 5
        assert "api_key" not in str(config)
        docs = client.get("/api/documents").json()["documents"]
        assert len(docs) == 2
        assert all(d["sample"] for d in docs)
        assert all(d["score"] is None for d in docs)


def test_job_completes_and_events_resume_without_another_model_run(directory):
    with TestClient(workspace(directory)) as client:
        payload = brief()
        created = client.post("/api/jobs", json=payload)
        assert created.status_code == 202
        doc_id = created.json()["id"]
        doc = wait_for(client, doc_id, {"completed", "needs_review", "failed"})
        assert doc["status"] == "completed", doc["error"]
        assert doc["version"] == 1
        assert all(t["status"] == "completed" for t in doc["tasks"])
        assert client.post("/api/jobs", json=payload).json()["id"] == doc_id
        assert len(client.get("/api/documents").json()["documents"]) == 3
        stream = client.get(f"/api/documents/{doc_id}/events")
        assert stream.status_code == 200
        assert '"kind": "plan_ready"' in stream.text
        assert "event: done" in stream.text
        events = client.get(f"/api/documents/{doc_id}/history").json()["events"]
        last = events[-1]["id"]
        resumed = client.get(
            f"/api/documents/{doc_id}/events", headers={"Last-Event-ID": str(last)}
        )
        assert '"kind"' not in resumed.text
        assert "event: done" in resumed.text
        assert (
            client.get(
                f"/api/documents/{doc_id}/events", headers={"Last-Event-ID": "bad"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/jobs",
                json={**payload, "request": "Create an entirely different client report please."},
            ).status_code
            == 409
        )

    with TestClient(workspace(directory)) as client:
        persisted = client.get(f"/api/documents/{doc_id}").json()
        assert persisted["artifact"] == doc["artifact"]
        assert len(client.get("/api/documents").json()["documents"]) == 3


def test_version_lock_approval_restore_and_export(directory):
    with TestClient(workspace(directory)) as client:
        sample = client.get("/api/documents").json()["documents"][0]
        url = f"/api/documents/{sample['id']}"
        original = client.get(url).json()
        assert (
            client.post(url + "/approval", json={"expected_version": 1, "approved": True}).json()[
                "approved_version"
            ]
            == 1
        )
        draft = original["artifact"]["draft"]
        new_summary = "This is a revised executive summary written by the consultant for the next client review."
        draft["executive_summary"] = new_summary
        edit = {"title": "A revised client engagement", "draft": draft, "expected_version": 1}
        saved = client.put(url + "/draft", json=edit)
        assert saved.status_code == 200
        assert saved.json()["version"] == 2
        assert saved.json()["approved_version"] is None
        assert saved.json()["status"] == "needs_review"
        assert client.put(url + "/draft", json=edit).status_code == 409
        assert (
            client.post(
                url + "/approval", json={"expected_version": 1, "approved": True}
            ).status_code
            == 409
        )
        export = client.get(url + "/export")
        assert export.status_code == 200
        assert client.get(url + "/export").content == export.content
        word = Document(io.BytesIO(export.content))
        assert new_summary in "\n".join(p.text for p in word.paragraphs)
        assert "v2.docx" in export.headers["content-disposition"]
        restored = client.post(url + "/versions/1/restore", json={"expected_version": 2})
        assert restored.status_code == 200
        assert restored.json()["version"] == 3
        assert restored.json()["artifact"]["draft"]["executive_summary"] != new_summary
        assert len(client.get(url + "/history").json()["versions"]) == 3
        assert (
            client.post(url + "/versions/99/restore", json={"expected_version": 3}).status_code
            == 404
        )


class WaitingService:
    async def run(self, request, *, request_id, on_event):
        await on_event("planning_started", {})
        await asyncio.sleep(100)


def test_cancel_queue_capacity_and_replay(directory):
    with TestClient(workspace(directory, WaitingService(), max_pending_jobs=1)) as client:
        payload = brief()
        result = client.post("/api/jobs", json=payload)
        doc_id = result.json()["id"]
        assert client.post("/api/jobs", json=payload).json()["id"] == doc_id
        assert client.post("/api/jobs", json=brief()).status_code == 429
        url = f"/api/documents/{doc_id}"
        assert client.get(url + "/export").status_code == 409
        cancelled = client.post(url + "/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.post(url + "/cancel").status_code == 409
        assert "event: done" in client.get(url + "/events").text


def test_generation_errors_are_recorded_without_provider_body(directory):
    class FailingService:
        async def run(self, request, *, request_id, on_event):
            raise RuntimeError("SECRET-PROVIDER-PAYLOAD")

    with TestClient(workspace(directory, FailingService())) as client:
        doc_id = client.post("/api/jobs", json=brief()).json()["id"]
        doc = wait_for(client, doc_id, {"failed"})
        assert "quota" in doc["error"]
        assert "SECRET" not in str(doc)
        assert "SECRET" not in client.get(f"/api/documents/{doc_id}/events").text


def test_job_timeout_is_terminal(directory):
    with TestClient(workspace(directory, WaitingService(), job_timeout_seconds=0.02)) as client:
        doc_id = client.post("/api/jobs", json=brief()).json()["id"]
        doc = wait_for(client, doc_id, {"failed"})
        assert "time limit" in doc["error"]


def test_crash_recovery_does_not_silently_restart_paid_work(directory):
    repository = WorkspaceStore(directory / "workspace.sqlite3")
    repository.initialize()
    doc, _ = repository.create(brief())
    repository.record(doc["id"], "planning_started", {})
    with TestClient(workspace(directory)) as client:
        recovered = client.get(f"/api/documents/{doc['id']}").json()
        assert recovered["status"] == "interrupted"
        assert "restarted" in recovered["error"]


def test_cross_origin_writes_and_invalid_input_are_rejected(directory):
    with TestClient(workspace(directory)) as client:
        assert (
            client.post(
                "/api/jobs", json=brief(), headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/jobs", json=brief(request="1234 5678 90")).status_code == 422
        assert client.post("/api/jobs", json=brief(context="x" * 12001)).status_code == 422
        assert client.get("/api/documents/missing").status_code == 404


def test_review_never_inflates_low_score(directory):
    class LowScore(FakeLLM):
        async def complete_json(self, system_prompt, user_prompt):
            if "ROLE: QUALITY_REVIEWER" in system_prompt:
                return {
                    "score": 6,
                    "passed": False,
                    "strengths": [],
                    "missing_items": [],
                    "contradictions": [],
                    "revision_instructions": [],
                }
            return await super().complete_json(system_prompt, user_prompt)

    state = AgentState(
        request_id="test0001",
        original_request="Create an employee support rollout plan.",
        plan=ExecutionPlan.model_validate(FakeLLM._plan(False)),
        draft=DocumentDraft.model_validate(FakeLLM._draft(False, revised=False)),
    )
    tools = AgentTools(LowScore(), DocumentBuilder(directory))
    review = asyncio.run(tools._review(state))
    assert review.score == 6
    assert review.passed is False


def test_failed_revision_review_retains_the_last_reviewed_draft(directory):
    class BrokenSecondReview(FakeLLM):
        reviews = 0

        async def complete_json(self, system_prompt, user_prompt):
            if "ROLE: QUALITY_REVIEWER" in system_prompt:
                self.reviews += 1
                if self.reviews > 1:
                    raise RuntimeError("Provider unavailable")
                return {
                    "score": 6,
                    "passed": False,
                    "missing_items": ["Needs more detail"],
                    "revision_instructions": ["Expand the milestones"],
                }
            return await super().complete_json(system_prompt, user_prompt)

    original = DocumentDraft.model_validate(FakeLLM._draft(False, revised=False))
    state = AgentState(
        request_id="test0001",
        original_request="Create an employee support rollout plan.",
        plan=ExecutionPlan.model_validate(FakeLLM._plan(False)),
        draft=original,
    )
    tools = AgentTools(BrokenSecondReview(), DocumentBuilder(directory))
    task = next(t for t in state.plan.tasks if t.tool == "review_document")
    asyncio.run(tools.review_document(task, state))
    assert state.draft == original
    assert state.review.score == 6
    assert state.revised is False
    assert state.warnings
