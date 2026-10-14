from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Security
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles

from app.agent import AgentRunError, AgentService
from app.config import Settings
from app.schemas import AgentRequest, AgentResponse, ErrorResponse
from app.team.auth import COOKIE, LOCAL_USER, AuthStore, require_role
from app.team.handoff_routes import router as handoff_router
from app.team.handoffs import HandoffStore
from app.team.review import ReviewStore
from app.team.review_routes import router as review_router
from app.team.routes import router as team_router
from app.workspace.jobs import JobManager
from app.workspace.routes import router as workspace_router
from app.workspace.samples import seed_samples
from app.workspace.store import WorkspaceStore


def create_app(
    *,
    service: AgentService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_service = service or AgentService(active_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = WorkspaceStore(Path(active_settings.outputs_dir) / "workspace.sqlite3")
        repository.initialize()
        app.state.reviews = ReviewStore(repository)
        app.state.reviews.initialize()
        repository.recover()
        seed_samples(repository)
        app.state.workspace = repository
        app.state.auth = AuthStore(repository, active_settings.session_hours)
        app.state.password_slots = asyncio.Semaphore(2)
        if active_settings.auth_enabled:
            app.state.auth.initialize()
        app.state.handoffs = HandoffStore(repository)
        app.state.handoffs.initialize()
        app.state.export_lock = asyncio.Lock()
        app.state.jobs = JobManager(
            repository, active_settings, lambda: service or AgentService(active_settings)
        )
        yield
        await app.state.jobs.close()

    application = FastAPI(
        title="Briefroom",
        version="2.2.0",
        lifespan=lifespan,
        # The middleware enforces this token on authenticated writes. This declaration
        # also lets API users supply it through Swagger's Authorize button.
        dependencies=[Security(APIKeyHeader(name="X-CSRF-Token", auto_error=False))],
        description=(
            "Plans, executes, reviews, and generates structured Microsoft Word documents "
            "from natural-language business requests."
        ),
    )
    application.state.agent_service = active_service
    application.state.settings = active_settings

    @application.middleware("http")
    async def workspace_security(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin:
            if urlparse(origin).netloc != request.url.netloc:
                return JSONResponse(
                    status_code=403, content={"detail": "Cross-origin writes are disabled."}
                )
        path = request.url.path
        public_auth = {"/api/auth/session", "/api/auth/login", "/api/auth/setup", "/api/auth/join"}
        protected = path.startswith(("/api/", "/documents/")) or path == "/agent"
        request.state.user = LOCAL_USER
        if active_settings.auth_enabled and protected and path not in public_auth:
            current = request.app.state.auth.resolve(request.cookies.get(COOKIE))
            if not current:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Sign in to your workspace."},
                    headers={"Cache-Control": "no-store"},
                )
            request.state.user = current["user"]
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                supplied = request.headers.get("X-CSRF-Token", "")
                if not secrets.compare_digest(supplied, current["csrf_token"]):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Session verification failed. Reload the page and try again."
                        },
                    )
        if path in public_auth and request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse(status_code=415, content={"detail": "Use application/json."})
        response = await call_next(request)
        if protected:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
                "; form-action 'self'; base-uri 'none'; object-src 'none'"
            )
        return response

    application.include_router(workspace_router)
    application.include_router(team_router)
    application.include_router(review_router)
    application.include_router(handoff_router)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's default error payload includes raw inputs (including passwords).
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()
                ]
            },
        )

    static_dir = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    async def workspace_home():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    @application.exception_handler(AgentRunError)
    async def agent_error_handler(request: Request, exc: AgentRunError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "request_id": exc.request_id,
                "status": "failed",
                "error": {"stage": exc.stage, "message": str(exc)},
            },
        )

    @application.get("/health", tags=["operations"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "llm_provider": active_settings.llm_provider,
            "llm_model": active_settings.llm_model,
        }

    @application.post(
        "/agent",
        response_model=AgentResponse,
        responses={502: {"model": ErrorResponse}},
        tags=["agent"],
    )
    async def create_document(payload: AgentRequest, request: Request) -> AgentResponse:
        require_role(request, "owner", "editor")
        return await request.app.state.agent_service.run(payload.request)

    @application.get("/documents/{filename}", response_class=FileResponse, tags=["documents"])
    async def download_document(
        filename: Annotated[
            str,
            PathParameter(pattern=r"^(?:[a-f0-9]{8}|[a-f0-9]{32})\.docx$"),
        ],
    ) -> FileResponse:
        output_dir = Path(active_settings.outputs_dir).resolve()
        candidate = (output_dir / filename).resolve()
        if candidate.parent != output_dir or not candidate.is_file():
            return JSONResponse(status_code=404, content={"detail": "document not found"})
        return FileResponse(
            path=candidate,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
        )

    return application


app = create_app()
