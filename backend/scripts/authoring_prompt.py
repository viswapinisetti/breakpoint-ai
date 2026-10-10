"""Refresh the generated sections of the ChatGPT authoring prompts.

    python -m scripts.authoring_prompt           # rewrite the sections
    python -m scripts.authoring_prompt --check   # exit 1 if they are stale

The prompts in docs/content-authoring/ are prose written by hand, with three
sections generated from the code: the subject/topic registry (with each
subject's allowed artifact types, failure categories and evidence types), the
failure taxonomy, and worked examples taken from real published content.

Generating them means a model is never told a topic name, an evidence type or
a field shape that the validator would then reject. Run this after changing
the topic registry, the catalog or an example challenge.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.config import BASE_DIR, settings
from app.engine.contracts import Challenge, ChallengeMode
from app.engine.taxonomy import LABELS
from app.subjects.catalog import BY_KEY as CONFIG
from app.subjects.topics import REGISTRY

DOCS = BASE_DIR.parent / "docs" / "content-authoring"
MAIN = DOCS / "CHATGPT_PROMPT.md"
ADVANCED = DOCS / "CHATGPT_PROMPT_ADVANCED_MODES.md"

# What the machine checks, per subject - mirrors engine/registry.py.
CHECKS = {
    "aptitude": "solver **required** (section 7)",
    "mathematics": "solver for numeric answers (section 7)",
    "data-analytics": "solver for numeric answers (section 7)",
    "programming": "runnable code check for Python items (section 7)",
    "dsa": "runnable code check for Python items (section 7)",
}

# (id, why it is shown). Chosen to cover each truth state and each kind of
# machine check a trust-or-challenge item can carry.
EXAMPLES = [
    ("apt-pct-001", "Aptitude, flawed: solver + flawed_solver, evidence numbers, transfer check"),
    ("apt-qr-044", "Aptitude, valid: the AI is right; hints lead to confirming it"),
    ("apt-ins-012", "Aptitude, insufficient information: an invented figure, two readings that disagree"),
    ("eng-agr-001", "English, flawed: a text-only subject with no machine check, validation_payload {}"),
    ("prg-max-001", "Programming, flawed: runnable ai_code vs reference_code, executed on test inputs"),
]
ADVANCED_EXAMPLES = [
    ("apt-wg-001", "Which AI Is Wrong: verdict b_correct, three solvers"),
    ("prg-bt-001", "Break the Tests: a green suite with an untested input class"),
]

# Computed on load, never authored.
COMPUTED = {"validators", "quality_score"}
MODE_ONLY = {"competing", "comparison", "test_gap"}


def _challenges() -> dict[str, Challenge]:
    found: dict[str, Challenge] = {}
    for path in sorted(settings.content_dir.rglob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            found[entry["id"]] = Challenge.model_validate(entry)
    return found


def _example_json(challenge: Challenge) -> str:
    """The challenge as an author should write it: every field present."""
    exclude = set(COMPUTED)
    if challenge.challenge_mode == ChallengeMode.TRUST_OR_CHALLENGE:
        exclude |= MODE_ONLY
    body = challenge.model_dump(mode="json", exclude=exclude)
    return json.dumps(body, indent=2, ensure_ascii=False)


def registry_section() -> str:
    lines: list[str] = []
    for subject in REGISTRY:
        config = CONFIG[subject.key]
        lines += [
            f"### {subject.number}. {subject.name}",
            "",
            f"- subject key: `{subject.key}` | id prefix: `{subject.id_prefix}` | "
            f"machine check: {CHECKS.get(subject.key, 'structure only (facts are not machine-checked)')}",
            "- artifact_type: " + ", ".join(f"`{a}`" for a in config.artifact_types),
            "- failure categories: " + ", ".join(config.failure_categories),
            "- evidence types: " + ", ".join(f"`{e.value}`" for e in config.evidence_types),
            "",
            "| # | Topic name (copy exactly) | Topic key (for ids) |",
            "|---|---|---|",
        ]
        lines += [f"| {t.number} | {t.name} | `{t.key}` |" for t in subject.topics]
        lines.append("")
    return "\n".join(lines)


def taxonomy_section() -> str:
    lines = ["| Code | Category |", "|---|---|"]
    lines += [f"| {code.value} | {label} |" for code, label in LABELS.items()]
    return "\n".join(lines) + "\n"


def examples_section(picks: list[tuple[str, str]], challenges: dict[str, Challenge]) -> str:
    blocks: list[str] = []
    for n, (challenge_id, why) in enumerate(picks, 1):
        if challenge_id not in challenges:
            raise SystemExit(f"example {challenge_id} is not in the content files")
        blocks += [
            f"### Example {n}: {why}",
            "",
            "```json",
            _example_json(challenges[challenge_id]),
            "```",
            "",
        ]
    return "\n".join(blocks)


def _fill(text: str, name: str, body: str) -> str:
    pattern = re.compile(
        rf"(<!-- BEGIN GENERATED: {re.escape(name)} [^\n]*-->\n)(.*?)(<!-- END GENERATED: {re.escape(name)} -->)",
        re.DOTALL,
    )
    if not pattern.search(text):
        raise SystemExit(f"marker for {name!r} not found")
    return pattern.sub(lambda m: m.group(1) + body + m.group(3), text)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    challenges = _challenges()
    outputs = {
        MAIN: {
            "registry": registry_section(),
            "taxonomy": taxonomy_section(),
            "examples": examples_section(EXAMPLES, challenges),
        },
        ADVANCED: {
            "advanced-examples": examples_section(ADVANCED_EXAMPLES, challenges),
        },
    }

    stale = []
    for path, sections in outputs.items():
        current = path.read_text(encoding="utf-8")
        rendered = current
        for name, body in sections.items():
            rendered = _fill(rendered, name, body)
        if rendered != current:
            stale.append(path)
            if not check:
                path.write_text(rendered, encoding="utf-8")

    rel = [str(p.relative_to(BASE_DIR.parent)) for p in stale]
    if check:
        if stale:
            print("stale - run `python -m scripts.authoring_prompt`:", ", ".join(rel))
            return 1
        print("authoring prompts are up to date")
        return 0
    print("updated: " + ", ".join(rel) if rel else "already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
