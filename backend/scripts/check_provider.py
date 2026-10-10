"""Verify the configured AI provider before spending money on generation.

Run this first after setting a key. It checks, in order: credentials resolve,
the configured models exist, a plain-text call works, and - the one that
actually matters - structured output round-trips into a validated contract.

    python -m scripts.check_provider              # test the active provider
    python -m scripts.check_provider --list       # list OpenRouter models
    python -m scripts.check_provider --list anthropic/   # filter the list
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from pydantic import BaseModel, Field

from app.agents.client import (
    AgentError,
    active_provider,
    drain_run_log,
    provider_status,
    structured,
    text_reply,
)
from app.agents.providers.base import strict_schema
from app.config import settings


class _Probe(BaseModel):
    """A small contract shaped like the real ones: nesting, enums, lists."""

    answer: int = Field(description="The numeric answer")
    reasoning: str = Field(description="One sentence of justification")
    confident: bool
    steps: list[str] = Field(description="Two short steps")


def list_models(prefix: str) -> int:
    url = f"{settings.openrouter_base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read())
    except Exception as exc:
        print(f"could not reach {url}: {exc}")
        return 1

    models = data.get("data", [])
    rows = [m for m in models if m["id"].startswith(prefix)] if prefix else models
    rows.sort(key=lambda m: m["id"])
    print(f"{len(rows)} model(s)" + (f" matching {prefix!r}" if prefix else ""))
    print()
    print(f"{'model id':<48} {'ctx':>9}  {'in $/M':>8} {'out $/M':>8}  structured")
    print("-" * 92)
    for m in rows[:80]:
        pricing = m.get("pricing") or {}
        try:
            pin = float(pricing.get("prompt") or 0) * 1_000_000
            pout = float(pricing.get("completion") or 0) * 1_000_000
        except (TypeError, ValueError):
            pin = pout = 0.0
        supported = m.get("supported_parameters") or []
        print(
            f"{m['id']:<48} {m.get('context_length') or 0:>9,}  "
            f"{pin:>8.2f} {pout:>8.2f}  "
            f"{'yes' if 'structured_outputs' in supported else 'no'}"
        )
    if len(rows) > 80:
        print(f"... and {len(rows) - 80} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the AI provider setup")
    parser.add_argument(
        "--list",
        nargs="?",
        const="",
        default=None,
        metavar="PREFIX",
        help="List OpenRouter models, optionally filtered by prefix",
    )
    args = parser.parse_args()

    if args.list is not None:
        return list_models(args.list)

    print("[1] provider resolution")
    status = provider_status()
    if not status["configured"]:
        print("    FAIL: no AI provider configured.")
        print()
        print("    Add ONE of these to backend/.env, then re-run:")
        print("      BREAKPOINT_OPENROUTER_API_KEY=sk-or-v1-...")
        print("      ANTHROPIC_API_KEY=sk-ant-...")
        if status["error"]:
            print(f"    ({status['error']})")
        return 2

    provider = active_provider()
    assert provider is not None
    print(f"    ok   provider: {status['provider']}")
    for role, model in status["models"].items():
        print(f"         {role:<11} -> {model}")

    print("\n[2] schema compatibility")
    schema = strict_schema(_Probe)
    print(f"    ok   probe schema built ({len(schema.get('properties', {}))} fields)")

    print("\n[3] plain-text call")
    try:
        reply = text_reply(
            agent="check",
            role="debate",
            system="You are terse. Reply with exactly the word: READY",
            messages=[{"role": "user", "content": "Say READY."}],
            max_tokens=200,
        )
    except AgentError as exc:
        print(f"    FAIL: {exc}")
        _report_usage()
        return 1
    print(f"    ok   reply: {reply[:60]!r}")

    print("\n[4] structured output (the one that matters)")
    try:
        probe = structured(
            agent="check",
            role="critic",
            system=(
                "You verify arithmetic. Answer strictly in the requested schema."
            ),
            prompt=(
                "A price of 1000 is decreased by 20%, then the result is "
                "increased by 20%. What is the final price? Give two steps."
            ),
            output_format=_Probe,
            max_tokens=2000,
            effort="low",
        )
    except AgentError as exc:
        print(f"    FAIL: {exc}")
        _report_usage()
        return 1

    print(f"    ok   parsed into {type(probe).__name__}")
    print(f"         answer={probe.answer} confident={probe.confident}")
    print(f"         steps={len(probe.steps)}")
    if probe.answer == 960:
        print("    ok   model got the reverse-percentage question right")
    else:
        print(
            f"    note model answered {probe.answer}, not 960 - structured output "
            "works, but consider a stronger model for generation"
        )

    _report_usage()
    print("\nProvider is ready. Generate content with:")
    print(
        "    python -m scripts.generate --topic 'Ratio, Proportion & Mixtures' "
        "--concept 'Ratio and proportion' --count 3"
    )
    return 0


def _report_usage() -> None:
    runs = drain_run_log()
    if not runs:
        return
    print("\n[usage]")
    for r in runs:
        state = "ok" if r.ok else "FAILED"
        print(
            f"    {r.agent:<6} {r.model:<34} {r.input_tokens:>6} in "
            f"{r.output_tokens:>6} out  {r.latency_ms:>6}ms  {state}"
        )
        if r.error:
            print(f"           {r.error[:150]}")


if __name__ == "__main__":
    sys.exit(main())
