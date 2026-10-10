"""AI Gateway (PRD section 73).

Every model call in Breakpoint goes through here. That is what keeps the
product model-agnostic: agents ask for a *role* ("critic", "debate") and the
gateway resolves the provider and model id from settings. Swapping vendors -
or running Claude through OpenRouter instead of the Anthropic API - changes
configuration, not agent code.

Two behaviours matter for this product specifically:

* **Structured output everywhere** (PRD section 74). Agents receive validated
  Pydantic models, never parsed prose. A malformed generation is a caught
  exception, not a corrupt challenge.
* **Refusals are handled, not assumed away.** Breakpoint deliberately asks a
  model to produce *incorrect* content and to argue against a student, and some
  subjects (prompt injection, security) sit near policy boundaries.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.providers.anthropic_native import AnthropicProvider
from app.agents.providers.base import AgentError, Provider, RefusedError
from app.agents.providers.openrouter import OpenRouterProvider
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Re-exported so callers keep importing errors from the gateway.
__all__ = [
    "AgentError",
    "RefusedError",
    "RunLog",
    "active_provider",
    "drain_run_log",
    "is_configured",
    "provider_status",
    "structured",
    "text_reply",
]

_PROVIDERS: dict[str, Provider] = {
    "openrouter": OpenRouterProvider(),
    "anthropic": AnthropicProvider(),
}

# Preference order when `ai_provider` is "auto". OpenRouter first because a
# key present in config is an explicit choice, whereas an Anthropic profile on
# disk may just be left over from another project.
_AUTO_ORDER = ("openrouter", "anthropic")


def active_provider() -> Provider | None:
    """The provider that will serve calls, or None if nothing is configured."""
    choice = settings.ai_provider.strip().lower()
    if choice and choice != "auto":
        provider = _PROVIDERS.get(choice)
        if provider is None:
            raise AgentError(
                f"unknown ai_provider {choice!r}; expected one of "
                f"{sorted(_PROVIDERS)} or 'auto'"
            )
        return provider if provider.is_configured() else None
    for key in _AUTO_ORDER:
        provider = _PROVIDERS[key]
        if provider.is_configured():
            return provider
    return None


def _require_provider() -> Provider:
    provider = active_provider()
    if provider is None:
        raise AgentError(
            "no AI provider configured. Set BREAKPOINT_OPENROUTER_API_KEY (or "
            "ANTHROPIC_API_KEY) in backend/.env and restart the API."
        )
    return provider


def is_configured() -> bool:
    """Whether live model calls are possible.

    The student experience runs entirely on pre-generated content, so the app
    must boot and serve challenges with no credential (PRD section 106).
    """
    try:
        return active_provider() is not None
    except AgentError:
        return False


def provider_status() -> dict[str, Any]:
    """Diagnostics for the health endpoint and the Studio."""
    try:
        provider = active_provider()
    except AgentError as exc:
        return {"configured": False, "provider": None, "error": str(exc)}
    if provider is None:
        return {"configured": False, "provider": None, "error": ""}
    return {
        "configured": True,
        "provider": provider.name,
        "error": "",
        "models": {
            role: provider.model_for(role)
            for role in ("generation", "critic", "debate", "evidence")
        },
    }


class RunLog(BaseModel):
    """Telemetry for one model call, persisted as a ModelRun row."""

    agent: str
    model: str
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str = ""


_run_log: list[RunLog] = []


def drain_run_log() -> list[RunLog]:
    """Return and clear buffered telemetry."""
    global _run_log
    runs, _run_log = _run_log, []
    return runs


def _record(log: RunLog) -> None:
    _run_log.append(log)
    logger.debug(
        "agent=%s provider=%s model=%s in=%d out=%d %dms ok=%s",
        log.agent,
        log.provider,
        log.model,
        log.input_tokens,
        log.output_tokens,
        log.latency_ms,
        log.ok,
    )


def _resolve(model: str | None, role: str, provider: Provider) -> str:
    """A caller may pass an explicit model, otherwise the role default wins."""
    return model or provider.model_for(role)


def structured(
    *,
    agent: str,
    role: str = "generation",
    model: str | None = None,
    system: str,
    prompt: str,
    output_format: type[T],
    max_tokens: int = 16000,
    effort: str = "high",
) -> T:
    """Run one structured-output call and return the validated model."""
    provider = _require_provider()
    resolved = _resolve(model, role, provider)
    started = time.perf_counter()
    try:
        reply = provider.structured(
            model=resolved,
            system=system,
            prompt=prompt,
            output_format=output_format,
            max_tokens=max_tokens,
            effort=effort,
        )
    except AgentError as exc:
        _record(
            RunLog(
                agent=agent,
                model=resolved,
                provider=provider.name,
                latency_ms=int((time.perf_counter() - started) * 1000),
                ok=False,
                error=str(exc)[:500],
            )
        )
        raise

    usage = reply.usage
    _record(
        RunLog(
            agent=agent,
            model=usage.model or resolved,
            provider=provider.name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    return reply.parsed  # type: ignore[return-value]


def text_reply(
    *,
    agent: str,
    role: str = "debate",
    model: str | None = None,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 2048,
    effort: str = "medium",
    timeout: float | None = None,
) -> str:
    """Run one plain-text call. Used by the Debate and Debrief agents, and by
    offline bulk authoring (which passes a long `timeout`)."""
    provider = _require_provider()
    resolved = _resolve(model, role, provider)
    started = time.perf_counter()
    try:
        reply = provider.text(
            model=resolved,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
            effort=effort,
            timeout=timeout,
        )
    except AgentError as exc:
        _record(
            RunLog(
                agent=agent,
                model=resolved,
                provider=provider.name,
                latency_ms=int((time.perf_counter() - started) * 1000),
                ok=False,
                error=str(exc)[:500],
            )
        )
        raise

    usage = reply.usage
    _record(
        RunLog(
            agent=agent,
            model=usage.model or resolved,
            provider=provider.name,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    )
    return reply.text
