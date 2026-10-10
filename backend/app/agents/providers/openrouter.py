"""OpenRouter provider (PRD section 73).

OpenRouter exposes an OpenAI-compatible Chat Completions API in front of many
vendors, so one key reaches Claude, GPT, Gemini, Llama and others. That maps
well onto Breakpoint's model-agnostic requirement, and it is the right client
to use here: OpenRouter speaks the OpenAI wire format, not the Anthropic one.

Worth knowing when routing to a Claude model this way: you get the model, but
not the Anthropic-native controls - adaptive thinking, server-side refusal
fallbacks and explicit prompt-cache breakpoints are Messages API features and
do not cross the OpenAI-compatible surface. `effort` is therefore mapped onto
`reasoning`, which OpenRouter forwards to providers that support it and
ignores elsewhere.

Structured output is requested as strict `json_schema` and degrades in two
steps rather than failing the run, because support varies per model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.providers.base import (
    AgentError,
    Provider,
    RefusedError,
    Reply,
    Usage,
    extract_json,
    strict_schema,
)
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# OpenRouter forwards `reasoning.effort` to models that support it.
_EFFORT_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(self) -> None:
        self._client: Any = None

    # --- setup ------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(settings.openrouter_api_key)

    def model_for(self, role: str) -> str:
        return {
            "generation": settings.openrouter_generation_model,
            "critic": settings.openrouter_critic_model,
            "debate": settings.openrouter_debate_model,
            "evidence": settings.openrouter_evidence_model,
        }.get(role, settings.openrouter_generation_model)

    def _get(self) -> Any:
        if self._client is None:
            if not self.is_configured():
                raise AgentError(
                    "no OpenRouter credential configured; set "
                    "BREAKPOINT_OPENROUTER_API_KEY in backend/.env"
                )
            from openai import OpenAI

            self._client = OpenAI(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
                max_retries=3,
                timeout=180.0,
                # OpenRouter uses these for app attribution on its dashboard.
                default_headers={
                    "HTTP-Referer": settings.openrouter_site_url,
                    "X-Title": settings.openrouter_app_name,
                },
            )
        return self._client

    # --- calls ------------------------------------------------------------

    def _complete(self, **kwargs: Any) -> Any:
        """One chat completion, with vendor errors mapped to AgentError."""
        import openai

        try:
            return self._get().chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            # Surfaced to callers so the structured() fallback ladder can act.
            raise _UnsupportedRequest(str(exc)) from exc
        except openai.APIStatusError as exc:
            raise AgentError(f"OpenRouter {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise AgentError(f"OpenRouter connection error: {exc}") from exc

    @staticmethod
    def _usage(response: Any, model: str) -> Usage:
        u = getattr(response, "usage", None)
        details = getattr(u, "prompt_tokens_details", None) if u else None
        return Usage(
            model=getattr(response, "model", model) or model,
            input_tokens=getattr(u, "prompt_tokens", 0) or 0 if u else 0,
            output_tokens=getattr(u, "completion_tokens", 0) or 0 if u else 0,
            cache_read_tokens=getattr(details, "cached_tokens", 0) or 0
            if details
            else 0,
        )

    @staticmethod
    def _content(response: Any) -> str:
        if not getattr(response, "choices", None):
            raise AgentError("OpenRouter returned no choices")
        choice = response.choices[0]
        # A content filter or provider refusal shows up as an empty message
        # with a finish reason, not an exception.
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            raise RefusedError(f"model declined: {refusal}")
        if choice.finish_reason == "content_filter":
            raise RefusedError("request blocked by a content filter")
        return choice.message.content or ""

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
        """Request JSON matching `output_format`, degrading gracefully.

        Three attempts, in order of fidelity:
          1. strict `json_schema` - the provider enforces the shape;
          2. `json_object` with the schema inlined in the prompt;
          3. plain text with a JSON-only instruction.

        Support for 1 and 2 varies by model, and a run that dies because a
        model does not implement a response_format flavour is a bad outcome
        when the model can plainly produce the JSON.
        """
        schema = strict_schema(output_format)
        base: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        mapped = _EFFORT_MAP.get(effort)
        if mapped:
            base["extra_body"] = {"reasoning": {"effort": mapped}}

        schema_text = json.dumps(schema, indent=2)
        attempts: list[tuple[str, dict[str, Any]]] = [
            (
                "json_schema",
                {
                    **base,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": output_format.__name__.lower(),
                            "strict": True,
                            "schema": schema,
                        },
                    },
                },
            ),
            (
                "json_object",
                {
                    **base,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": (
                                f"{prompt}\n\nRespond with a single JSON object "
                                f"matching this schema exactly:\n{schema_text}"
                            ),
                        },
                    ],
                },
            ),
            (
                "plain",
                {
                    **base,
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": (
                                f"{prompt}\n\nRespond with ONLY a single JSON "
                                f"object matching this schema. No prose, no "
                                f"markdown fences.\n{schema_text}"
                            ),
                        },
                    ],
                },
            ),
        ]

        last_error: Exception | None = None
        for mode, kwargs in attempts:
            try:
                response = self._complete(**kwargs)
            except _UnsupportedRequest as exc:
                logger.info("openrouter: %s mode rejected by %s, degrading", mode, model)
                last_error = exc
                continue

            raw = self._content(response)
            usage = self._usage(response, model)
            try:
                parsed = output_format.model_validate_json(extract_json(raw))
            except (ValidationError, ValueError) as exc:
                logger.warning(
                    "openrouter: %s mode returned unparseable output from %s",
                    mode,
                    model,
                )
                last_error = exc
                continue
            return Reply(text=raw, parsed=parsed, usage=usage)

        raise AgentError(
            f"OpenRouter could not produce valid {output_format.__name__} from "
            f"{model}: {last_error}"
        )

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        mapped = _EFFORT_MAP.get(effort)
        if mapped:
            kwargs["extra_body"] = {"reasoning": {"effort": mapped}}
        try:
            response = self._complete(**kwargs)
        except _UnsupportedRequest as exc:
            raise AgentError(f"OpenRouter rejected the request: {exc}") from exc
        return Reply(
            text=self._content(response).strip(),
            usage=self._usage(response, model),
        )


class _UnsupportedRequest(AgentError):
    """A 400 that usually means this model does not support a request feature."""
