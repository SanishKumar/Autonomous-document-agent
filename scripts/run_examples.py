from __future__ import annotations

import argparse
import json
from urllib import request


EXAMPLES = {
    "standard": (
        "Create a 90-day implementation plan for introducing an internal employee helpdesk "
        "chatbot in a company with 500 employees. Include objectives, project phases, owners, "
        "milestones, major risks, mitigations, and measurable success metrics."
    ),
    "complex": (
        "Create a technical proposal for an autonomous customer support agent that must launch "
        "within 6 weeks. It must run completely on-premise, support Hindi and English, use only "
        "open-source models, remain within a budget of INR 3 lakh, support 10,000 concurrent "
        "users, and provide 99.99 percent availability. Important technical and organizational "
        "details are missing, so make reasonable assumptions and clearly identify conflicts, "
        "risks, and decisions."
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one documented request against the API.")
    parser.add_argument("case", choices=EXAMPLES)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    payload = json.dumps({"request": EXAMPLES[args.case]}).encode("utf-8")
    outbound = request.Request(
        f"{args.base_url.rstrip('/')}/agent",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(outbound, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

