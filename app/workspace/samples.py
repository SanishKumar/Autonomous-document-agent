"""Curated, fictional examples. Never represented as live model output."""

from __future__ import annotations

from app.planner import Planner
from app.schemas import DocumentDraft
from app.workspace.store import WorkspaceStore

TEMPLATES = [
    {
        "id": "proposal",
        "name": "Client proposal",
        "label": "WIN THE NEXT YES",
        "description": "A considered scope, a clear approach, and a case for moving forward.",
        "prompt": "Write a client proposal to redesign onboarding for a B2B software company. Include scope, a six-week timeline, deliverables, role-based owners, assumptions, and success measures.",
    },
    {
        "id": "project_plan",
        "name": "Project plan",
        "label": "MAKE IT HAPPEN",
        "description": "Turn an ambitious idea into phases, owners, and measurable outcomes.",
        "prompt": "Create a 90-day implementation plan for an internal employee helpdesk chatbot serving 500 employees. Include phases, owners, milestones, risks, mitigations, and measurable success metrics.",
    },
    {
        "id": "sop",
        "name": "Operating playbook",
        "label": "MAKE IT REPEATABLE",
        "description": "Give your team a practical, repeatable way to do their best work.",
        "prompt": "Create a standard operating procedure for onboarding a new consulting client. Include responsibilities, required inputs, numbered steps, quality checks, escalation paths, and a handover checklist.",
    },
    {
        "id": "specification",
        "name": "Product specification",
        "label": "GET EVERYONE ALIGNED",
        "description": "Connect the customer problem to requirements and acceptance criteria.",
        "prompt": "Write a product specification for a self-service client portal for a consulting firm. Include users, core journeys, functional requirements, privacy considerations, acceptance criteria, and open questions.",
    },
    {
        "id": "report",
        "name": "Decision report",
        "label": "BRING CLARITY",
        "description": "Make the options, trade-offs, and recommendation easy to act on.",
        "prompt": "Create a decision report comparing an internal build with a managed service for a small company's knowledge base. Include evaluation criteria, trade-offs, risks, assumptions, and a recommendation without inventing vendor prices.",
    },
]


def section(
    heading: str,
    paragraphs: list[str] | None = None,
    bullets: list[str] | None = None,
    table: dict | None = None,
) -> dict:
    return {
        "heading": heading,
        "paragraphs": paragraphs or [],
        "bullets": bullets or [],
        "numbered_items": [],
        "table": table,
    }


