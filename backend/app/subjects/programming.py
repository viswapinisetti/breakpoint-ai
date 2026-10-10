"""Programming adapter - Tier A deterministic validator (PRD sections 12, 96).

PRD section 96 is explicit: the student creates a failing input and "the product
automatically runs it. Failure confirmed." That is only honest if the engine
really executes the code, so this validator does.

A programming challenge carries two implementations in `validation_payload`:
the AI's code (as shown to the student) and a reference implementation. The
validator runs both across a set of inputs and checks that the artifact means
what the challenge claims:

* a flawed challenge must have at least one input where the two disagree -
  otherwise there is no detectable bug, whatever the prose asserts;
* a correct challenge must agree on every input;
* the declared counterexample, if given, must actually be one.

This is the same principle as the Aptitude solver check: correctness is
computed, not asserted.

Execution safety: student input reaches this path only as *data* - argument
literals parsed by `ast.literal_eval`, never as code. The code itself is
authored by content developers or produced by the generation pipeline and
reviewed before publication. It still runs in a separate process with an
import allowlist, restricted builtins, a minimal environment and a wall-clock
timeout; `app/engine/sandbox.py` documents precisely what that guarantees.
"""

from __future__ import annotations

import ast
from typing import Any

from app.engine import sandbox
from app.engine.contracts import Challenge
from app.subjects.base import SubjectConfig, ValidationResult
from app.subjects.catalog import BY_KEY


class CodeError(RuntimeError):
    """Challenge code could not be executed."""


CASE_TIMEOUT = 5.0


def parse_call(call: str) -> list[object]:
    """Turn a stored argument expression into a positional argument list.

    `call` is a literal such as "([-5, -10, -2],)" - a tuple of positional
    arguments. Parsed, never executed: `ast.literal_eval` accepts constants and
    literal containers only, so no argument expression can become a payload.
    """
    try:
        args = ast.literal_eval(call)
    except (ValueError, SyntaxError, TypeError) as exc:
        raise CodeError(f"could not parse arguments {call!r}: {exc}") from exc
    return list(args) if isinstance(args, tuple) else [args]


def run_case(source: str, entry_point: str, call: str) -> Any:
    """Execute `source` in the sandbox, then apply `entry_point` to `call`.

    An exception raised by the code under test is captured and returned as a
    marker string rather than propagating, because "this input raises" is
    itself a legitimate observable behaviour to compare. A failure of the
    sandbox itself - or of the snippet to define its function - is a CodeError,
    because that means the comparison never happened and must not be read as
    two implementations agreeing.
    """
    args = parse_call(call)
    try:
        result = sandbox.run(
            source, entry_point=entry_point, calls=[args], timeout=CASE_TIMEOUT
        )
    except sandbox.SandboxError as exc:
        raise CodeError(str(exc)) from exc
    if not result.ok:
        raise CodeError(f"code failed to run: {result.error}")
    outcome = result.calls[0]
    if not outcome.ok:
        return f"<raised {outcome.error.split(':', 1)[0]}>"
    return outcome.value


