"""Offline challenge generation CLI (PRD sections 47, 56, 57).

This is the Challenge Studio's engine. It runs the full quality pipeline and
writes only survivors to a content file for human review - nothing here
publishes directly to students.

    python -m scripts.generate --topic "Percentages, Profit/Loss & Discounts" \
        --concept "Successive percentage change" --count 5

    python -m scripts.generate --concept "Averages" --correct   # false-failure

Costs real money: each candidate makes four model calls (compose, inject,
critique, quality). Use --dry-run to see the plan first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.agents.client import (
    AgentError,
    drain_run_log,
    is_configured,
    provider_status,
)
from app.config import settings
from app.engine.contracts import ChallengeMode
from app.pipeline import run_pipeline
from app.subjects import topics as topic_registry

# The failure types the injector is asked for, cycled across a batch so one
# run produces variety rather than five copies of the same trap.
FAILURE_ROTATION = [
    "hidden assumption",
    "wrong shortcut",
    "calculation trap",
    "interpretation trap",
    "rule misapplication",
]


def main() -> int:
    # Generation can run for minutes per candidate. Block-buffered stdout makes
    # a piped or redirected run look frozen, so force line buffering.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:  # pragma: no cover - very old streams
        pass

    parser = argparse.ArgumentParser(description="Generate Breakpoint challenges")
    parser.add_argument("--subject", default="aptitude")
    parser.add_argument(
        "--topic",
        default=None,
        help="A topic registered for the subject (app/subjects/topics.py). "
        "Defaults to the subject's first topic.",
    )
    parser.add_argument("--concept", required=True)
    parser.add_argument("--difficulty", default="3", choices=list("12345"))
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument(
        "--correct",
        action="store_true",
        help="Generate false-failure challenges where the AI is actually right",
    )
    parser.add_argument("--failure", default=None, help="Force one failure type")
    parser.add_argument("--out", default=None, help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Checked before anything is spent: a candidate under an unregistered
    # topic would pay for four model calls and then fail validation.
    try:
        registered = topic_registry.subject(args.subject)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.topic is None:
        args.topic = registered.topics[0].name
    check = topic_registry.validate_topic(args.subject, args.topic)
    if not check.passed:
        print(check.detail, file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"Would generate {args.count} candidate(s):")
        print(f"  subject={args.subject} topic={args.topic} concept={args.concept}")
        print(f"  difficulty={args.difficulty} correct_artifact={args.correct}")
        status = provider_status()
        target = (
            status["models"]["generation"]
            if status["configured"]
            else "(no provider configured)"
        )
        print(f"  ~{args.count * 4} model calls via {status['provider']} -> {target}")
        return 0

    if not is_configured():
        print(
            "No AI provider configured. Set BREAKPOINT_OPENROUTER_API_KEY (or "
            "ANTHROPIC_API_KEY) in backend/.env, then verify with:\n"
            "    python -m scripts.check_provider",
            file=sys.stderr,
        )
        return 2

    status = provider_status()
    print(f"provider: {status['provider']}  models: {status['models']}")

    out_path = Path(
        args.out
        or settings.content_dir
        / args.subject
        / f"{args.concept.lower().replace(' ', '-')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    published: list[dict] = []
    rejected = 0

    for i in range(args.count):
        failure = args.failure or FAILURE_ROTATION[i % len(FAILURE_ROTATION)]
        label = "correct artifact" if args.correct else failure
        print(f"\n[{i + 1}/{args.count}] generating ({label})…", flush=True)
        try:
            outcome = run_pipeline(
                subject=args.subject,
                topic=args.topic,
                concept=args.concept,
                difficulty=args.difficulty,
                desired_failure=failure,
                mode=ChallengeMode.TRUST_OR_CHALLENGE,
                make_correct=args.correct,
            )
        except AgentError as exc:
            print(f"  ERROR {exc}")
            rejected += 1
            continue

        if outcome.published and outcome.challenge:
            q = outcome.challenge.quality_score
            print(f"  PUBLISHED {outcome.challenge.id}  quality {q:.2f}/10")
            published.append(outcome.challenge.model_dump(mode="json"))
        else:
            rejected += 1
            print(f"  REJECTED at stage '{outcome.stage}'")
            for reason in outcome.reasons:
                print(f"    - {reason}")

    # Report the funnel the way PRD section 57 describes it.
    print(f"\nfunnel: {args.count} generated -> {len(published)} survived, {rejected} rejected")

    runs = drain_run_log()
    if runs:
        tokens_in = sum(r.input_tokens for r in runs)
        tokens_out = sum(r.output_tokens for r in runs)
        cached = sum(r.cache_read_tokens for r in runs)
        failed = sum(1 for r in runs if not r.ok)
        print(
            f"model usage: {len(runs)} calls ({failed} failed), {tokens_in} in "
            f"({cached} cached) / {tokens_out} out"
        )

    if published:
        existing = []
        if out_path.exists():
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        out_path.write_text(
            json.dumps(existing + published, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {len(published)} challenge(s) to {out_path}")
        print(
            "\nNext: review them, then run "
            "`python -m scripts.validate_content` and restart the API to publish."
        )
    else:
        print("nothing survived the pipeline; no file written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
