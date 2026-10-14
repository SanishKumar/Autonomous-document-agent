from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # The app still works when variables are supplied by the shell.
    load_dotenv = None


@dataclass(frozen=True, slots=True)
class Settings:
    llm_provider: str = "ollama"
    llm_model: str = "llama3.2:3b"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 2
    review_threshold: int = 8
    outputs_dir: Path = Path("outputs")
    max_concurrent_jobs: int = 2
    max_pending_jobs: int = 20
    job_timeout_seconds: float = 300.0
    auth_enabled: bool = True
    secure_cookies: bool = False
    session_hours: int = 12

    @classmethod
    def from_env(cls) -> Settings:
        if load_dotenv is not None:
            load_dotenv()

        provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
        if provider == "groq":
            base_url = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
            api_key = os.getenv("GROQ_API_KEY", "").strip()
            model = os.getenv("LLM_MODEL", "").strip()
        elif provider == "ollama":
            base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
            api_key = os.getenv("LLM_API_KEY", "ollama")
            model = os.getenv("LLM_MODEL", "llama3.2:3b").strip()
        else:
            raise ValueError("LLM_PROVIDER must be either 'ollama' or 'groq'.")

        if provider == "groq" and not api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq.")
        if not model:
            raise ValueError("LLM_MODEL must name a model available from the selected provider.")

        return cls(
            llm_provider=provider,
            llm_model=model,
            llm_base_url=base_url.rstrip("/"),
            llm_api_key=api_key,
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "90")),
            llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
            review_threshold=int(os.getenv("REVIEW_THRESHOLD", "8")),
            outputs_dir=Path(os.getenv("OUTPUTS_DIR", "outputs")),
            max_concurrent_jobs=max(1, min(8, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))),
            max_pending_jobs=max(1, int(os.getenv("MAX_PENDING_JOBS", "20"))),
            job_timeout_seconds=max(10, float(os.getenv("JOB_TIMEOUT_SECONDS", "300"))),
            auth_enabled=os.getenv("AUTH_ENABLED", "true").lower() == "true",
            secure_cookies=os.getenv("SECURE_COOKIES", "false").lower() == "true",
            session_hours=max(1, min(72, int(os.getenv("SESSION_HOURS", "12")))),
        )
