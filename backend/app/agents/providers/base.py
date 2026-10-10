"""Provider contract for the AI Gateway (PRD section 73).

The product must not depend on one model vendor. Every provider implements the
same two calls, so agents are written once and the vendor is a setting:

    structured(...) -> a validated Pydantic model   (PRD section 74)
    text(...)       -> a plain string                (debate, debrief)

Anything vendor-specific - auth, request shape, schema dialect, error mapping -
belongs behind this interface, never in an agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AgentError(RuntimeError):
    """A model call failed in a way the pipeline must handle explicitly."""


class RefusedError(AgentError):
    """The model declined the request."""


@dataclass
class Usage:
    """Token accounting for one call, normalised across providers."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class Reply:
    """A provider response: the payload plus what it cost."""

    text: str = ""
    parsed: Any = None
    usage: Usage = field(default_factory=Usage)


class Provider(Protocol):
    """What every AI provider must implement."""

    name: str

    def is_configured(self) -> bool:
        """Whether a usable credential is present."""
        ...

    def model_for(self, role: str) -> str:
        """Resolve the model id for an agent role (generation, critic, ...)."""
        ...

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
        """Return a response whose `parsed` is a validated `output_format`."""
        ...

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
        """Return a plain-text response.

        `timeout` overrides the client default for this call only - for long
        offline generations that legitimately outlast an interactive request.
        """
        ...


# --- JSON Schema helpers ---------------------------------------------------


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Build a JSON Schema that strict structured-output modes will accept.

    Pydantic emits idiomatic JSON Schema, but strict modes (OpenAI-compatible
    `json_schema` with `strict: true`, which is what OpenRouter forwards)
    impose extra rules:

    * every object must set `additionalProperties: false`;
    * every property must appear in `required` - optional fields are expressed
      by allowing null in the type, not by omission;
    * `$defs` references must be walked, since our contracts nest models.

    Fields with defaults are still listed as required. The model is told to
    emit them, and Pydantic re-applies defaults on validation anyway, so
    nothing is lost and the provider stops rejecting the schema.
    """
    schema = model.model_json_schema()
    _tighten(schema, schema.get("$defs", {}))
    return schema


def _tighten(node: Any, defs: dict[str, Any], seen: set[int] | None = None) -> None:
    """Recursively apply strict-mode rules in place."""
    if seen is None:
        seen = set()
    if id(node) in seen:
        return
    if isinstance(node, dict):
        seen.add(id(node))
        if node.get("type") == "object" or "properties" in node:
            node.setdefault("additionalProperties", False)
            props = node.get("properties")
            if isinstance(props, dict) and props:
                node["required"] = list(props.keys())
        for key, value in node.items():
            if key == "$defs":
                continue
            _tighten(value, defs, seen)
        for value in defs.values():
            _tighten(value, defs, seen)
    elif isinstance(node, list):
        for item in node:
            _tighten(item, defs, seen)


def extract_json(text: str) -> str:
    """Pull a JSON object out of a model response.

    Models routed through a gateway sometimes wrap JSON in markdown fences or
    add a sentence before it, even when asked not to. Rather than fail the
    whole generation on formatting, recover the object.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[: -3].rstrip()
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip()
    if cleaned.startswith("{"):
        return cleaned
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned
