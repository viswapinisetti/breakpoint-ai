"""Mode F - Break the Tests (PRD v0.2 section 4.2).

The artifact ships with a test suite that passes. That is the whole point: a
passing suite is the single most common reason a wrong implementation reaches
production, so "the tests are green" is exactly the kind of evidence students
must learn not to trust. The task is to find the input the suite forgot.

Success is defined by behaviour, not by opinion: the student's input must make
the shipped implementation and the correct implementation disagree. Both are
executed in the sandbox, and the disagreement - or its absence - is the verdict.
Nothing here consults an LLM.

Student input is parsed as literals and passed as arguments. It is never
executed as code (see `sandbox.parse_test_args`), which is what keeps an
open-ended "write me a test" interaction safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine import sandbox
from app.engine.contracts import Challenge


@dataclass(slots=True)
class TestVerdict:
    """The outcome of one Break-the-Tests submission."""

    accepted: bool
    reason_code: str
    message: str
    normalised_input: str = ""
    shipped_result: str = ""
    correct_result: str = ""


def _describe(outcome: sandbox.CallOutcome) -> str:
    """A comparable, displayable string for one call's outcome.

    An exception is compared by *type*, not by message: two implementations
    that both raise ValueError agree about the input being rejected, and the
    wording of the message is not behaviour a student should have to match.
    """
    if outcome.ok:
        return repr(outcome.value)
    return f"raises {outcome.error.split(':', 1)[0]}"


def _run(source: str, entry_point: str, args: list[Any]) -> sandbox.CallOutcome:
    result = sandbox.run(source, entry_point=entry_point, calls=[args])
    if not result.ok:
        # The snippet did not even define its function. This is an authoring
        # fault, not a student one, and must never be reported as "your test
        # did not break anything" - that would blame the student for our bug.
        raise sandbox.SandboxError(result.error or "implementation failed to load")
    return result.calls[0]


def evaluate_test(challenge: Challenge, raw_input: str) -> TestVerdict:
    """Judge one candidate test input against the two implementations."""
    gap = challenge.test_gap
    if gap is None:
        raise ValueError("challenge is not a break_the_tests challenge")

    payload = challenge.validation_payload
    shipped = payload.get("ai_code")
    correct = payload.get("reference_code")
    if not (shipped and correct):
        raise ValueError("break_the_tests challenge is missing its implementations")

    try:
        args = sandbox.parse_test_args(raw_input, arity=gap.arity)
    except sandbox.TestInputError as exc:
        return TestVerdict(
            accepted=False, reason_code="unparseable_input", message=str(exc)
        )

    normalised = sandbox.canonical_args(args)

    # An input the shipped suite already covers proves nothing: the suite
    # passes on it by construction.
    already = {
        sandbox.canonical_args(sandbox.parse_test_args(t, arity=gap.arity))
        for t in gap.existing_tests
        if _parseable(t, gap.arity)
    }
    if normalised in already:
        return TestVerdict(
            accepted=False,
            reason_code="already_covered",
            message=(
                "The shipped suite already tests that input, and it passes. "
                "A test that the code already survives cannot expose anything - "
                "look for the case the suite never considered."
            ),
            normalised_input=normalised,
        )

    try:
        shipped_outcome = _run(shipped, gap.entry_point, args)
        correct_outcome = _run(correct, gap.entry_point, args)
    except sandbox.SandboxError as exc:
        return TestVerdict(
            accepted=False,
            reason_code="execution_error",
            message=(
                "We could not run that input against both implementations "
                f"({exc}). This is a problem on our side, not with your test - "
                "please report it and try another input."
            ),
            normalised_input=normalised,
        )

    shipped_text = _describe(shipped_outcome)
    correct_text = _describe(correct_outcome)

    if shipped_text != correct_text:
        return TestVerdict(
            accepted=True,
            reason_code="suite_broken",
            message=(
                f"Your test breaks it. On {normalised} the shipped code gives "
                f"{shipped_text}, but the correct behaviour is {correct_text}. "
                "The suite was green because it never asked this question."
            ),
            normalised_input=normalised,
            shipped_result=shipped_text,
            correct_result=correct_text,
        )

    return TestVerdict(
        accepted=False,
        reason_code="no_divergence",
        message=(
            f"Both implementations give {shipped_text} on {normalised}, so this "
            "input does not separate them. That is real information: you have "
            "just ruled out a region of the input space. Try the edges - "
            "empty, zero, negative, duplicate, boundary, out-of-order."
        ),
        normalised_input=normalised,
        shipped_result=shipped_text,
        correct_result=correct_text,
    )


def _parseable(raw: str, arity: int) -> bool:
    try:
        sandbox.parse_test_args(raw, arity=arity)
    except sandbox.TestInputError:
        return False
    return True
