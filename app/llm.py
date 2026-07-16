from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    """Raised when a model request cannot produce usable JSON."""


class LLMHTTPError(LLMError):
    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"model API returned HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        json_generation_failed = self.status_code == 400 and any(
            marker in str(self).casefold()
            for marker in ("json_validate_failed", "failed to generate json")
        )
        return (
            json_generation_failed
            or self.status_code in {408, 409, 425, 429}
            or self.status_code >= 500
        )


class JsonLLM(Protocol):
    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]: ...


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object even if a model wrapped it in prose or code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise LLMError("model response did not contain a valid JSON object")


class OpenAICompatibleLLM:
    """Small provider-neutral client for Groq and Ollama's OpenAI-compatible APIs."""

    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.llm_base_url}/chat/completions"
        self._api_key = settings.llm_api_key
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds
        self._max_retries = settings.llm_max_retries

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 7000,
            "response_format": {"type": "json_object"},
        }

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = await self._post(payload)
                content = raw["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise LLMError("model response content was not text")
                return extract_json_object(content)
            except LLMHTTPError as exc:
                last_error = exc
                if not exc.retryable:
                    raise LLMError(f"model API rejected the request: {exc}") from exc
                if attempt == self._max_retries:
                    break
                delay = max(0.5 * (2**attempt), exc.retry_after or 0.0)
                await asyncio.sleep(min(delay, 60.0))
            except (KeyError, IndexError, TypeError, LLMError, httpx.TransportError) as exc:
                last_error = exc
                if attempt == self._max_retries:
                    break
                await asyncio.sleep(0.5 * (2**attempt))

        raise LLMError(f"model request failed after {self._max_retries + 1} attempts: {last_error}")

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "autonomous-document-agent/1.0",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=True,
        ) as client:
            response = await client.post(self._url, json=payload, headers=headers)

        if response.is_error:
            retry_after = self._parse_retry_after(response.headers.get("retry-after"))
            detail = response.text.strip()[:500] or response.reason_phrase
            raise LLMHTTPError(
                response.status_code,
                detail,
                retry_after=retry_after,
            )

        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise LLMError("model API returned a non-JSON response") from exc
        if not isinstance(result, dict):
            raise LLMError("model API response was not a JSON object")
        return result

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None


def build_llm(settings: Settings) -> JsonLLM:
    return OpenAICompatibleLLM(settings)
