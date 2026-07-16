from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.llm import JsonLLM, LLMError
from app.prompts import PLANNER_SYSTEM
from app.schemas import ExecutionPlan, PlannedTask


@dataclass(slots=True)
class PlanningResult:
    plan: ExecutionPlan
    source: str
    attempts: int
    validation_errors: list[str]


class Planner:
    def __init__(self, llm: JsonLLM) -> None:
        self._llm = llm

    async def create_plan(self, user_request: str) -> PlanningResult:
        errors: list[str] = []
        prompt = f"User request:\n{user_request}"
        for attempt in range(1, 3):
            try:
                payload = await self._llm.complete_json(PLANNER_SYSTEM, prompt)
                plan = ExecutionPlan.model_validate(payload)
                plan = self._apply_optional_tool_policy(plan, user_request)
                plan = self._remove_unrequested_solution_choices(plan, user_request)
                return PlanningResult(plan, "model", attempt, errors)
            except (ValidationError, ValueError, TypeError, LLMError) as exc:
                errors.append(str(exc))
                prompt = (
                    f"User request:\n{user_request}\n\n"
                    "Your previous plan failed validation. Return the full corrected JSON object.\n"
                    f"Validation error:\n{str(exc)[:1200]}"
                )

        return PlanningResult(
            plan=self._fallback_plan(user_request),
            source="fallback",
            attempts=2,
            validation_errors=errors,
        )

    @staticmethod
    def _needs_constraint_resolution(user_request: str) -> bool:
        lowered = user_request.casefold()
        return any(
            marker in lowered
            for marker in (
                "ambiguous",
                "conflict",
                "missing information",
                "missing details",
                "reasonable assumptions",
                "unrealistic",
                "budget",
                "on-premise",
                "on premise",
                "99.99",
            )
        )

    def _apply_optional_tool_policy(
        self,
        plan: ExecutionPlan,
        user_request: str,
    ) -> ExecutionPlan:
        needs_resolution = self._needs_constraint_resolution(user_request)
        has_resolution = any(task.tool == "resolve_constraints" for task in plan.tasks)

        if needs_resolution and not has_resolution:
            raise ValueError(
                "the request contains explicit ambiguity or conflicting constraints; "
                "include resolve_constraints"
            )
        if needs_resolution or not has_resolution:
            return plan

        retained = [task for task in plan.tasks if task.tool != "resolve_constraints"]
        id_map = {task.id: f"task_{index}" for index, task in enumerate(retained, start=1)}
        rebuilt: list[PlannedTask] = []
        previous_id: str | None = None
        for task in retained:
            dependencies = [
                id_map[dependency]
                for dependency in task.depends_on
                if dependency in id_map
            ]
            if not dependencies and previous_id is not None:
                dependencies = [previous_id]
            current_id = id_map[task.id]
            rebuilt.append(
                task.model_copy(
                    update={"id": current_id, "depends_on": dependencies}
                )
            )
            previous_id = current_id

        return ExecutionPlan.model_validate(
            plan.model_copy(update={"tasks": rebuilt}).model_dump()
        )

    @staticmethod
    def _remove_unrequested_solution_choices(
        plan: ExecutionPlan,
        user_request: str,
    ) -> ExecutionPlan:
        request = user_request.casefold()
        vendor_requested = any(
            marker in request for marker in ("vendor", "licens", "commercial support")
        )
        deployment_requested = any(
            marker in request
            for marker in ("cloud", "on-premise", "on premise", "in-house")
        )

        def keep(value: str) -> bool:
            lowered = value.casefold()
            if not vendor_requested and any(
                marker in lowered for marker in ("vendor", "licens", "sla")
            ):
                return False
            if not deployment_requested and any(
                marker in lowered for marker in ("cloud-based", "developed in-house")
            ):
                return False
            if (
                "limited it resources" in lowered
                and not any(marker in request for marker in ("resource", "staff", "team capacity"))
            ):
                return False
            if (
                "member" in lowered
                and any(character.isdigit() for character in lowered)
                and not any(marker in request for marker in ("team", "staff", "resource"))
            ):
                return False
            named_models = ("bert", "llama", "mistral", "qwen", "gemma")
            if any(model in lowered for model in named_models) and not any(
                model in request for model in named_models
            ):
                return False
            return True

        return plan.model_copy(
            update={
                "constraints": [value for value in plan.constraints if keep(value)],
                "missing_information": [
                    value for value in plan.missing_information if keep(value)
                ],
                "assumptions": [value for value in plan.assumptions if keep(value)],
                "decisions": [value for value in plan.decisions if keep(value)],
            }
        )

    @classmethod
    def _fallback_plan(cls, user_request: str) -> ExecutionPlan:
        lowered = user_request.casefold()
        needs_resolution = cls._needs_constraint_resolution(user_request)
        if "proposal" in lowered:
            document_type = "Technical Proposal"
        elif "sop" in lowered or "procedure" in lowered:
            document_type = "Standard Operating Procedure"
        elif "report" in lowered:
            document_type = "Business Report"
        else:
            document_type = "Project Implementation Plan"

        title = f"{document_type}: Recommended Approach"
        tasks = [
            PlannedTask(
                id="task_1",
                description=(
                    "Analyze the request, audience, deliverables, constraints, and missing inputs"
                ),
                tool="analyze_requirements",
                depends_on=[],
            )
        ]
        previous = "task_1"
        next_number = 2
        if needs_resolution:
            tasks.append(
                PlannedTask(
                    id="task_2",
                    description=(
                        "Resolve conflicting constraints and define a credible delivery scope"
                    ),
                    tool="resolve_constraints",
                    depends_on=["task_1"],
                )
            )
            previous = "task_2"
            next_number = 3

        steps = [
            (
                "create_outline",
                "Create a document-specific structure and choose suitable content formats",
            ),
            (
                "draft_document",
                "Draft the complete document using the validated analysis and decisions",
            ),
            (
                "review_document",
                "Review the draft against the request and perform one bounded revision if needed",
            ),
            (
                "generate_docx",
                "Generate the final professionally formatted Microsoft Word document",
            ),
        ]
        for tool, description in steps:
            task_id = f"task_{next_number}"
            tasks.append(
                PlannedTask(
                    id=task_id,
                    description=description,
                    tool=tool,
                    depends_on=[previous],
                )
            )
            previous = task_id
            next_number += 1

        return ExecutionPlan(
            document_type=document_type,
            title=title,
            objective=user_request,
            audience="Business and technical stakeholders",
            constraints=[],
            missing_information=[
                "Details not explicit in the request will be treated as assumptions."
            ],
            assumptions=[
                "Recommendations are planning estimates and require stakeholder validation."
            ],
            decisions=["Use a phased, risk-aware approach when requirements are uncertain."],
            tasks=tasks,
        )
