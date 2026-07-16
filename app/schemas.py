from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ToolName = Literal[
    "analyze_requirements",
    "resolve_constraints",
    "create_outline",
    "draft_document",
    "review_document",
    "generate_docx",
]


class AgentRequest(BaseModel):
    request: Annotated[str, Field(min_length=10, max_length=5000)]

    @field_validator("request")
    @classmethod
    def validate_request(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if sum(character.isalpha() for character in normalized) < 8:
            raise ValueError("request must contain a meaningful natural-language instruction")
        if len(normalized.split()) < 4:
            raise ValueError("request must contain at least four words")
        return normalized


class PlannedTask(BaseModel):
    id: Annotated[str, Field(pattern=r"^task_[1-7]$")]
    description: Annotated[str, Field(min_length=8, max_length=240)]
    tool: ToolName
    depends_on: list[str] = Field(default_factory=list, max_length=3)


class ExecutionPlan(BaseModel):
    document_type: Annotated[str, Field(min_length=3, max_length=100)]
    title: Annotated[str, Field(min_length=5, max_length=180)]
    objective: Annotated[str, Field(min_length=10, max_length=600)]
    audience: Annotated[str, Field(min_length=2, max_length=200)]
    constraints: list[str] = Field(default_factory=list, max_length=12)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    decisions: list[str] = Field(default_factory=list, max_length=12)
    tasks: Annotated[list[PlannedTask], Field(min_length=5, max_length=6)]

    @model_validator(mode="after")
    def validate_task_graph(self) -> "ExecutionPlan":
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")

        tools = [task.tool for task in self.tasks]
        required = {
            "analyze_requirements",
            "create_outline",
            "draft_document",
            "review_document",
            "generate_docx",
        }
        missing = required.difference(tools)
        if missing:
            raise ValueError(f"plan is missing required tools: {sorted(missing)}")
        if len(tools) != len(set(tools)):
            raise ValueError("each tool may appear at most once")
        if self.tasks[-1].tool != "generate_docx":
            raise ValueError("generate_docx must be the final task")

        seen: set[str] = set()
        for task in self.tasks:
            unknown = set(task.depends_on).difference(seen)
            if unknown:
                raise ValueError(
                    f"{task.id} depends on tasks that have not completed: {sorted(unknown)}"
                )
            seen.add(task.id)

        if tools.index("create_outline") < tools.index("analyze_requirements"):
            raise ValueError("requirements must be analyzed before the outline")
        if tools.index("draft_document") < tools.index("create_outline"):
            raise ValueError("the outline must be created before drafting")
        if tools.index("review_document") < tools.index("draft_document"):
            raise ValueError("the draft must be created before review")
        return self


class RequirementAnalysis(BaseModel):
    objective: Annotated[str, Field(min_length=10, max_length=800)]
    audience: Annotated[str, Field(min_length=2, max_length=300)]
    deliverables: list[str] = Field(min_length=1, max_length=15)
    constraints: list[str] = Field(default_factory=list, max_length=15)
    missing_information: list[str] = Field(default_factory=list, max_length=15)
    assumptions: list[str] = Field(default_factory=list, max_length=15)
    conflicts: list[str] = Field(default_factory=list, max_length=12)
    risks: list[str] = Field(default_factory=list, max_length=15)


class ConstraintDecision(BaseModel):
    issue: Annotated[str, Field(min_length=3, max_length=300)]
    decision: Annotated[str, Field(min_length=3, max_length=500)]
    rationale: Annotated[str, Field(min_length=3, max_length=700)]
    impact: Annotated[str, Field(min_length=3, max_length=500)]


class ConstraintResolution(BaseModel):
    decisions: list[ConstraintDecision] = Field(min_length=1, max_length=10)
    recommended_scope: Annotated[str, Field(min_length=10, max_length=1000)]
    deferred_items: list[str] = Field(default_factory=list, max_length=12)


class OutlineSection(BaseModel):
    heading: Annotated[str, Field(min_length=2, max_length=120)]
    purpose: Annotated[str, Field(min_length=5, max_length=500)]
    suggested_format: Literal["prose", "bullets", "table", "steps", "callout"]


class DocumentOutline(BaseModel):
    sections: list[OutlineSection] = Field(min_length=4, max_length=15)

    @field_validator("sections")
    @classmethod
    def unique_headings(cls, value: list[OutlineSection]) -> list[OutlineSection]:
        headings = [section.heading.casefold() for section in value]
        if len(headings) != len(set(headings)):
            raise ValueError("outline section headings must be unique")
        return value


class DocumentTable(BaseModel):
    headers: list[str] = Field(min_length=1, max_length=6)
    rows: list[list[str]] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_row_widths(self) -> "DocumentTable":
        width = len(self.headers)
        if any(len(row) != width for row in self.rows):
            raise ValueError("every table row must have the same number of cells as headers")
        return self


class DraftSection(BaseModel):
    heading: Annotated[str, Field(min_length=2, max_length=120)]
    paragraphs: list[str] = Field(default_factory=list, max_length=8)
    bullets: list[str] = Field(default_factory=list, max_length=15)
    numbered_items: list[str] = Field(default_factory=list, max_length=15)
    table: DocumentTable | None = None

    @model_validator(mode="after")
    def require_content(self) -> "DraftSection":
        has_content = (
            self.paragraphs
            or self.bullets
            or self.numbered_items
            or self.table is not None
        )
        if not has_content:
            raise ValueError(
                "a draft section must contain paragraphs, bullets, numbered items, or a table"
            )
        return self


class DocumentDraft(BaseModel):
    executive_summary: Annotated[str, Field(min_length=30, max_length=1800)]
    sections: list[DraftSection] = Field(min_length=4, max_length=15)
    conclusion: Annotated[str, Field(min_length=10, max_length=1200)]


class ReviewResult(BaseModel):
    score: Annotated[int, Field(ge=1, le=10)]
    passed: bool
    strengths: list[str] = Field(default_factory=list, max_length=10)
    missing_items: list[str] = Field(default_factory=list, max_length=12)
    contradictions: list[str] = Field(default_factory=list, max_length=12)
    revision_instructions: list[str] = Field(default_factory=list, max_length=12)


class TaskExecution(BaseModel):
    task_id: str
    description: str
    tool: ToolName
    status: Literal["completed", "failed"]
    duration_ms: int
    attempts: int = 1
    result_summary: str | None = None
    error: str | None = None


class AgentResponse(BaseModel):
    request_id: str
    status: Literal["completed"]
    document_type: str
    title: str
    objective: str
    audience: str
    constraints: list[str]
    missing_information: list[str]
    assumptions: list[str]
    decisions: list[str]
    plan_source: Literal["model", "fallback"]
    planning_attempts: int
    plan: list[PlannedTask]
    execution_log: list[TaskExecution]
    initial_quality_score: int
    quality_score: int
    revised: bool
    reflection_feedback: list[str]
    summary: str
    document_url: str
    total_duration_ms: int


class ErrorDetail(BaseModel):
    stage: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    status: Literal["failed"] = "failed"
    error: ErrorDetail
