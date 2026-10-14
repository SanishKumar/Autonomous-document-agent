from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from app.document_builder import DocumentBuilder
from app.schemas import ConstraintResolution, DocumentDraft, ExecutionPlan
from app.team.auth import COOKIE, require_role
from app.team.review import actor_info
from app.workspace.comparison import compare
from app.workspace.models import Approval, NewJob, RestoreDraft, SaveDraft
from app.workspace.samples import TEMPLATES
from app.workspace.store import ConflictError

router = APIRouter(prefix="/api", tags=["workspace"])
TERMINAL = {"completed", "needs_review", "failed", "cancelled", "interrupted"}


def store(request: Request):
    return request.app.state.workspace


def document(request: Request, doc_id: str) -> dict:
    try:
        return store(request).get(doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found") from None


@router.get("/config")
async def config(request: Request):
    settings = request.app.state.settings
    return {
        "name": "Briefroom",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "local_workspace": True,
        "templates": TEMPLATES,
        "max_concurrent_jobs": settings.max_concurrent_jobs,
    }


@router.get("/documents")
async def documents(
    request: Request, q: str = Query(default="", max_length=200), status: str = "all"
):
    return {"documents": store(request).list(q, status)}


@router.post("/jobs", status_code=202)
async def create_job(payload: NewJob, request: Request):
    actor = require_role(request, "owner", "editor")
    submission = payload.model_dump()
    submission["idempotency_key"] = actor["id"] + ":" + payload.idempotency_key
    manager = request.app.state.jobs
    if len(manager.tasks) >= manager.settings.max_pending_jobs and not store(
        request
    ).has_submission(submission["idempotency_key"]):
        raise HTTPException(429, "The workspace queue is full. Wait for a run to finish.")
    try:
        doc, created = store(request).create(submission, actor=actor_info(actor))
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    if created:
        manager.submit(doc["id"], payload)
    return doc


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, request: Request):
    return document(request, doc_id)


@router.post("/documents/{doc_id}/cancel")
async def cancel(doc_id: str, request: Request):
    require_role(request, "owner", "editor")
    doc = document(request, doc_id)
    if doc["status"] not in {"queued", "running"}:
        raise HTTPException(409, "This run has already finished.")
    await request.app.state.jobs.cancel(doc_id)
    return document(request, doc_id)


@router.get("/documents/{doc_id}/events")
async def events(doc_id: str, request: Request, after: int = Query(default=0, ge=0)):
    document(request, doc_id)
    try:
        cursor = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        raise HTTPException(400, "Invalid event cursor") from None

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            if request.app.state.settings.auth_enabled and not request.app.state.auth.resolve(
                request.cookies.get(COOKIE)
            ):
                yield "event: auth_expired\ndata: {}\n\n"
                break
            batch = store(request).events(doc_id, cursor)
            for event in batch:
                cursor = event["id"]
                yield f"id: {cursor}\ndata: {json.dumps(event)}\n\n"
            if document(request, doc_id)["status"] in TERMINAL and len(batch) < 100:
                yield "event: done\ndata: {}\n\n"
                break
            yield ": keepalive\n\n"
            await asyncio.sleep(0.7)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/documents/{doc_id}/history")
async def history(
    doc_id: str, request: Request,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
):
    document(request, doc_id)
    batch = store(request).events(doc_id, after, limit + 1)
    page = batch[:limit]
    return {
        "versions": store(request).versions(doc_id),
        "events": page,
        "next_cursor": page[-1]["id"] if len(batch) > limit else None,
    }


@router.put("/documents/{doc_id}/draft")
async def save(doc_id: str, payload: SaveDraft, request: Request):
    actor = require_role(request, "owner", "editor")
    document(request, doc_id)
    try:
        return store(request).save(
            doc_id,
            payload.title,
            payload.draft.model_dump(),
            payload.expected_version,
            payload.note,
            actor=actor_info(actor),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/documents/{doc_id}/compare")
async def compare_versions(
    doc_id: str, request: Request,
    from_version: int = Query(ge=1), to_version: int = Query(ge=1),
):
    document(request, doc_id)
    try:
        return compare(store(request).revision(doc_id, from_version),
                       store(request).revision(doc_id, to_version))
    except KeyError:
        raise HTTPException(404, "Version not found") from None


@router.post("/documents/{doc_id}/versions/{number}/restore")
async def restore(doc_id: str, number: int, payload: RestoreDraft, request: Request):
    actor = require_role(request, "owner", "editor")
    document(request, doc_id)
    try:
        old = store(request).revision(doc_id, number)
        return store(request).save(
            doc_id,
            old["title"],
            old["draft"],
            payload.expected_version,
            f"Restored version {number}",
            actor=actor_info(actor),
        )
    except KeyError:
        raise HTTPException(404, "Version not found") from None
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/documents/{doc_id}/approval")
async def approve(doc_id: str, payload: Approval, request: Request):
    actor = require_role(request, "owner", "reviewer")
    document(request, doc_id)
    try:
        return request.app.state.reviews.decide(
            doc_id,
            payload.expected_version,
            "approved" if payload.approved else "approval_withdrawn",
            "",
            actor_info(actor),
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/documents/{doc_id}/export")
async def export(doc_id: str, request: Request):
    doc = document(request, doc_id)
    if not doc["artifact"]:
        raise HTTPException(409, "This document has no draft to export yet.")
    artifact = doc["artifact"]
    directory = Path(request.app.state.settings.outputs_dir) / "exports"
    builder = DocumentBuilder(directory)
    # A version-specific path prevents concurrent edits from replacing an active download.
    path = directory / f"{doc_id}-v{doc['version']}.docx"
    # Versions are immutable. Reuse an export rather than replace an open download on Windows.
    async with request.app.state.export_lock:
        if not path.is_file():
            path = await asyncio.to_thread(
                builder.build,
                request_id=f"{doc_id}-v{doc['version']}",
                plan=ExecutionPlan.model_validate(artifact["plan"]),
                draft=DocumentDraft.model_validate(artifact["draft"]),
                assumptions=artifact["assumptions"],
                resolution=ConstraintResolution.model_validate(artifact["resolution"])
                if artifact["resolution"]
                else None,
            )
    return FileResponse(
        path,
        filename=f"briefroom-{doc_id[:8]}-v{doc['version']}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
