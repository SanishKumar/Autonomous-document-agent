from __future__ import annotations

from typing import Any


class FakeLLM:
    """Deterministic model double used to exercise orchestration, not a runtime provider."""

    def __init__(self) -> None:
        self.complex_review_calls = 0

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        is_complex = any(
            marker in user_prompt.casefold()
            for marker in ("10,000", "99.99", "3 lakh", "on-premise")
        )
        if "ROLE: PLANNER" in system_prompt:
            return self._plan(is_complex)
        if "ROLE: REQUIREMENTS_ANALYST" in system_prompt:
            return self._analysis(is_complex)
        if "ROLE: CONSTRAINT_RESOLVER" in system_prompt:
            return self._resolution()
        if "ROLE: DOCUMENT_ARCHITECT" in system_prompt:
            return self._outline(is_complex)
        if "ROLE: BUSINESS_DOCUMENT_WRITER" in system_prompt:
            return self._draft(is_complex, revised=False)
        if "ROLE: QUALITY_REVIEWER" in system_prompt:
            if is_complex:
                self.complex_review_calls += 1
                if self.complex_review_calls == 1:
                    return {
                        "score": 7,
                        "passed": False,
                        "strengths": ["The phased architecture is credible and addresses language support."],
                        "missing_items": [
                            "Budget allocations need explicit validation gates.",
                            "Pilot and production availability targets should be separated.",
                        ],
                        "contradictions": [],
                        "revision_instructions": [
                            "Add an indicative INR 3 lakh pilot budget with exclusions.",
                            "State that 99.99% is a later production target, not a six-week pilot commitment.",
                        ],
                    }
            return {
                "score": 9,
                "passed": True,
                "strengths": [
                    "The document covers the requested constraints with measurable outcomes.",
                    "Owners, milestones, risks, and next steps are explicit.",
                ],
                "missing_items": [],
                "contradictions": [],
                "revision_instructions": [],
            }
        if "ROLE: DOCUMENT_REVISER" in system_prompt:
            return self._draft(True, revised=True)
        raise AssertionError(f"Unexpected prompt role: {system_prompt[:80]}")

    @staticmethod
    def _plan(complex_request: bool) -> dict[str, Any]:
        if complex_request:
            tools = [
                ("analyze_requirements", "Analyze technical, operational, schedule, and budget requirements"),
                ("resolve_constraints", "Resolve conflicts between scope, capacity, availability, time, and budget"),
                ("create_outline", "Design a decision-oriented technical proposal structure"),
                ("draft_document", "Draft a phased proposal with architecture, delivery, cost, and risks"),
                ("review_document", "Check every constraint and revise unsupported commitments once"),
                ("generate_docx", "Generate the reviewed proposal as a formatted Word document"),
            ]
            tasks = []
            for index, (tool, description) in enumerate(tools, start=1):
                tasks.append(
                    {
                        "id": f"task_{index}",
                        "description": description,
                        "tool": tool,
                        "depends_on": [] if index == 1 else [f"task_{index - 1}"],
                    }
                )
            return {
                "document_type": "Technical Proposal",
                "title": "Phased On-Premise Bilingual Autonomous Support Agent",
                "objective": "Define a credible six-week path for an on-premise Hindi and English support-agent pilot while exposing production feasibility gaps.",
                "audience": "Technology leadership, customer support leadership, and finance",
                "constraints": [
                    "Launch within six weeks",
                    "Run completely on-premise using open-source models",
                    "Support Hindi and English",
                    "Remain within INR 3 lakh",
                    "Target 10,000 concurrent users and 99.99% availability",
                ],
                "missing_information": [
                    "Existing hardware capacity and procurement lead time",
                    "Expected request rate, response latency, and average session length",
                    "Support knowledge-base size and data quality",
                ],
                "assumptions": [
                    "Existing servers are available for the six-week pilot.",
                    "The first release covers a controlled subset of support intents.",
                    "INR 3 lakh excludes existing hardware and internal salaries.",
                ],
                "decisions": [
                    "Treat six weeks as a production-like pilot, not unrestricted enterprise launch.",
                    "Validate scale and high availability before committing to production SLOs.",
                ],
                "tasks": tasks,
            }

        tools = [
            ("analyze_requirements", "Analyze objectives, audience, deliverables, and explicit constraints"),
            ("create_outline", "Create a project-plan outline for a 90-day rollout"),
            ("draft_document", "Draft phases, owners, milestones, risks, and success metrics"),
            ("review_document", "Review completeness and revise once if the quality threshold is missed"),
            ("generate_docx", "Generate the reviewed plan as a formatted Word document"),
        ]
        tasks = []
        for index, (tool, description) in enumerate(tools, start=1):
            tasks.append(
                {
                    "id": f"task_{index}",
                    "description": description,
                    "tool": tool,
                    "depends_on": [] if index == 1 else [f"task_{index - 1}"],
                }
            )
        return {
            "document_type": "90-Day Implementation Plan",
            "title": "Employee Helpdesk Chatbot: 90-Day Implementation Plan",
            "objective": "Plan a controlled 90-day introduction of an internal helpdesk chatbot for 500 employees.",
            "audience": "Executive sponsor, IT, HR, service desk, and project delivery teams",
            "constraints": ["Ninety-day delivery window", "Five hundred employees"],
            "missing_information": ["Current ticket volume", "Knowledge-base readiness"],
            "assumptions": [
                "The company has an internal knowledge base and named content owners.",
                "The initial release supports English and common tier-one helpdesk intents.",
            ],
            "decisions": ["Use a limited pilot before company-wide rollout."],
            "tasks": tasks,
        }

    @staticmethod
    def _analysis(complex_request: bool) -> dict[str, Any]:
        if complex_request:
            return {
                "objective": "Produce a decision-ready technical proposal for a bilingual, on-premise autonomous support-agent pilot.",
                "audience": "Technology, support operations, security, infrastructure, and finance leaders",
                "deliverables": [
                    "Target architecture",
                    "Six-week delivery plan",
                    "Budget envelope",
                    "Feasibility decisions",
                    "Risk and validation plan",
                ],
                "constraints": [
                    "On-premise deployment",
                    "Open-source models only",
                    "Hindi and English support",
                    "Six weeks and INR 3 lakh",
                    "10,000 concurrent users and 99.99% availability",
                ],
                "missing_information": [
                    "Hardware inventory",
                    "Traffic distribution and latency SLO",
                    "Escalation policy",
                    "Knowledge-base coverage",
                ],
                "assumptions": [
                    "Existing GPU-capable infrastructure can be reused for the pilot.",
                    "The pilot starts with twenty high-volume intents.",
                    "Human agents remain available for escalation.",
                ],
                "conflicts": [
                    "The stated budget is unlikely to fund new redundant hardware for 10,000 concurrent users.",
                    "Six weeks is insufficient to validate a 99.99% production SLO across a new bilingual system.",
                ],
                "risks": [
                    "Hindi response quality varies by domain terminology.",
                    "Capacity targets cannot be sized without workload measurements.",
                    "On-premise model operations require monitoring and specialist ownership.",
                ],
            }
        return {
            "objective": "Deliver a measured 90-day rollout plan for an employee helpdesk chatbot.",
            "audience": "Executive sponsor, IT, HR, service desk, and employees",
            "deliverables": [
                "Objectives and scope",
                "Phased timeline and milestones",
                "Ownership model",
                "Risk controls",
                "Success measures",
            ],
            "constraints": ["Ninety days", "Five hundred employees"],
            "missing_information": ["Ticket baseline", "Approved chatbot channel"],
            "assumptions": [
                "A searchable internal knowledge base exists.",
                "IT and HR can nominate content owners during week one.",
            ],
            "conflicts": [],
            "risks": ["Stale knowledge articles", "Low employee adoption", "Incorrect responses"],
        }

    @staticmethod
    def _resolution() -> dict[str, Any]:
        return {
            "decisions": [
                {
                    "issue": "Six-week launch versus enterprise scale",
                    "decision": "Launch a production-like pilot for a controlled user cohort and twenty intents.",
                    "rationale": "A bounded pilot can validate demand, quality, safety, and performance inside six weeks.",
                    "impact": "The date is retained, but unrestricted 10,000-user access is deferred.",
                },
                {
                    "issue": "INR 3 lakh versus redundant on-premise infrastructure",
                    "decision": "Use existing hardware and spend the budget on integration, evaluation, and observability.",
                    "rationale": "New redundant GPU capacity would exceed the stated envelope.",
                    "impact": "Hardware procurement and production high availability require a separate business case.",
                },
                {
                    "issue": "99.99% availability commitment",
                    "decision": "Measure availability during the pilot and treat 99.99% as a gated production target.",
                    "rationale": "The target requires redundancy, operational support, and failure testing not yet defined.",
                    "impact": "No unsupported SLO is promised in the initial launch.",
                },
            ],
            "recommended_scope": "Deliver a six-week on-premise bilingual pilot with controlled access, human escalation, measurable quality gates, and a load-test-backed production recommendation.",
            "deferred_items": [
                "Unrestricted 10,000-user concurrency",
                "Formal 99.99% availability SLO",
                "New high-availability GPU cluster procurement",
            ],
        }

    @staticmethod
    def _outline(complex_request: bool) -> dict[str, Any]:
        headings = (
            [
                ("Purpose and recommendation", "Frame the decision and bounded pilot", "callout"),
                ("Requirements and feasibility", "Separate stated targets from evidence gaps", "bullets"),
                ("Target architecture", "Describe the on-premise components and controls", "prose"),
                ("Six-week delivery plan", "Show phases, owners, and exit gates", "table"),
                ("Budget envelope", "Allocate the pilot budget and state exclusions", "table"),
                ("Quality and scale validation", "Define bilingual and load-test gates", "bullets"),
                ("Risks and mitigations", "Make operational and technical risks explicit", "table"),
                ("Decision gates and next steps", "State approvals required", "steps"),
            ]
            if complex_request
            else [
                ("Objectives and outcomes", "Define the business outcomes", "bullets"),
                ("Scope and operating assumptions", "Bound the initial release", "prose"),
                ("90-day roadmap", "Show phases and milestones", "table"),
                ("Roles and governance", "Assign accountable owners", "bullets"),
                ("Risks and mitigations", "Address delivery and adoption risks", "table"),
                ("Success metrics", "Define measurable launch criteria", "table"),
                ("Immediate next steps", "List actions to begin", "steps"),
            ]
        )
        return {
            "sections": [
                {"heading": heading, "purpose": purpose, "suggested_format": format_name}
                for heading, purpose, format_name in headings
            ]
        }

    @staticmethod
    def _draft(complex_request: bool, *, revised: bool) -> dict[str, Any]:
        if complex_request:
            availability_text = (
                "Treat 99.99% as a gated production target. The pilot records measured availability "
                "without promising a four-nines SLO."
                if revised
                else "Measure service availability during the controlled pilot."
            )
            budget_rows = (
                [
                    ["Integration and workflow", "90,000", "Connect knowledge, escalation, and audit paths"],
                    ["Evaluation and language QA", "70,000", "Hindi/English test set and native-speaker review"],
                    ["Observability and load testing", "80,000", "Metrics, dashboards, failure and capacity tests"],
                    ["Contingency", "60,000", "Model tuning and integration uncertainty"],
                    ["Total", "300,000", "Pilot cap, subject to week-one validation"],
                ]
                if revised
                else [["Pilot delivery envelope", "300,000", "Detailed validation during discovery"]]
            )
            return {
                "executive_summary": (
                    "A six-week launch is credible only as a controlled, production-like pilot. The proposed "
                    "system runs on existing on-premise infrastructure, uses open-source language and embedding "
                    "models, supports Hindi and English, and retains human escalation. The pilot will validate "
                    "quality, safety, throughput, and operating cost before enterprise commitments are approved."
                ),
                "sections": [
                    {
                        "heading": "Purpose and recommendation",
                        "paragraphs": [
                            "Approve a bounded pilot for selected support intents and a controlled user cohort. Preserve the six-week date, but gate broad rollout on bilingual quality, load, security, and recovery evidence."
                        ],
                        "bullets": [],
                        "numbered_items": [],
                        "table": None,
                    },
                    {
                        "heading": "Requirements and feasibility",
                        "paragraphs": [
                            "The on-premise, open-source, bilingual constraints are compatible with a pilot. The concurrency, availability, schedule, and budget targets cannot all be treated as proven production commitments without traffic profiles, hardware inventory, redundancy design, and failure testing."
                        ],
                        "bullets": [
                            "Pilot commitment: twenty high-volume intents, controlled access, and human escalation.",
                            "Evidence gap: requests per second, token profile, latency target, and session duration are not yet known.",
                            "Infrastructure assumption: existing GPU-capable servers are available and approved for reuse.",
                            availability_text,
                        ],
                        "numbered_items": [],
                        "table": None,
                    },
                    {
                        "heading": "Target architecture",
                        "paragraphs": [
                            "An API gateway authenticates users and applies rate limits. An orchestration service classifies requests, retrieves approved knowledge, invokes the bilingual model, applies policy checks, and routes low-confidence cases to a human queue. Model serving, vector search, logs, and evaluation data remain inside the company network.",
                            "The design keeps components replaceable: model serving exposes an internal API, retrieval is separated from generation, and policy checks run before a response is returned. Structured traces record retrieval sources, latency, confidence, and escalation outcomes without storing unnecessary personal data.",
                        ],
                        "bullets": [
                            "Open-source serving layer with quantized model candidates benchmarked on available hardware.",
                            "Hybrid Hindi/English retrieval with approved knowledge sources and document-level access controls.",
                            "Circuit breaker and queue-based fallback when model capacity is exhausted.",
                        ],
                        "numbered_items": [],
                        "table": None,
                    },
                    {
                        "heading": "Six-week delivery plan",
                        "paragraphs": [],
                        "bullets": [],
                        "numbered_items": [],
                        "table": {
                            "headers": ["Week", "Focus", "Key outputs", "Owner", "Exit gate"],
                            "rows": [
                                ["1", "Discovery", "Traffic assumptions, intents, data and hardware inventory", "Product + Infra", "Scope and test plan approved"],
                                ["2", "Foundation", "Model benchmark, retrieval baseline, API skeleton", "ML + Platform", "Candidate meets latency baseline"],
                                ["3", "Integration", "Knowledge ingestion, authentication, escalation", "Platform + Support", "End-to-end happy path works"],
                                ["4", "Quality", "Hindi/English evaluation, policy tests, red-team cases", "ML + QA", "Quality threshold met"],
                                ["5", "Reliability", "Load, failover, monitoring, runbooks", "SRE + Security", "Pilot SLO and controls pass"],
                                ["6", "Pilot", "Controlled release, daily review, go/no-go report", "Product + Support", "Production recommendation signed"],
                            ],
                        },
                    },
                    {
                        "heading": "Budget envelope",
                        "paragraphs": [
                            "The INR 3 lakh envelope is an indicative pilot budget, excludes existing hardware and internal salaries, and must be validated after week-one inventory and vendor checks."
                        ],
                        "bullets": [],
                        "numbered_items": [],
                        "table": {
                            "headers": ["Workstream", "INR", "Purpose"],
                            "rows": budget_rows,
                        },
                    },
                    {
                        "heading": "Quality and scale validation",
                        "paragraphs": [
                            "A fixed bilingual evaluation set should cover intent resolution, groundedness, safety, escalation correctness, and terminology. Native Hindi reviewers approve domain phrasing. Load testing then increases arrival rate until latency or error thresholds fail, producing a capacity curve rather than an unsupported concurrency claim."
                        ],
                        "bullets": [
                            "Quality gate: at least 85% correct resolution on approved pilot intents and no critical safety failures.",
                            "Escalation gate: at least 95% of low-confidence or restricted requests route correctly.",
                            "Performance gate: publish throughput, p95 latency, saturation point, and recovery time on actual hardware.",
                            "Rollout gate: approve capacity expansion only after workload measurements support the business case.",
                        ],
                        "numbered_items": [],
                        "table": None,
                    },
                    {
                        "heading": "Risks and mitigations",
                        "paragraphs": [],
                        "bullets": [],
                        "numbered_items": [],
                        "table": {
                            "headers": ["Risk", "Likelihood", "Impact", "Mitigation", "Owner"],
                            "rows": [
                                ["Hindi terminology errors", "Medium", "High", "Native-speaker review and domain glossary", "QA Lead"],
                                ["Hardware saturation", "High", "High", "Capacity test, queue limits, and graceful fallback", "Infra Lead"],
                                ["Stale knowledge", "Medium", "High", "Named content owners and freshness checks", "Support Lead"],
                                ["Unsupported SLO expectation", "High", "High", "Pilot SLO and signed production gate", "Sponsor"],
                                ["Sensitive data exposure", "Medium", "High", "Access control, redaction, and audit logging", "Security"],
                            ],
                        },
                    },
                    {
                        "heading": "Decision gates and next steps",
                        "paragraphs": [],
                        "bullets": [],
                        "numbered_items": [
                            "Name the executive sponsor, product owner, infrastructure owner, and support content owner.",
                            "Complete the hardware, traffic, data, and security discovery pack in week one.",
                            "Approve pilot users, twenty intents, evaluation thresholds, and escalation policy.",
                            "At the end of week six, decide whether to expand, remediate, or stop based on measured evidence.",
                        ],
                        "table": None,
                    },
                ],
                "conclusion": "Proceed with the bounded pilot and evidence gates. Do not approve unrestricted 10,000-user scale or a 99.99% production SLO until capacity, redundancy, failure recovery, and total cost are validated on the intended infrastructure.",
            }

        return {
            "executive_summary": "This plan introduces an internal employee helpdesk chatbot over 90 days through discovery, controlled build, pilot, and company-wide rollout. It assigns clear owners, keeps knowledge quality and escalation controls in scope, and uses measurable adoption, containment, quality, and satisfaction targets to govern expansion.",
            "sections": [
                {
                    "heading": "Objectives and outcomes",
                    "paragraphs": [],
                    "bullets": [
                        "Give 500 employees faster answers to common IT and HR questions.",
                        "Reduce avoidable tier-one tickets while preserving a clear human escalation path.",
                        "Create a governed knowledge workflow with named owners and freshness standards.",
                        "Use measured pilot evidence to decide whether and how to expand automation.",
                    ],
                    "numbered_items": [],
                    "table": None,
                },
                {
                    "heading": "Scope and operating assumptions",
                    "paragraphs": [
                        "The initial release covers high-volume, low-risk employee helpdesk intents and retrieves answers only from approved internal content. Requests involving personal decisions, security incidents, or low-confidence responses are handed to the existing service desk.",
                        "The delivery team will confirm ticket baselines, approved channels, privacy requirements, and knowledge ownership during the first two weeks. Estimates in this plan should be recalibrated when that baseline is available.",
                    ],
                    "bullets": [],
                    "numbered_items": [],
                    "table": None,
                },
                {
                    "heading": "90-day roadmap",
                    "paragraphs": [],
                    "bullets": [],
                    "numbered_items": [],
                    "table": {
                        "headers": ["Phase", "Timing", "Activities", "Owner", "Exit milestone"],
                        "rows": [
                            ["Discover", "Days 1-15", "Baseline tickets, select intents, audit knowledge, confirm controls", "Product Lead", "Scope and measures approved"],
                            ["Build", "Days 16-35", "Configure retrieval, conversation flows, access and escalation", "Tech Lead", "End-to-end test passes"],
                            ["Validate", "Days 36-50", "Quality, privacy, security and employee usability testing", "QA Lead", "Pilot readiness signed"],
                            ["Pilot", "Days 51-70", "Release to 50 employees, review failures and improve content", "Service Desk", "Pilot gates achieved"],
                            ["Roll out", "Days 71-90", "Stage company access, train support, publish runbook", "Change Lead", "Operational handover complete"],
                        ],
                    },
                },
                {
                    "heading": "Roles and governance",
                    "paragraphs": [
                        "The executive sponsor resolves cross-functional decisions. The product lead owns scope and metrics; the technical lead owns the service; IT and HR content owners approve source material; the service desk owns escalation and daily operations; security and privacy reviewers approve controls."
                    ],
                    "bullets": [
                        "Weekly delivery review: milestones, risks, decisions, and metric trend.",
                        "Twice-weekly pilot review: incorrect answers, escalations, content gaps, and employee feedback.",
                        "Monthly knowledge review after launch: expiry, ownership, and policy changes.",
                    ],
                    "numbered_items": [],
                    "table": None,
                },
                {
                    "heading": "Risks and mitigations",
                    "paragraphs": [],
                    "bullets": [],
                    "numbered_items": [],
                    "table": {
                        "headers": ["Risk", "Likelihood", "Impact", "Mitigation", "Owner"],
                        "rows": [
                            ["Stale knowledge", "Medium", "High", "Named owners, expiry dates, and review queue", "Content Owners"],
                            ["Incorrect answer", "Medium", "High", "Grounded retrieval, confidence threshold, escalation", "Tech Lead"],
                            ["Low adoption", "Medium", "Medium", "Pilot champions, channel placement, and training", "Change Lead"],
                            ["Privacy exposure", "Low", "High", "Data minimization, access controls, and audit logs", "Security"],
                            ["Service desk overload", "Low", "Medium", "Staged rollout and monitored escalation volume", "Service Desk"],
                        ],
                    },
                },
                {
                    "heading": "Success metrics",
                    "paragraphs": [
                        "Baseline values are confirmed in discovery. Targets below govern the 50-person pilot and the staged company rollout."
                    ],
                    "bullets": [],
                    "numbered_items": [],
                    "table": {
                        "headers": ["Measure", "Pilot target", "Day-90 target", "Source"],
                        "rows": [
                            ["Correct resolution", ">= 85%", ">= 90%", "Reviewed test set"],
                            ["Self-service containment", ">= 35%", ">= 50%", "Chat and ticket logs"],
                            ["Employee satisfaction", ">= 4.0/5", ">= 4.2/5", "Post-chat survey"],
                            ["p95 response time", "< 5 seconds", "< 4 seconds", "Service telemetry"],
                            ["Critical privacy incidents", "0", "0", "Security register"],
                        ],
                    },
                },
                {
                    "heading": "Immediate next steps",
                    "paragraphs": [],
                    "bullets": [],
                    "numbered_items": [
                        "Confirm the executive sponsor, product lead, technical lead, and content owners.",
                        "Export the prior eight to twelve weeks of categorized helpdesk tickets for baseline analysis.",
                        "Select the first ten to twenty intents and identify their approved knowledge sources.",
                        "Schedule the day-15 scope review and day-50 pilot go/no-go decision.",
                    ],
                    "table": None,
                },
            ],
            "conclusion": "Begin with discovery and ownership decisions in the first week. Keep the company-wide rollout conditional on pilot quality, privacy, adoption, and operational-readiness gates rather than the calendar alone.",
        }
