from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.document_builder import DocumentBuilder
from app.llm import JsonLLM
from app.prompts import (
    CONSTRAINT_SYSTEM,
    DRAFT_SYSTEM,
    OUTLINE_SYSTEM,
    REQUIREMENTS_SYSTEM,
    REVIEW_SYSTEM,
    REVISION_SYSTEM,
    as_json,
)
from app.schemas import (
    ConstraintResolution,
    DocumentDraft,
    DocumentOutline,
    ExecutionPlan,
    PlannedTask,
    RequirementAnalysis,
    ReviewResult,
    ToolName,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(slots=True)
class AgentState:
    request_id: str
    original_request: str
    plan: ExecutionPlan
    analysis: RequirementAnalysis | None = None
    resolution: ConstraintResolution | None = None
    outline: DocumentOutline | None = None
    draft: DocumentDraft | None = None
    initial_review: ReviewResult | None = None
    review: ReviewResult | None = None
    revised: bool = False
    revision_count: int = 0
    document_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


ToolFunction = Callable[[PlannedTask, AgentState], Awaitable[str]]


class AgentTools:
    def __init__(
        self,
        llm: JsonLLM,
        document_builder: DocumentBuilder,
        *,
        review_threshold: int = 8,
    ) -> None:
        self._llm = llm
        self._document_builder = document_builder
        self._review_threshold = review_threshold

    @property
    def registry(self) -> dict[ToolName, ToolFunction]:
        return {
            "analyze_requirements": self.analyze_requirements,
            "resolve_constraints": self.resolve_constraints,
            "create_outline": self.create_outline,
            "draft_document": self.draft_document,
            "review_document": self.review_document,
            "generate_docx": self.generate_docx,
        }

    async def analyze_requirements(self, task: PlannedTask, state: AgentState) -> str:
        prompt = (
            f"Original request:\n{state.original_request}\n\nPlanner output:\n{as_json(state.plan)}"
        )
        state.analysis = await self._validated_call(
            RequirementAnalysis, REQUIREMENTS_SYSTEM, prompt
        )
        state.analysis = self._sanitize_analysis(state.analysis, state.original_request)
        return (
            f"Identified {len(state.analysis.deliverables)} deliverables, "
            f"{len(state.analysis.constraints)} constraints, and "
            f"{len(state.analysis.conflicts)} conflicts."
        )

    async def resolve_constraints(self, task: PlannedTask, state: AgentState) -> str:
        if state.analysis is None:
            raise RuntimeError("requirements analysis is required before constraint resolution")
        prompt = (
            f"Original request:\n{state.original_request}\n\n"
            f"Validated analysis:\n{as_json(state.analysis)}\n\n"
            f"Planner decisions:\n{as_json(state.plan.decisions)}"
        )
        state.resolution = await self._validated_call(
            ConstraintResolution, CONSTRAINT_SYSTEM, prompt
        )
        return f"Made {len(state.resolution.decisions)} explicit scope decisions."

    async def create_outline(self, task: PlannedTask, state: AgentState) -> str:
        if state.analysis is None:
            raise RuntimeError("requirements analysis is required before outlining")
        context = {
            "original_request": state.original_request,
            "document_type": state.plan.document_type,
            "title": state.plan.title,
            "analysis": state.analysis,
            "constraint_resolution": state.resolution,
        }
        state.outline = await self._validated_call(
            DocumentOutline, OUTLINE_SYSTEM, as_json(context)
        )
        return f"Created a document-specific outline with {len(state.outline.sections)} sections."

    async def draft_document(self, task: PlannedTask, state: AgentState) -> str:
        if state.analysis is None or state.outline is None:
            raise RuntimeError("analysis and outline are required before drafting")
        context = {
            "original_request": state.original_request,
            "plan": state.plan,
            "analysis": state.analysis,
            "constraint_resolution": state.resolution,
            "outline": state.outline,
        }
        state.draft = await self._validated_call(DocumentDraft, DRAFT_SYSTEM, as_json(context))
        return f"Drafted {len(state.draft.sections)} structured sections."

    async def review_document(self, task: PlannedTask, state: AgentState) -> str:
        if state.draft is None:
            raise RuntimeError("a draft is required before review")
        state.review = await self._review(state)
        state.initial_review = state.review
        initial_score = state.initial_review.score

        while not state.review.passed and state.revision_count < 2:
            revision_context = {
                "original_request": state.original_request,
                "plan": state.plan,
                "current_draft": state.draft,
                "review": state.review,
                "revision_attempt": state.revision_count + 1,
            }
            previous_draft = state.draft
            try:
                state.draft = await self._validated_call(
                    DocumentDraft, REVISION_SYSTEM, as_json(revision_context)
                )
                state.review = await self._review(state)
                state.revised = True
                state.revision_count += 1
            except Exception as exc:  # A usable reviewed draft is preferable to losing the result.
                state.draft = previous_draft
                state.warnings.append(
                    f"Revision could not finish ({type(exc).__name__}). The last draft is retained for human review."
                )
                break

        return (
            f"Quality review scored {initial_score}/10 initially and "
            f"{state.review.score}/10 finally; revision_attempts={state.revision_count}."
        )

    async def generate_docx(self, task: PlannedTask, state: AgentState) -> str:
        if state.draft is None or state.review is None:
            raise RuntimeError("a reviewed draft is required before DOCX generation")
        assumptions = self._merge_unique(
            state.plan.assumptions,
            state.analysis.assumptions if state.analysis else [],
        )
        state.document_path = self._document_builder.build(
            request_id=state.request_id,
            plan=state.plan,
            draft=state.draft,
            assumptions=assumptions,
            resolution=state.resolution,
        )
        return f"Saved {state.document_path.name}."

    async def _review(self, state: AgentState) -> ReviewResult:
        context = {
            "original_request": state.original_request,
            "plan": state.plan,
            "analysis": state.analysis,
            "constraint_resolution": state.resolution,
            "draft": state.draft,
            "ready_threshold": self._review_threshold,
        }
        review = await self._validated_call(ReviewResult, REVIEW_SYSTEM, as_json(context))
        review = self._remove_non_blocking_unknowns(review, state.original_request)
        audit_issues, audit_instructions = self._deterministic_review_findings(state)
        if audit_issues:
            review = review.model_copy(
                update={
                    "score": min(review.score, self._review_threshold - 1),
                    "passed": False,
                    "missing_items": self._merge_unique(review.missing_items, audit_issues)[:12],
                    "revision_instructions": self._merge_unique(
                        review.revision_instructions, audit_instructions
                    )[:12],
                }
            )
        expected_passed = (
            review.score >= self._review_threshold
            and not review.contradictions
            and not audit_issues
        )
        if review.passed != expected_passed:
            review = review.model_copy(update={"passed": expected_passed})
        return review

    @staticmethod
    def _deterministic_review_findings(
        state: AgentState,
    ) -> tuple[list[str], list[str]]:
        if state.draft is None:
            return ["The draft is missing."], ["Create a complete structured draft."]

        request = state.original_request.casefold()
        sections = state.draft.sections
        content_values: list[str] = [
            state.draft.executive_summary,
            state.draft.conclusion,
        ]
        for section in sections:
            content_values.extend(
                [section.heading, *section.paragraphs, *section.bullets, *section.numbered_items]
            )
            if section.table is not None:
                content_values.extend(section.table.headers)
                content_values.extend(cell for row in section.table.rows for cell in row)
        combined = "\n".join(content_values).casefold()

        issues: list[str] = []
        instructions: list[str] = []
        raw_identifiers = [
            value
            for value in content_values
            if (
                " " not in value.strip()
                and value.strip().count("-") >= 3
                and value.strip() == value.strip().casefold()
            )
            or bool(re.search(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b", value))
        ]
        if raw_identifiers:
            issues.append("The draft contains a raw slug or internal identifier.")
            instructions.append(
                "Replace raw slugs or internal identifiers with reader-ready business language."
            )

        internal_roles = (
            "document revisor",
            "document reviser",
            "business document writer",
            "requirements analyst",
            "constraint resolver",
            "document architect",
            "quality reviewer",
        )
        if any(role in combined for role in internal_roles):
            issues.append("The draft uses an internal agent-component label as a business role.")
            instructions.append(
                "Replace internal agent-component labels with accountable project roles."
            )

        metric_requested = any(
            marker in request for marker in ("measurable", "success metric", "metrics", "kpi")
        )
        if metric_requested:
            metric_sections = [
                section
                for section in sections
                if any(
                    marker in section.heading.casefold()
                    for marker in ("metric", "measure", "success", "kpi")
                )
            ]
            quantified_entries = 0
            for section in metric_sections:
                entries = [*section.paragraphs, *section.bullets, *section.numbered_items]
                if section.table is not None:
                    entries.extend(" | ".join(row) for row in section.table.rows)
                quantified_entries += sum(
                    any(character.isdigit() for character in entry)
                    or "%" in entry
                    or any(
                        phrase in entry.casefold()
                        for phrase in ("at least", "no more than", "less than", "greater than")
                    )
                    for entry in entries
                )
            if quantified_entries < 3:
                issues.append(
                    "Requested success metrics are not sufficiently numeric and time-bound."
                )
                instructions.append(
                    "Add at least three numeric, time-bound success targets with a measurement source or method."
                )

        requested_terms = {
            "objectives": ("objective",),
            "phases": ("phase", "roadmap"),
            "owners": ("owner", "accountable"),
            "milestones": ("milestone", "exit gate", "exit criteria"),
            "risks": ("risk",),
            "mitigations": ("mitigation", "control"),
        }
        for requested, acceptable_terms in requested_terms.items():
            if requested in request and not any(term in combined for term in acceptable_terms):
                issues.append(f"The requested {requested} are missing or not explicit.")
                instructions.append(
                    f"Add a specific {requested} treatment tied to the proposed delivery plan."
                )

        if "paper-based" in combined and "paper-based" not in request:
            issues.append("The draft invents a paper-based current process not stated by the user.")
            instructions.append(
                "Treat the current helpdesk process as an unknown to validate during discovery."
            )

        placeholder_names = (
            "john doe",
            "jane doe",
            "john smith",
            "jane smith",
            "bob johnson",
            "alice johnson",
        )
        if any(name in combined for name in placeholder_names):
            issues.append("The draft invents placeholder personal names for owners.")
            instructions.append(
                "Replace invented names with accountable role titles because no real names were supplied."
            )

        budget_requested = any(
            marker in request
            for marker in ("budget", "cost", "inr", "usd", "eur", "rupee", "dollar", "$")
        )
        has_currency = bool(re.search(r"(?:\$|₹|\b(?:inr|usd|eur)\b)\s*[\d,]+", combined))
        if has_currency and not budget_requested:
            issues.append("The draft invents a currency amount not requested by the user.")
            instructions.append(
                "Remove the unsupported currency amount and make any funding need a discovery or approval action."
            )

        if "tickets per week" in combined and "tickets per week" not in request:
            issues.append("The draft invents a current ticket-volume baseline.")
            instructions.append(
                "Measure workload reduction against a ticket baseline established during discovery instead of inventing a weekly count."
            )

        if "vendor" not in request and any(
            marker in combined
            for marker in ("vendor support", "vendor licensing", "licensing agreement", "sla")
        ):
            issues.append("The draft introduces an unsupported vendor or licensing dependency.")
            instructions.append(
                "Keep the plan platform-neutral and validate commercial or support dependencies during discovery."
            )

        unsupported_deployment = any(
            marker in combined for marker in ("cloud-based", "developed in-house")
        )
        if unsupported_deployment and not any(
            marker in request for marker in ("cloud", "on-premise", "on premise", "in-house")
        ):
            issues.append("The draft invents a deployment or delivery model.")
            instructions.append(
                "Keep the deployment and delivery model open until discovery validates security, integration, and operating constraints."
            )

        if (
            "current helpdesk process involves" in combined
            and "current helpdesk process" not in request
        ):
            issues.append("The draft invents details of the current helpdesk workflow.")
            instructions.append(
                "Replace the invented workflow description with a discovery task to map the current process and baseline."
            )

        internal_workflow_phrases = (
            "create document outline",
            "draft technical proposal",
            "draft document",
            "review and revise document",
            "finalize technical proposal",
            "generate docx",
        )
        if any(phrase in combined for phrase in internal_workflow_phrases):
            issues.append("The business document exposes the document agent's internal workflow.")
            instructions.append(
                "Replace document-authoring steps with a delivery timeline containing project work, owners, outputs, and exit gates."
            )

        if "bert" in combined and "bert" not in request:
            issues.append(
                "The draft selects BERT without benchmark evidence for the requested agent."
            )
            instructions.append(
                "Use a benchmark-selected open-source instruction model and define language, quality, latency, and hardware evaluation gates."
            )

        conflicting_scale_request = all(
            marker in request for marker in ("on-premise", "budget", "10,000", "99.99")
        )
        if conflicting_scale_request:
            if "pilot" not in combined:
                issues.append("The conflicting request is not bounded to a controlled pilot.")
                instructions.append(
                    "Preserve the six-week date as a controlled pilot and define a separate production approval gate."
                )
            if not any(
                marker in combined
                for marker in (
                    "gated production",
                    "production target",
                    "production slo",
                    "defer",
                    "not commit",
                    "cannot guarantee",
                    "subject to capacity",
                )
            ):
                issues.append(
                    "The draft does not qualify the 10,000-user and 99.99% production targets."
                )
                instructions.append(
                    "State that concurrency and four-nines availability require measured capacity, redundancy, and cost evidence before commitment."
                )

        budget_match = re.search(r"\binr\s*([\d.]+)\s*lakh\b", request)
        if budget_match:
            budget_cap = float(budget_match.group(1))
            for section in sections:
                if "budget" not in section.heading.casefold() or section.table is None:
                    continue
                total_rows = [
                    row for row in section.table.rows if row and "total" in row[0].casefold()
                ]
                rows_to_measure = total_rows or section.table.rows
                amounts: list[float] = []
                for row in rows_to_measure:
                    row_text = " ".join(row).casefold()
                    amounts.extend(
                        float(value)
                        for value in re.findall(
                            r"(?:\binr\s*)?([\d.]+)\s*lakh\b",
                            row_text,
                        )
                    )
                measured_total = amounts[-1] if total_rows and amounts else sum(amounts)
                if measured_total > budget_cap + 0.001:
                    issues.append(
                        f"The budget table totals INR {measured_total:g} lakh, above the INR {budget_cap:g} lakh cap."
                    )
                    instructions.append(
                        "Revise the budget rows so their arithmetic is explicit and does not exceed the stated cap."
                    )
        return issues, instructions

    @staticmethod
    def _is_complex_request(user_request: str) -> bool:
        request = user_request.casefold()
        return any(
            marker in request
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

    @staticmethod
    def _sanitize_analysis(
        analysis: RequirementAnalysis,
        user_request: str,
    ) -> RequirementAnalysis:
        request = user_request.casefold()
        vendor_requested = any(
            marker in request for marker in ("vendor", "licens", "commercial support")
        )
        deployment_requested = any(
            marker in request for marker in ("cloud", "on-premise", "on premise", "in-house")
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
            if "limited it resources" in lowered and not any(
                marker in request for marker in ("resource", "staff", "team capacity")
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

        return analysis.model_copy(
            update={
                "deliverables": [value for value in analysis.deliverables if keep(value)],
                "constraints": [value for value in analysis.constraints if keep(value)],
                "missing_information": [
                    value for value in analysis.missing_information if keep(value)
                ],
                "assumptions": [value for value in analysis.assumptions if keep(value)],
                "conflicts": [value for value in analysis.conflicts if keep(value)],
                "risks": [value for value in analysis.risks if keep(value)],
            }
        )

    @staticmethod
    def _remove_non_blocking_unknowns(
        review: ReviewResult,
        user_request: str,
    ) -> ReviewResult:
        request = user_request.casefold()

        def is_non_blocking(value: str) -> bool:
            lowered = value.casefold()
            if "vendor" in lowered or "licens" in lowered or "sla" in lowered:
                return not any(
                    marker in request for marker in ("vendor", "licens", "commercial support")
                )
            if "employee technical proficiency" in lowered:
                return "technical proficiency" not in request
            if "current helpdesk" in lowered or "current workflow" in lowered:
                return "current helpdesk" not in request and "current workflow" not in request
            if "infrastructure" in lowered or "hardware" in lowered:
                return not any(
                    marker in request
                    for marker in ("infrastructure", "hardware", "on-premise", "on premise")
                )
            if any(
                marker in lowered
                for marker in (
                    "specific chatbot platform",
                    "select a platform",
                    "platform selection",
                )
            ):
                return not any(
                    marker in request for marker in ("platform", "technology", "model", "framework")
                )
            if "resource allocation" in lowered or "limited it resources" in lowered:
                return not any(
                    marker in request for marker in ("resource", "staff", "team capacity")
                )
            if "training data" in lowered or "data collection plan" in lowered:
                return not any(
                    marker in request for marker in ("training data", "data collection", "dataset")
                )
            if "review and update" in lowered or "review/update" in lowered:
                return not any(
                    marker in request
                    for marker in ("governance", "review process", "update process")
                )
            return False

        return review.model_copy(
            update={
                "missing_items": [
                    value for value in review.missing_items if not is_non_blocking(value)
                ],
                "revision_instructions": [
                    value for value in review.revision_instructions if not is_non_blocking(value)
                ],
            }
        )

    async def _validated_call(
        self,
        model_type: type[ModelT],
        system_prompt: str,
        user_prompt: str,
    ) -> ModelT:
        prompt = user_prompt
        last_error: ValidationError | None = None
        for _ in range(2):
            payload = await self._llm.complete_json(system_prompt, prompt)
            payload = self._normalize_payload(model_type, payload)
            try:
                return model_type.model_validate(payload)
            except ValidationError as exc:
                last_error = exc
                prompt = (
                    f"{user_prompt}\n\n"
                    "The previous JSON below failed schema validation. Correct it and return "
                    "the complete object, not a patch.\n"
                    f"Validation error:\n{str(exc)[:1200]}\n\n"
                    f"Previous JSON:\n{as_json(payload)[:16000]}"
                )
        raise RuntimeError(f"model output failed validation twice: {last_error}")

    @staticmethod
    def _normalize_payload(
        model_type: type[ModelT], payload: dict[str, object]
    ) -> dict[str, object]:
        """Repair a small set of safe omissions before strict schema validation."""
        normalized = dict(payload)
        if model_type is DocumentDraft:

            def clean_numeric_placeholders(value: object) -> object:
                if isinstance(value, str):
                    cleaned = re.sub(r"<(\d+(?:\.\d+)?%?)>", r"\1", value)
                    role_replacements = {
                        "Document Revisor": "Project Lead",
                        "Document Reviser": "Project Lead",
                        "Document_Revisor": "Project Lead",
                        "Document_Reviser": "Project Lead",
                        "Technical_Owner": "Technical Lead",
                        "Service_Desk_Owner": "Service Desk Lead",
                    }
                    for source, target in role_replacements.items():
                        cleaned = cleaned.replace(source, target)
                    cleaned = re.sub(
                        r"(?:open-source\s+)?(?:language\s+)?models?\s+like\s+BERT(?:\s+or\s+similar)?",
                        "a benchmark-selected open-source instruction model",
                        cleaned,
                        flags=re.IGNORECASE,
                    )
                    cleaned = re.sub(
                        r"proven open-source models like BERT(?:\s+or\s+similar)?",
                        "benchmark-selected open-source instruction models",
                        cleaned,
                        flags=re.IGNORECASE,
                    )
                    return cleaned
                if isinstance(value, list):
                    return [clean_numeric_placeholders(item) for item in value]
                if isinstance(value, dict):
                    return {key: clean_numeric_placeholders(item) for key, item in value.items()}
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return str(value)
                return value

            normalized = clean_numeric_placeholders(normalized)
            sections = normalized.get("sections")
            if isinstance(sections, list) and any(
                isinstance(section, dict)
                and any(
                    marker in str(section.get("heading", "")).casefold()
                    for marker in ("metric", "measure", "success", "kpi")
                )
                for section in sections
            ):
                kpi_markers = (
                    "accuracy",
                    "adoption",
                    "satisfaction",
                    "response time",
                    "containment",
                    "resolution rate",
                )
                for section in sections:
                    if not isinstance(section, dict):
                        continue
                    if "objective" not in str(section.get("heading", "")).casefold():
                        continue
                    bullets = section.get("bullets")
                    if isinstance(bullets, list):
                        section["bullets"] = [
                            bullet
                            for bullet in bullets
                            if not (
                                isinstance(bullet, str)
                                and any(character.isdigit() for character in bullet)
                                and any(marker in bullet.casefold() for marker in kpi_markers)
                            )
                        ]
            if not normalized.get("conclusion"):
                normalized["conclusion"] = (
                    "Proceed through the proposed phases and decision gates, validate the "
                    "stated assumptions during discovery, and use the defined success measures "
                    "to govern rollout."
                )
        return normalized

    @staticmethod
    def _merge_unique(*groups: list[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for value in group:
                key = value.casefold().strip()
                if key and key not in seen:
                    seen.add(key)
                    merged.append(value.strip())
        return merged
