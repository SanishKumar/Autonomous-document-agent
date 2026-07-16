from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Path as PathParameter, Request
from fastapi.responses import FileResponse, JSONResponse

from app.agent import AgentRunError, AgentService
from app.config import Settings
from app.schemas import AgentRequest, AgentResponse, ErrorResponse


def create_app(
    *,
    service: AgentService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    active_service = service or AgentService(active_settings)

    application = FastAPI(
        title="Autonomous Business Document Agent",
        version="1.0.0",
        description=(
            "Plans, executes, reviews, and generates structured Microsoft Word documents "
            "from natural-language business requests."
        ),
    )
    application.state.agent_service = active_service
    application.state.settings = active_settings

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
        return await request.app.state.agent_service.run(payload.request)

    @application.get("/documents/{filename}", response_class=FileResponse, tags=["documents"])
    async def download_document(
        filename: Annotated[
            str,
            PathParameter(pattern=r"^[a-f0-9]{8}\.docx$"),
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