class ProgrammingAdapter:
    """Executes challenge code to prove the claimed behaviour."""

    def __init__(self, config: SubjectConfig | None = None) -> None:
        # Registered for more than one subject (Programming and DSA), so the
        # config is whatever the registry supplied rather than a fixed key.
        self.config = config or BY_KEY["programming"]

    def validate(self, challenge: Challenge) -> list[ValidationResult]:
        payload = challenge.validation_payload
        ai_code = payload.get("ai_code")
        reference = payload.get("reference_code")
        entry = payload.get("entry_point")
        cases: list[str] = list(payload.get("test_inputs") or [])

        if not (ai_code and reference and entry and cases):
            return [
                ValidationResult(
                    True,
                    "no_executable_validation",
                    "Challenge carries no runnable payload (needs ai_code, "
                    "reference_code, entry_point and test_inputs); relying on "
                    "critic and human review.",
                )
            ]

        results: list[ValidationResult] = []
        disagreements: list[tuple[str, Any, Any]] = []
        try:
            for call in cases:
                got = run_case(ai_code, entry, call)
                want = run_case(reference, entry, call)
                if got != want:
                    disagreements.append((call, got, want))
        except CodeError as exc:
            return [ValidationResult(False, "code_execution", str(exc))]

        results.append(
            ValidationResult(
                True,
                "code_execution",
                f"Both implementations ran across {len(cases)} input(s).",
            )
        )

        if challenge.contains_failure:
            if disagreements:
                call, got, want = disagreements[0]
                results.append(
                    ValidationResult(
                        True,
                        "failure_is_reproducible",
                        f"Input {call} returns {got!r} but should return {want!r} "
                        f"({len(disagreements)} of {len(cases)} inputs differ).",
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        False,
                        "failure_is_reproducible",
                        "The AI's code agrees with the reference on every test "
                        "input, so the claimed bug is not detectable. Add an "
                        "input that exposes it, or the challenge is unfair.",
                    )
                )
        else:
            if disagreements:
                call, got, want = disagreements[0]
                results.append(
                    ValidationResult(
                        False,
                        "correct_artifact",
                        f"Challenge is marked {challenge.truth_state.value}, but "
                        f"input {call} returns "
                        f"{got!r} against a reference {want!r}.",
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        True,
                        "correct_artifact",
                        "The AI's code matches the reference on every input.",
                    )
                )

        # A declared counterexample must genuinely break the code, or students
        # are handed evidence that does not hold up.
        counter = payload.get("counterexample_input")
        if counter:
            try:
                got = run_case(ai_code, entry, counter)
                want = run_case(reference, entry, counter)
            except CodeError as exc:
                results.append(
                    ValidationResult(False, "counterexample_holds", str(exc))
                )
            else:
                if got != want:
                    results.append(
                        ValidationResult(
                            True,
                            "counterexample_holds",
                            f"Counterexample {counter} reproduces the failure: "
                            f"{got!r} instead of {want!r}.",
                        )
                    )
                else:
                    results.append(
                        ValidationResult(
                            False,
                            "counterexample_holds",
                            f"Declared counterexample {counter} does not expose any "
                            f"difference (both return {got!r}).",
                        )
                    )

        results.extend(self._check_test_gap(challenge, ai_code, reference))
        results.append(self._check_failure_location(challenge))
        return results

    def _check_test_gap(
        self, challenge: Challenge, ai_code: str, reference: str
    ) -> list[ValidationResult]:
        """Gate a Break-the-Tests item on its two structural promises.

        Mode F makes the student two promises, and both are checkable without
        an LLM:

        1. *The shipped suite passes.* Every input listed in `existing_tests`
           must produce the same result from both implementations. If one of
           them already fails, the premise is a lie and the student is being
           asked to find something that is already visible.
        2. *The gap is findable.* At least one input in the author's
           `breaking_inputs` must separate them, so we know a winning answer
           exists. Shipping a challenge with no reachable answer is the worst
           failure mode this mode has.
        """
        gap = challenge.test_gap
        if gap is None:
            return []

        results: list[ValidationResult] = []
        try:
            leaks = [
                call
                for call in gap.existing_tests
                if run_case(ai_code, gap.entry_point, call)
                != run_case(reference, gap.entry_point, call)
            ]
        except CodeError as exc:
            return [ValidationResult(False, "shipped_suite_passes", str(exc))]

        if leaks:
            results.append(
                ValidationResult(
                    False,
                    "shipped_suite_passes",
                    f"Existing test {leaks[0]} already fails against the "
                    "reference, so the shipped suite is not green and the "
                    "premise of the challenge does not hold.",
                )
            )
        else:
            results.append(
                ValidationResult(
                    True,
                    "shipped_suite_passes",
                    f"All {len(gap.existing_tests)} shipped test(s) agree with "
                    "the reference, so the suite really is green.",
                )
            )

        breaking = list(challenge.validation_payload.get("breaking_inputs") or [])
        if not breaking:
            results.append(
                ValidationResult(
                    False,
                    "test_gap_is_reachable",
                    "No breaking_inputs declared, so nothing proves a winning "
                    "test input exists.",
                )
            )
            return results

        try:
            found = [
                call
                for call in breaking
                if run_case(ai_code, gap.entry_point, call)
                != run_case(reference, gap.entry_point, call)
            ]
        except CodeError as exc:
            return [*results, ValidationResult(False, "test_gap_is_reachable", str(exc))]

        if found:
            results.append(
                ValidationResult(
                    True,
                    "test_gap_is_reachable",
                    f"{len(found)} of {len(breaking)} declared input(s) separate "
                    f"the implementations, e.g. {found[0]}.",
                )
            )
        else:
            results.append(
                ValidationResult(
                    False,
                    "test_gap_is_reachable",
                    "None of the declared breaking_inputs separates the two "
                    "implementations, so the challenge has no reachable answer.",
                )
            )
        return results

    def _check_failure_location(self, challenge: Challenge) -> ValidationResult:
        steps = {s.index for s in challenge.ai_solution}
        if not challenge.contains_failure:
            if challenge.failure is not None:
                return ValidationResult(
                    False,
                    "failure_location",
                    f"Challenge is marked {challenge.truth_state.value} but "
                    "carries a failure object.",
                )
            return ValidationResult(
                True,
                "failure_location",
                f"{challenge.truth_state.value} artifact, no failure expected.",
            )
        if challenge.failure is None:
            return ValidationResult(
                False, "failure_location", "Flawed challenge has no failure object."
            )
        if challenge.failure.location not in steps:
            return ValidationResult(
                False,
                "failure_location",
                f"Failure location step {challenge.failure.location} is not among "
                f"the reasoning steps {sorted(steps)}.",
            )
        return ValidationResult(
            True,
            "failure_location",
            f"First failure localised at step {challenge.failure.location}.",
        )
