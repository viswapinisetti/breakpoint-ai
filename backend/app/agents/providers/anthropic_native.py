"""Anthropic provider using the native Messages API (PRD section 73).

Preferred when an Anthropic credential is available, because it offers things
the OpenAI-compatible surface cannot: adaptive thinking, explicit prompt-cache
breakpoints, and server-side refusal fallbacks - which matter here because
Breakpoint deliberately asks a model to produce incorrect content and to argue
against a student.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.providers.base import (
    AgentError,
    Provider,
    RefusedError,
    Reply,
    Usage,
)
from app.config import settings

T = TypeVar("T", bound=BaseModel)

# Scalar-form server-side fallbacks: routes by refusal category, so no model
# list has to be maintained here.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self) -> None:
        self._client: Any = None

    def is_configured(self) -> bool:
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get(
            "ANTHROPIC_AUTH_TOKEN"
        ):
            return True
        if settings.anthropic_api_key:
            return True
        return (Path.home() / ".config" / "anthropic").exists()

    def model_for(self, role: str) -> str:
        return {
            "generation": settings.generation_model,
            "critic": settings.critic_model,
            "debate": settings.debate_model,
            "evidence": settings.evidence_model,
        }.get(role, settings.generation_model)

    def _get(self) -> Any:
        if self._client is None:
            if not self.is_configured():
                raise AgentError(
                    "no Anthropic credential configured; set ANTHROPIC_API_KEY "
                    "or run `ant auth login`"
                )
            import anthropic

            kwargs: dict[str, Any] = {"max_retries": 3}
            if settings.anthropic_api_key:
                kwargs["api_key"] = settings.anthropic_api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    @staticmethod
    def _usage(response: Any) -> Usage:
        u = response.usage
        return Usage(
            model=response.model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        )

    @staticmethod
    def _guard_refusal(response: Any) -> None:
        """The whole fallback chain declining returns HTTP 200 with no output."""
        if response.stop_reason == "refusal":
            category = getattr(
                getattr(response, "stop_details", None), "category", None
            )
            raise RefusedError(f"request declined (category={category})")

    def structured(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        output_format: type[T],
        max_tokens: int,
        effort: str,
    ) -> Reply:
        import anthropic

        try:
            response = self._get().beta.messages.parse(
                model=model,
                max_tokens=max_tokens,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
                output_format=output_format,
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AgentError(f"Anthropic: {exc}") from exc

        self._guard_refusal(response)
        parsed = response.parsed_output
        if parsed is None:
            raise AgentError("Anthropic returned no parseable structured output")
        return Reply(parsed=parsed, usage=self._usage(response))

    def text(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        effort: str,
        timeout: float | None = None,
    ) -> Reply:
        import anthropic

        extra: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}
        try:
            response = self._get().beta.messages.create(
                **extra,
                model=model,
                max_tokens=max_tokens,
                betas=[_FALLBACK_BETA],
                fallbacks="default",
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            raise AgentError(f"Anthropic: {exc}") from exc

        self._guard_refusal(response)
        text = "".join(
            b.text for b in response.content if b.type == "text"
        ).strip()
        return Reply(text=text, usage=self._usage(response))