def seed_samples(store: WorkspaceStore) -> None:
    if store.list():
        return
    samples = [
        (
            "proposal",
            "A better first 30 days",
            "Meridian · Customer experience",
            "Redesign client onboarding for Meridian, a fictional B2B software company. Build a six-week proposal with clear deliverables, owners, risks, and success measures.",
            "Give every new customer a confident start. This six-week engagement brings research, journey design and a measured pilot together to reduce friction between a signed agreement and the first moment of value. Scope and targets below are illustrative, not verified client data.",
            [
                section(
                    "The opportunity",
                    [
                        "Onboarding is where a promise becomes an experience. Meridian wants a consistent path from handover to activation, with fewer repeated questions and clearer ownership at every step.",
                        "We recommend a focused redesign of the first 30 days. Start with evidence from customers and the delivery team, then validate the new experience with a small pilot before expanding.",
                    ],
                ),
                section(
                    "What we will deliver",
                    bullets=[
                        "A current-state journey map and a prioritized friction log.",
                        "A shared onboarding playbook with accountable owners and escalation paths.",
                        "A client-facing welcome kit, milestone checklist and communication templates.",
                        "A pilot scorecard and recommendations for the next rollout.",
                    ],
                ),
                section(
                    "A six-week path to confidence",
                    table={
                        "headers": ["Phase", "When", "Deliverable", "Owner"],
                        "rows": [
                            [
                                "Discover",
                                "Weeks 1–2",
                                "Customer interviews and baseline",
                                "Research lead",
                            ],
                            ["Design", "Weeks 3–4", "Playbook and welcome kit", "Experience lead"],
                            [
                                "Pilot",
                                "Week 5",
                                "Test with a small client cohort",
                                "Customer success lead",
                            ],
                            [
                                "Decide",
                                "Week 6",
                                "Results and rollout recommendation",
                                "Engagement lead",
                            ],
                        ],
                    },
                ),
                section(
                    "Define success before delivery",
                    table={
                        "headers": ["Measure", "Proposed pilot target", "How to measure"],
                        "rows": [
                            [
                                "Time to first value",
                                "20% reduction against discovery baseline",
                                "Milestone timestamps",
                            ],
                            [
                                "Onboarding satisfaction",
                                "At least 4 of 5 by day 30",
                                "End-of-onboarding survey",
                            ],
                            [
                                "Handover completeness",
                                "95% of required fields at kickoff",
                                "Weekly checklist audit",
                            ],
                        ],
                    },
                ),
                section(
                    "Risks worth making visible",
                    bullets=[
                        "Limited interview access: reserve customer and team time before kickoff.",
                        "Scope expansion: route new requests through a weekly scope review.",
                        "An unrepresentative pilot: agree selection criteria and record exceptions.",
                    ],
                ),
                section(
                    "The next conversation",
                    [
                        "Confirm the sponsor, nominate a customer success partner, and agree the pilot cohort. The first working session will validate the timeline, access needs and proposed success targets."
                    ],
                ),
            ],
            [
                "A client sponsor can approve scope and unblock access.",
                "The pilot can use existing tools; platform migration is outside scope.",
            ],
            [
                "Start with a small pilot before company-wide adoption.",
                "Validate success targets against the discovery baseline.",
            ],
            ["Who will sponsor the work?", "Which customers can join the pilot?"],
        ),
        (
            "project_plan",
            "From scattered knowledge to shared answers",
            "Internal operations · 90-day roadmap",
            "Plan a 90-day rollout of an employee support knowledge service for 500 employees, with milestones, ownership, risks and measurable targets.",
            "Build a dependable starting point for employee questions over 90 days. The proposed approach puts content ownership and human escalation in place before a wider rollout. This is a fictional sample roadmap with proposed targets for stakeholder validation.",
            [
                section(
                    "Start with the questions that matter",
                    [
                        "Use a discovery baseline to identify the most frequent, low-risk employee questions. Assign an owner to every knowledge source and preserve an obvious route to the service desk when an answer is uncertain."
                    ],
                ),
                section(
                    "The first 90 days",
                    table={
                        "headers": ["Window", "Focus", "Exit gate", "Owner"],
                        "rows": [
                            [
                                "Days 1–15",
                                "Discovery and content audit",
                                "Scope and baseline approved",
                                "Product lead",
                            ],
                            [
                                "Days 16–40",
                                "Build and integration",
                                "End-to-end test passes",
                                "Technical lead",
                            ],
                            [
                                "Days 41–65",
                                "Controlled pilot",
                                "Quality and privacy checks pass",
                                "Service desk lead",
                            ],
                            [
                                "Days 66–90",
                                "Staged rollout",
                                "Operations handover signed",
                                "Change lead",
                            ],
                        ],
                    },
                ),
                section(
                    "Guardrails before growth",
                    bullets=[
                        "Use approved content with named owners and review dates.",
                        "Apply source-level access controls to sensitive material.",
                        "Route unresolved questions to a human queue.",
                        "Review incorrect answers and recurring content gaps every week.",
                    ],
                ),
                section(
                    "A measurable pilot",
                    table={
                        "headers": ["Measure", "Illustrative gate", "Evidence"],
                        "rows": [
                            [
                                "Answer correctness",
                                "At least 90% on approved intents",
                                "Reviewed test set",
                            ],
                            ["User satisfaction", "At least 4 of 5", "Post-answer survey"],
                            ["Critical data exposure", "Zero incidents", "Security review"],
                        ],
                    },
                ),
                section(
                    "Open decisions",
                    bullets=[
                        "Confirm the employee access channel and identity integration.",
                        "Agree the knowledge review process with IT and HR.",
                        "Choose a deployment option after privacy and workload review.",
                    ],
                ),
                section(
                    "First-week checklist",
                    bullets=[
                        "Name the sponsor and delivery owners.",
                        "Audit the top support categories and available sources.",
                        "Book the day-15 scope and baseline review.",
                    ],
                ),
            ],
            [
                "Content owners can participate during discovery.",
                "A limited employee cohort can join the pilot.",
            ],
            ["Expand access only after the pilot gates pass."],
            ["Which knowledge sources are approved?", "What is the baseline ticket volume?"],
        ),
    ]
    for kind, title, audience, brief, summary, sections, assumptions, decisions, gaps in samples:
        doc, _ = store.create(
            {"title": title, "request": brief, "audience": audience, "document_type": kind},
            sample=True,
        )
        plan = Planner._fallback_plan(brief).model_copy(
            update={
                "title": title,
                "document_type": kind.replace("_", " ").title(),
                "audience": audience,
                "assumptions": assumptions,
                "decisions": decisions,
                "missing_information": gaps,
            }
        )
        draft = DocumentDraft.model_validate(
            {
                "executive_summary": summary,
                "sections": sections,
                "conclusion": "Validate the assumptions with stakeholders and agree the next decision before delivery begins.",
            }
        )
        store.record(
            doc["id"],
            "artifact_ready",
            {
                "plan": plan.model_dump(),
                "draft": draft.model_dump(),
                "assumptions": assumptions,
                "resolution": None,
                "review": None,
                "warnings": ["Curated fictional sample. No LLM was called."],
            },
        )
