"""Validate challenge content against the schema, the topic registry and each
subject's domain validator.

Run this in CI, and on every file you author before restarting the API:

    python -m scripts.validate_content                          # all content
    python -m scripts.validate_content content/aptitude/si-ci.json   # one file
    python -m scripts.validate_content drafts/                  # a folder

Content is data, so it must be checked like data - a challenge whose solver no
longer reproduces its stated answer is a defect, whether it was written by a
model or a person.

Two levels of finding:

* **FAIL** - the API would refuse or corrupt this challenge: invalid JSON, a
  schema error, a failing validator (so the seeder refuses it), or an id used
  twice (so one challenge silently overwrites the other). Exit code 1.
* **warn** - it would load, but work worse than it should: a malformed hint
  ladder, evidence the offline checker can never accept, a failure category
  outside the subject's taxonomy. Shown for the files you name; counted when
  checking everything. See docs/content-authoring/README.md.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.engine.arithmetic import parse_value
from app.engine.contracts import Challenge, ChallengeMode, TruthState
from app.engine.registry import has_deterministic_validator
from app.governance import validate as validate_challenge
from app.subjects import topics as topic_registry
from app.subjects.catalog import SUBJECTS
from app.subjects.catalog import BY_KEY as SUBJECT_CONFIG

HINT_KINDS = ["attention", "direction", "concept", "strong", "reveal"]
ID_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
NUMBER = re.compile(r"\d")
EXECUTABLE_SUBJECTS = {"programming", "dsa"}
SOLVER_SUBJECTS = {"aptitude", "mathematics", "data-analytics"}


# --- loading ---------------------------------------------------------------


def _targets(args: list[str]) -> list[Path]:
    """The files to check: every content file, or the paths given."""
    if not args:
        return sorted(settings.content_dir.rglob("*.json"))
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(arg)
    return files


def _raw_entries(path: Path) -> tuple[list[dict] | None, str]:
    """Parse one file. Returns (entries, error)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
    except UnicodeDecodeError:
        return None, "file is not UTF-8 encoded"
    if not isinstance(data, list):
        return None, "the file must contain a JSON array [ ... ] of challenges"
    bad = [i for i, e in enumerate(data, 1) if not isinstance(e, dict)]
    if bad:
        return None, f"entries {bad} are not JSON objects"
    return data, ""


