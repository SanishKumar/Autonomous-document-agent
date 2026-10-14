from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from app.config import Settings
from app.document_builder import DocumentBuilder
from app.events import EventSink, emit
from app.executor import ExecutionError, TaskExecutor
from app.llm import JsonLLM, build_llm
from app.planner import Planner
from app.schemas import AgentResponse, TaskExecution
from app.tools import AgentState, AgentTools


class AgentRunError(RuntimeError):
    def __init__(
        self,
        *,
        request_id: str,
        stage: str,
        message: str,
        execution_log: list[TaskExecution] | None = None,
    ) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.stage = stage
        self.execution_log = execution_log or []


class AgentService:
    def __init__(self, settings: Settings, llm: JsonLLM | None = None) -> None:
        self.settings = settings
        self._llm = llm or build_llm(settings)
        self._planner = Planner(self._llm)
        builder = DocumentBuilder(settings.outputs_dir)
        tools = AgentTools(
            self._llm,
            builder,
            review_threshold=settings.review_threshold,
        )
        self._executor = TaskExecutor(tools.registry)

    async def run(
        self,
        user_request: str,
        *,
        request_id: str | None = None,
        on_event: EventSink | None = None,
    ) -> AgentResponse:
        request_id = request_id or uuid4().hex[:8]
        started = perf_counter()
        await emit(on_event, "planning_started")
        try:
            planning = await self._planner.create_plan(user_request)
        except Exception as exc:
            raise AgentRunError(
                request_id=request_id,
                stage="planning",
                message=str(exc),
            ) from exc

        state = AgentState(
            request_id=request_id,
            original_request=user_request,
            plan=planning.plan,
        )
        await emit(on_event, "plan_ready", plan=planning.plan.model_dump(), source=planning.source)
        try:
            execution_log = await self._executor.execute(planning.plan, state, on_event)
        except ExecutionError as exc:
            raise AgentRunError(
                request_id=request_id,
                stage=exc.task_id,
                message=str(exc),
                execution_log=exc.log,
            ) from exc

        if (
            state.document_path is None
            or state.review is None
            or state.initial_review is None
            or state.draft is None
        ):
            raise AgentRunError(
                request_id=request_id,
                stage="completion",
                message="agent finished without a reviewed document",
                execution_log=execution_log,
            )

        assumptions = AgentTools._merge_unique(
            planning.plan.assumptions,
            state.analysis.assumptions if state.analysis else [],
        )
        decisions = list(planning.plan.decisions)
        if state.resolution is not None:
            decisions.extend(item.decision for item in state.resolution.decisions)

        await emit(
            on_event,
            "artifact_ready",
            plan=planning.plan.model_dump(),
            draft=state.draft.model_dump(),
            review=state.review.model_dump(),
            resolution=state.resolution.model_dump() if state.resolution else None,
            assumptions=assumptions,
            warnings=state.warnings,
        )

        return AgentResponse(
            request_id=request_id,
            status="completed",
            document_type=planning.plan.document_type,
            title=planning.plan.title,
            objective=planning.plan.objective,
            audience=planning.plan.audience,
            constraints=AgentTools._merge_unique(
                planning.plan.constraints,
                state.analysis.constraints if state.analysis else [],
            ),
            missing_information=AgentTools._merge_unique(
                planning.plan.missing_information,
                state.analysis.missing_information if state.analysis else [],
            ),
            assumptions=assumptions,
            decisions=AgentTools._merge_unique(decisions),
            plan_source=planning.source,
            planning_attempts=planning.attempts,
            plan=planning.plan.tasks,
            execution_log=execution_log,
            initial_quality_score=state.initial_review.score,
            quality_score=state.review.score,
            revised=state.revised,
            review_passed=state.review.passed,
            review_issues=AgentTools._merge_unique(
                state.review.missing_items,
                state.review.contradictions,
            ),
            warnings=state.warnings,
            reflection_feedback=state.initial_review.revision_instructions,
            summary=(
                f"Created a reviewed {planning.plan.document_type.lower()} with "
                f"{len(state.draft.sections)} main sections."
            ),
            document_url=f"/documents/{state.document_path.name}",
            total_duration_ms=round((perf_counter() - started) * 1000),
        )
