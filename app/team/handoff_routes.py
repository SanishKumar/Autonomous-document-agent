from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.team.auth import require_role
from app.team.review import actor_info
from app.workspace.store import ConflictError

router = APIRouter(prefix="/api", tags=["review handoffs"])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    reviewer_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    note: str = Field(default="", max_length=2000)


def repository(request: Request):
    if not request.app.state.settings.auth_enabled:
        raise HTTPException(409, "Enable team accounts to assign reviews.")
    return request.app.state.handoffs


@router.get("/review-inbox")
async def inbox(request: Request):
    return {"requests": repository(request).list(user_id=request.state.user["id"])}


@router.get("/documents/{doc_id}/review-requests")
async def document_requests(doc_id: str, request: Request):
    repo = repository(request)
    try:
        request.app.state.workspace.get(doc_id)
    except KeyError:
        raise HTTPException(404, "Document not found.") from None
    return {"requests": repo.list(doc_id=doc_id)}


@router.post("/documents/{doc_id}/review-requests", status_code=201)
async def request_review(doc_id: str, payload: ReviewRequest, request: Request):
    actor = require_role(request, "owner", "editor")
    repo = repository(request)
    try:
        request_id = repo.request(
            doc_id, payload.expected_version, payload.reviewer_id, payload.note, actor_info(actor)
        )
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Document not found.") from None
    return {"id": request_id}


@router.post("/documents/{doc_id}/review-requests/{request_id}/withdraw")
async def withdraw(doc_id: str, request_id: str, request: Request):
    actor = require_role(request, "owner", "editor")
    try:
        repository(request).withdraw(doc_id, request_id, actor_info(actor))
    except KeyError:
        raise HTTPException(404, "Active review request not found.") from None
    return {"ok": True}
