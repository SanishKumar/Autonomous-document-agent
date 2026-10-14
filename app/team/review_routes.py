from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.team.auth import identity, require_role
from app.team.review import actor_info
from app.workspace.store import ConflictError

router = APIRouter(prefix="/api/documents", tags=["review"])


class Reply(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=4000)


class Comment(Reply):
    expected_version: int = Field(ge=1)
    section: int | None = Field(default=None, ge=0, le=14)


class Resolve(BaseModel):
    resolved: bool


class Decision(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    decision: Literal["approved", "changes_requested"]
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def explain_changes(self):
        if self.decision == "changes_requested" and not self.note:
            raise ValueError("Explain what needs to change.")
        return self


def repository(request: Request, doc_id: str):
    try:
        request.app.state.workspace.get(doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found.") from None
    return request.app.state.reviews


def handle(action):
    try:
        return action()
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Discussion not found.") from None


@router.get("/{doc_id}/review")
async def review(doc_id: str, request: Request):
    return repository(request, doc_id).get(doc_id)


@router.post("/{doc_id}/comments", status_code=201)
async def comment(doc_id: str, payload: Comment, request: Request):
    repo = repository(request, doc_id)
    thread_id = handle(
        lambda: repo.comment(
            doc_id,
            payload.expected_version,
            payload.section,
            payload.body,
            actor_info(identity(request)),
        )
    )
    return {"id": thread_id}


@router.post("/{doc_id}/comments/{thread_id}/replies", status_code=201)
async def reply(doc_id: str, thread_id: str, payload: Reply, request: Request):
    repo = repository(request, doc_id)
    handle(lambda: repo.reply(doc_id, thread_id, payload.body, actor_info(identity(request))))
    return {"ok": True}


@router.post("/{doc_id}/comments/{thread_id}/resolve")
async def resolve(doc_id: str, thread_id: str, payload: Resolve, request: Request):
    repo = repository(request, doc_id)
    handle(lambda: repo.resolve(doc_id, thread_id, payload.resolved, actor_info(identity(request))))
    return {"ok": True}


@router.post("/{doc_id}/review")
async def decide(doc_id: str, payload: Decision, request: Request):
    actor = require_role(request, "owner", "reviewer")
    repo = repository(request, doc_id)
    return handle(
        lambda: repo.decide(
            doc_id, payload.expected_version, payload.decision, payload.note, actor_info(actor)
        )
    )
