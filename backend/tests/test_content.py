"""Content integrity, one test case per challenge.

The script form (`python -m scripts.validate_content`) reports 1,080 challenges
as a single pass or fail. Here each challenge is its own case, so a content
author can run just theirs:

    pytest tests/test_content.py -k apt-pct-001
    pytest tests/test_content.py -k aptitude
    pytest tests/test_content.py              # all of them

The checks themselves are not reimplemented - they are the same
`app.governance.validate` and `scripts.validate_content.lint` the script uses,
so the two can never disagree about what valid content is.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest
from pydantic import ValidationError

from app.config import settings
from app.engine.contracts import Challenge
from app.engine.registry import has_deterministic_validator
from app.governance import validate as validate_challenge
from app.subjects.catalog import SUBJECTS
from scripts.validate_content import lint


def _load_all() -> list[tuple[str, str, dict]]:
    """Every challenge entry as (subject_dir, label, raw_dict).

    Collected at import time so pytest can name one case per challenge.
    """
    entries: list[tuple[str, str, dict]] = []
    for path in sorted(settings.content_dir.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Surface as a case rather than breaking collection for everything.
            entries.append((path.parent.name, f"{path.name}-UNPARSEABLE", {"__error__": str(exc)}))
            continue
        for position, entry in enumerate(raw, 1):
            label = entry.get("id") or f"{path.name}#{position}"
            entries.append((path.parent.name, label, entry))
    return entries


ALL_ENTRIES = _load_all()

assert ALL_ENTRIES, "no content found - check settings.content_dir"


@pytest.mark.parametrize(
    "subject,label,entry",
    ALL_ENTRIES,
    ids=[f"{subject}/{label}" for subject, label, _ in ALL_ENTRIES],
)
def test_challenge_is_valid(subject: str, label: str, entry: dict) -> None:
    """Schema parses, and every governance validator passes."""
    if "__error__" in entry:
        pytest.fail(f"{label} is not parseable JSON: {entry['__error__']}")

    try:
        challenge = Challenge.model_validate(entry)
    except ValidationError as exc:
        pytest.fail(f"{label} failed schema validation:\n{exc}")

    problems = [f"{r.validator}: {r.detail}" for r in validate_challenge(challenge) if not r.passed]
    assert not problems, f"{label} failed validation:\n  " + "\n  ".join(problems)


def test_challenge_ids_are_unique() -> None:
    """An id collision silently shadows content, so it is its own check."""
    counts = Counter(label for _, label, _ in ALL_ENTRIES)
    duplicates = {label: n for label, n in counts.items() if n > 1}
    assert not duplicates, f"ids used more than once: {duplicates}"


def test_subject_tier_labels_match_the_validator_registry() -> None:
    """`tier` is display-only, so a wrong label breaks nothing at runtime - it
    just misreports how rigorously a subject is checked. Catch it here."""
    mismatches = [
        f"{config.key}: catalog says tier {config.tier}, "
        f"registry says {'A' if has_deterministic_validator(config.key) else 'B'}"
        for config in SUBJECTS
        if (config.tier == "A") != has_deterministic_validator(config.key)
    ]
    assert not mismatches, "tier labels disagree with the registry:\n  " + "\n  ".join(mismatches)


def test_truth_mix_is_near_target() -> None:
    """PRD v0.2 3.2 sets the launch mix. Drifting far from it changes what the
    product teaches - too few valid artifacts teaches blind skepticism."""
    states: Counter[str] = Counter()
    for _, _, entry in ALL_ENTRIES:
        if "__error__" not in entry:
            states[entry.get("truth_state", "unknown")] += 1

    total = sum(states.values())
    valid_share = states["valid"] / total
    insufficient_share = states["insufficient_information"] / total

    # Generous bands: this guards against collapse, not against normal drift.
    assert 0.18 <= valid_share <= 0.34, (
        f"valid share {valid_share:.0%} is outside 18-34% "
        f"(target {settings.valid_artifact_ratio:.0%}); mix={dict(states)}"
    )
    assert 0.02 <= insufficient_share <= 0.12, (
        f"insufficient share {insufficient_share:.0%} is outside 2-12% "
        f"(target {settings.insufficient_information_ratio:.0%}); mix={dict(states)}"
    )


@pytest.mark.lint
@pytest.mark.parametrize(
    "subject,label,entry",
    ALL_ENTRIES,
    ids=[f"{subject}/{label}" for subject, label, _ in ALL_ENTRIES],
)
def test_challenge_has_no_authoring_warnings(subject: str, label: str, entry: dict) -> None:
    """Style and authoring lint. Separate from validity so a warning never
    blocks a merge on its own - run with `-m ""` or deselect to skip."""
    if "__error__" in entry:
        pytest.skip("unparseable; covered by test_challenge_is_valid")
    try:
        challenge = Challenge.model_validate(entry)
    except ValidationError:
        pytest.skip("invalid schema; covered by test_challenge_is_valid")

    warnings = lint(challenge)
    assert not warnings, f"{label} authoring warnings:\n  " + "\n  ".join(warnings)