def _schema_errors(exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "(challenge)"
        out.append(f"{where}: {err['msg']}")
    return out


# --- authoring warnings ------------------------------------------------------


def lint(ch: Challenge) -> list[str]:
    """Checks the validators do not make but authored content should pass."""
    warnings: list[str] = []
    config = SUBJECT_CONFIG.get(ch.subject)
    comparison = ch.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG

    if not ID_PATTERN.match(ch.id) or len(ch.id) > 64:
        warnings.append(
            "id should be lowercase words and digits joined by hyphens, at most 64 "
            "characters, e.g. apt-si-ci-001"
        )
    registered = topic_registry.BY_KEY.get(ch.subject)
    if registered and not ch.id.startswith(f"{registered.id_prefix}-"):
        warnings.append(f"{registered.name} ids start with '{registered.id_prefix}-'")
    if not ch.subtopic.strip():
        warnings.append("subtopic is empty; it is the item's title in the contents rail")
    elif len(ch.subtopic) > 60:
        warnings.append("subtopic is over 60 characters; it is shown as a short title")

    # Hint ladder: five rungs, in order, ending in the reveal.
    kinds = [h.kind for h in ch.hints]
    levels = [h.level for h in ch.hints]
    if kinds != HINT_KINDS or levels != [1, 2, 3, 4, 5]:
        warnings.append(
            f"hints should be exactly 5, levels 1-5, kinds {HINT_KINDS}; got {list(zip(levels, kinds))}"
        )

    # Reasoning steps.
    step_lists = [c.ai_solution for c in ch.competing] if comparison else [ch.ai_solution]
    for steps in step_lists:
        indices = [s.index for s in steps]
        if indices != list(range(1, len(indices) + 1)):
            warnings.append(f"step indices should run 1, 2, 3 ... in order; got {indices}")
        if len(steps) < 2:
            warnings.append("fewer than 2 reasoning steps leaves nothing to investigate")

    # Truth-state structure. Aptitude and Programming enforce these in their
    # validators; for every other subject nothing does, so check here.
    if not comparison:
        if ch.truth_state == TruthState.FLAWED:
            if ch.failure is None:
                warnings.append("flawed challenge has no `failure` object")
            elif ch.failure.location not in {s.index for s in ch.ai_solution}:
                warnings.append(
                    f"failure.location {ch.failure.location} is not one of the step indices"
                )
        elif ch.failure is not None:
            warnings.append(f"{ch.truth_state.value} challenge should not carry a `failure`")
        if ch.truth_state == TruthState.INSUFFICIENT_INFORMATION and (
            not ch.missing_information.strip() or len(ch.resolving_scenarios) < 2
        ):
            warnings.append(
                "insufficient_information needs missing_information and at least 2 "
                "resolving_scenarios"
            )

    if config is not None:
        if ch.failure and ch.failure.category not in config.failure_categories:
            warnings.append(
                f"failure.category {ch.failure.category} is outside {config.name}'s "
                f"taxonomy {list(config.failure_categories)}"
            )
        allowed = {e.value for e in config.evidence_types}
        foreign = sorted({s.type.value for s in ch.valid_evidence} - allowed)
        if foreign:
            warnings.append(
                f"valid_evidence types {foreign} cannot be submitted in {config.name} "
                f"(allowed: {sorted(allowed)})"
            )

    if ch.truth_state == TruthState.FLAWED and not ch.valid_evidence:
        warnings.append("flawed challenge has no valid_evidence")
    # Only numbers in must_contain_values let the offline pre-check accept a
    # student's evidence. A text answer ("incorrect") has nothing to cite, so
    # the warning is for numeric problems only.
    if NUMBER.search(ch.canonical_answer) and not any(
        NUMBER.search(v) for s in ch.valid_evidence for v in s.must_contain_values
    ):
        warnings.append(
            "numeric answer, but no valid_evidence entry has a number in "
            "must_contain_values, so a student's evidence can never be accepted "
            "offline (only by the AI evaluator or a reviewer)"
        )

    confidences = (
        [c.simulated_confidence for c in ch.competing]
        if comparison
        else [ch.simulated_confidence]
    )
    if any(not 60 <= c <= 99 for c in confidences):
        warnings.append(f"simulated_confidence {confidences} is outside the usual 60-99 range")

    if ch.hints and ch.hints[-1].kind == "reveal" and len(ch.hints) >= 4:
        early = " ".join(h.text for h in ch.hints[:3]).lower()
        answer = ch.canonical_answer.strip().lower()
        if len(answer) >= 2 and NUMBER.search(answer) and answer in early:
            warnings.append(
                f"hints 1-3 contain the canonical answer {ch.canonical_answer!r}; only the "
                "reveal (level 5) may"
            )

    # Graded by `arithmetic.values_agree`: numbers by value, text exactly.
    if ch.transfer_check and parse_value(ch.transfer_check.answer) is None:
        warnings.append(
            f"transfer_check answer {ch.transfer_check.answer!r} is text: students must "
            "type it exactly (case-sensitive). Prefer a number"
        )

    payload = ch.validation_payload
    # Only a single Python snippet can be executed; a bash or JavaScript
    # artifact, or a multi-file project, is expected to carry no payload.
    language = str(ch.artifact.get("language", "python")).lower()
    if (
        ch.subject in EXECUTABLE_SUBJECTS
        and ch.artifact_type == "code"
        and language == "python"
        and "code" in ch.artifact
        and not all(payload.get(k) for k in ("ai_code", "reference_code", "entry_point", "test_inputs"))
    ):
        warnings.append(
            "code challenge without ai_code/reference_code/entry_point/test_inputs is "
            "not executed, so the claimed bug is not verified"
        )
    if (
        ch.subject in SOLVER_SUBJECTS - {"aptitude"}
        and ch.artifact_type in ("numeric_solution", "data_table")
        and not payload.get("solver")
    ):
        warnings.append("numeric challenge without a solver: the answer is not computed")

    return warnings


# --- main --------------------------------------------------------------------


def main(argv: list[str]) -> int:
    try:
        targets = _targets(argv)
    except FileNotFoundError as exc:
        print(f"FATAL: no such file or folder: {exc}")
        return 2
    if not targets:
        print("FATAL: no content found")
        return 2
    show_warnings = bool(argv)

    # Ids across *all* content plus the targets, so a draft that reuses an
    # existing id is caught before it overwrites a published challenge.
    # Resolved, so a target named by a relative path is not counted twice.
    id_sources: dict[str, list[str]] = {}
    every_file = {p.resolve() for p in (*settings.content_dir.rglob("*.json"), *targets)}
    for path in sorted(every_file, key=str):
        entries, _ = _raw_entries(path)
        for entry in entries or []:
            if isinstance(entry.get("id"), str):
                id_sources.setdefault(entry["id"], []).append(path.name)

    failures = warnings_total = checked = 0
    by_state: Counter[str] = Counter()

    for path in targets:
        entries, error = _raw_entries(path)
        if error:
            failures += 1
            print(f"\nFAIL {path}: {error}")
            continue

        for position, entry in enumerate(entries, 1):
            label = entry.get("id") or f"{path.name} entry #{position}"
            problems: list[str] = []

            sources = id_sources.get(entry.get("id"), [])
            if len(sources) > 1:
                problems.append(
                    f"id is used {len(sources)} times ({', '.join(sources)}); ids must be "
                    "unique across all content"
                )

            try:
                challenge = Challenge.model_validate(entry)
            except ValidationError as exc:
                failures += 1
                print(f"\nFAIL {label}  ({path.name}) - schema")
                for line in problems + _schema_errors(exc):
                    print(f"     {line}")
                continue

            checked += 1
            by_state[challenge.truth_state.value] += 1
            results = validate_challenge(challenge)
            problems += [f"{r.validator}: {r.detail}" for r in results if not r.passed]
            found = lint(challenge)
            warnings_total += len(found)

            if problems:
                failures += 1
                print(f"\nFAIL {challenge.id}  ({path.name})")
                for line in problems:
                    print(f"     {line}")
            else:
                checks = ", ".join(r.validator for r in results)
                print(f"ok   {challenge.id:<16} [{challenge.truth_state.value:<24}] {checks}")
            if show_warnings:
                for w in found:
                    print(f"     warn: {w}")

    print(f"\n{checked} challenges by truth state:")
    for state in ("flawed", "valid", "insufficient_information"):
        n = by_state.get(state, 0)
        share = n / checked * 100 if checked else 0
        print(f"  {state:<26} {n:>3}  ({share:.0f}%)")
    print(
        "target mix (PRD v0.2 3.2): "
        f"valid {settings.valid_artifact_ratio * 100:.0f}%, "
        f"insufficient {settings.insufficient_information_ratio * 100:.0f}%"
    )
    if warnings_total:
        hint = "" if show_warnings else " (name a file or folder to see them)"
        print(f"{warnings_total} authoring warning(s){hint}")

    # The catalog's `tier` label is display-only, so nothing breaks at runtime
    # when it disagrees with the registry - it just quietly misreports how
    # rigorously a subject is checked. Catch the divergence here instead.
    tier_mismatches = [
        f"{config.key}: catalog says tier {config.tier}, "
        f"registry says {'A' if has_deterministic_validator(config.key) else 'B'}"
        for config in SUBJECTS
        if (config.tier == "A") != has_deterministic_validator(config.key)
    ]
    if tier_mismatches:
        print("\nFAIL subject tier labels disagree with the validator registry:")
        for line in tier_mismatches:
            print(f"     {line}")

    if failures:
        print(f"\n{failures} challenge(s) failed validation")
    if failures or tier_mismatches:
        return 1
    print("all challenges passed deterministic validation")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
