from __future__ import annotations

import argparse
import getpass
import json
from http.cookiejar import CookieJar
from urllib import request
from urllib.parse import urlparse

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
    base = args.base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        parser.error("Use HTTPS for a remote server, or HTTP on loopback only.")
    client = request.build_opener(request.HTTPCookieProcessor(CookieJar()))
    with client.open(base + "/api/auth/session", timeout=15) as response:
        session = json.loads(response.read())
    csrf = None
    if session["auth_enabled"]:
        if session["setup_required"]:
            parser.error("Create the owner account in the workspace before running examples.")
        credentials = {"email": input("Workspace email: "), "password": getpass.getpass()}
        login = request.Request(
            base + "/api/auth/login",
            data=json.dumps(credentials).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with client.open(login, timeout=30) as response:
            csrf = json.loads(response.read())["csrf_token"]
        del credentials, login
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    payload = json.dumps({"request": EXAMPLES[args.case]}).encode("utf-8")
    outbound = request.Request(
        f"{base}/agent",
        data=payload,
        headers=headers,
        method="POST",
    )
    try:
        with client.open(outbound, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
        print(json.dumps(result, indent=2))
    finally:
        if csrf:
            logout = request.Request(
                base + "/api/auth/logout", data=b"{}", headers=headers, method="POST"
            )
            with client.open(logout, timeout=15):
                pass


if __name__ == "__main__":
    main()
