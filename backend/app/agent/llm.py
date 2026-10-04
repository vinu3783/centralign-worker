"""LLM provider abstraction.

The agent only ever asks an LLM for JSON that is then validated against a
Pydantic schema. LLM output is data, never code.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_OPENAI_BASE_URL = "https://api.groq.com/openai/v1"


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str
    model: str

    @property
    def is_demo(self) -> bool:
        return False

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

    @abstractmethod
    def complete_json(self, system: str, user: str) -> str:
        """Return the raw JSON text produced by the model."""

    def structured(self, system: str, user: str, schema: type[T], *, attempts: int = 2) -> T:
        """Ask for JSON matching `schema`; feed validation errors back once."""
        prompt, last_err = user, ""
        for _ in range(attempts):
            raw = self.complete_json(system, prompt)
            try:
                return schema.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_err = str(exc)[:1500]
                prompt = (f"{user}\n\nYour previous answer was invalid:\n{last_err}\n"
                          "Return ONLY corrected JSON matching the schema.")
        raise LLMError(f"Model output failed schema validation: {last_err}")


class DemoProvider(LLMProvider):
    """No model calls: understanding and planning use the deterministic rule engine."""

    name = "demo"
    model = "rule-based (DEMO mode)"

    @property
    def is_demo(self) -> bool:
        return True

    @property
    def label(self) -> str:
        return "DEMO mode (deterministic rules)"

    def complete_json(self, system: str, user: str) -> str:  # pragma: no cover - never called
        raise LLMError("Demo provider does not call an LLM")


class OpenAICompatibleProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None, timeout: float):
        from openai import OpenAI

        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)

    def complete_json(self, system: str, user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
        except Exception as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        return resp.choices[0].message.content or "{}"


class GeminiProvider(OpenAICompatibleProvider):
    """Gemini through Google's OpenAI-compatible endpoint."""

    name = "gemini"


class GroqProvider(OpenAICompatibleProvider):
    """Groq (open models such as Llama) through its OpenAI-compatible endpoint."""

    name = "groq"


def build_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if s.llm_provider == "demo" or not s.llm_api_key:
        if s.llm_provider != "demo":
            log.warning("LLM_PROVIDER=%s but no LLM_API_KEY set; falling back to DEMO mode", s.llm_provider)
        return DemoProvider()
    if s.llm_provider == "groq":
        return GroqProvider(s.llm_api_key, s.llm_model or "openai/gpt-oss-120b",
                            s.llm_base_url or GROQ_OPENAI_BASE_URL, s.llm_timeout_seconds)
    if s.llm_provider == "gemini":
        return GeminiProvider(s.llm_api_key, s.llm_model or "gemini-2.0-flash",
                              s.llm_base_url or GEMINI_OPENAI_BASE_URL, s.llm_timeout_seconds)
    return OpenAICompatibleProvider(s.llm_api_key, s.llm_model or "gpt-4o-mini", s.llm_base_url,
                                    s.llm_timeout_seconds)
