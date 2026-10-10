"""Aptitude adapter - Tier A reference implementation (PRD sections 10, 28, 48).

Aptitude is the subject where validation can be genuinely deterministic, and
that is the point of making it the reference: the canonical answer is *computed*,
not asserted by a language model. A challenge only publishes if

    1. the canonical solver runs and reproduces `canonical_answer`, and
    2. the flawed solver runs and reproduces the AI's stated wrong answer, and
    3. the two disagree (otherwise there is nothing to find), and
    4. the declared first-failure step actually exists in the reasoning.

Check 2 is what separates a controlled educational failure from an accidental
model hallucination (PRD section 75). If the flawed path does not land on the
number the AI claims, the AI is wrong in some *other* way and the challenge is
rejected.

Solver source lives in `challenge.validation_payload`, never in `artifact`,
because `artifact` is sent to the student.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from app.engine import sandbox
from app.engine.contracts import Challenge, ChallengeMode, Judgment, TruthState
from app.subjects.base import SubjectConfig, ValidationResult
from app.subjects.catalog import BY_KEY

# Solvers are authored by the generation pipeline and reviewed by content
# developers, but they still run in a separate process with an import
# allowlist, restricted builtins, no inherited environment and a wall-clock
# timeout. See app/engine/sandbox.py for exactly what that does and does not
# guarantee.
#
# Historically solvers were given `math` and `Fraction` as injected globals
# rather than imports, and published content relies on that. The preamble keeps
# those names available; both modules are on the sandbox allowlist and are pure
# computation.
_SOLVER_PREAMBLE = """import math
from fractions import Fraction
"""

SOLVER_TIMEOUT = 5.0


class SolverError(RuntimeError):
    """Raised when a challenge's solver source cannot be executed."""


def run_solver(source: str) -> str:
    """Execute solver source and return its `answer` as a normalised string.

    The solver must assign to a variable named `answer`.
    """
    try:
        result = sandbox.run(
            _SOLVER_PREAMBLE + source,
            read_names=["answer"],
            timeout=SOLVER_TIMEOUT,
        )
    except sandbox.SandboxError as exc:
        raise SolverError(str(exc)) from exc
    if not result.ok:
        raise SolverError(f"solver failed: {result.error}")
    if "answer" not in result.names:
        raise SolverError("solver did not assign `answer`")
    return normalise(result.names["answer"])


def normalise(value: Any) -> str:
    """Canonical string form so equal quantities compare equal.

    960, 960.0 and "960" all normalise alike, and so do "175/12", the Fraction
    and the float 14.5833... The fraction case matters: the Composer is told to
    prefer exact arithmetic when a decimal would round, so it legitimately
    answers "175/12" while its solver returns a float. Treating those as
    different rejected valid challenges.

    Non-numeric answers (for example "does not follow") pass through as
    trimmed text.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Fraction):
        value = float(value)
    if isinstance(value, str):
        parsed = _parse_number(value)
        if parsed is None:
            return value.strip()
        value = parsed
    if isinstance(value, (int, float)):
        rounded = round(float(value), 6)
        if rounded == int(rounded):
            return str(int(rounded))
        return f"{rounded:g}"
    return str(value).strip()


def _parse_number(text: str) -> float | None:
    """Parse a bare numeric answer, including 'a/b' rationals.

    Returns None when the text is not purely numeric, so genuinely textual
    answers are left alone rather than coerced.
    """
    cleaned = text.strip().replace(",", "").replace("%", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        pass
    if cleaned.count("/") == 1:
        num, _, den = cleaned.partition("/")
        try:
            return float(Fraction(num.strip()) / Fraction(den.strip()))
        except (ValueError, ZeroDivisionError, TypeError):
            return None
    return None


class AptitudeAdapter:
    """Deterministic validator for quantitative and logical aptitude.

    `require_solver` is what separates Aptitude from other numeric subjects.
    PRD v0.2 makes Aptitude the reference implementation, so every Aptitude
    challenge must compute its answer - a missing solver is a defect. Elsewhere
    a subject legitimately mixes computable artifacts with textual ones (a KPI
    definition has no arithmetic to check), so the solver is validated when
    present and skipped when not.
    """

    require_solver = True

    def __init__(self, config: SubjectConfig | None = None) -> None:
        self.config = config or BY_KEY["aptitude"]

    def validate(self, challenge: Challenge) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        payload = challenge.validation_payload
        solver = payload.get("solver")
        flawed_solver = payload.get("flawed_solver")

        # Run the canonical solver once so a crash in it is reported against
        # `canonical_solver` only, rather than also polluting later diagnostics.
        canonical_computed: str | None = None
        canonical_error: str | None = None
        if solver:
            try:
                canonical_computed = run_solver(solver)
            except SolverError as exc:
                canonical_error = str(exc)

        # --- 1. canonical answer is computed, not trusted -------------------
        if not solver:
            if self.require_solver:
                results.append(
                    ValidationResult(
                        False,
                        "canonical_solver",
                        "No solver supplied; Aptitude is the reference "
                        "implementation and requires deterministic computation of "
                        "the canonical answer (PRD v0.2 section 8.1).",
                    )
                )
            elif challenge.truth_state == TruthState.INSUFFICIENT_INFORMATION:
                # Not a missing check: these challenges work *because* what is
                # needed to decide them is withheld, so there is nothing to
                # compute and supplying a solver would destroy them. Reported
                # distinctly so coverage does not read it as an unfilled gap.
                results.append(
                    ValidationResult(
                        True,
                        "insufficient_information",
                        "Underdetermined by design; computing it would supply "
                        "the information the challenge deliberately withholds.",
                    )
                )
                results.append(self._check_failure_location(challenge))
                return results
            else:
                results.append(
                    ValidationResult(
                        True,
                        "no_deterministic_check",
                        "No solver supplied; this artifact is judged on its "
                        "reasoning rather than by computation.",
                    )
                )
                # Nothing computable, so the remaining numeric checks do not apply.
                results.append(self._check_failure_location(challenge))
                return results
        elif canonical_error is not None:
            results.append(
                ValidationResult(False, "canonical_solver", canonical_error)
            )
        else:
            expected = normalise(challenge.canonical_answer)
            if canonical_computed == expected:
                results.append(
                    ValidationResult(
                        True,
                        "canonical_solver",
                        f"Solver reproduced canonical answer {canonical_computed}.",
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        False,
                        "canonical_solver",
                        f"Solver computed {canonical_computed!r} but canonical_answer "
                        f"is {expected!r}.",
                    )
                )

        # --- 2. Which-AI-Is-Wrong takes a different second stage -------------
        # There is no single artifact to be right or wrong, so instead of one
        # flawed path we verify each rival's stated answer against its own
        # solver. That is what makes the mode fair: a rival's wrong answer has
        # to *follow* from its stated reasoning, not merely be wrong.
        if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
            results.extend(self._check_rivals(challenge, canonical_computed))
            return results

        # --- 2 & 3. the flawed path must land on the AI's stated answer ------
        if challenge.contains_failure:
            if not flawed_solver:
                results.append(
                    ValidationResult(
                        False,
                        "flawed_solver",
                        "Flawed challenge has no flawed_solver, so the AI's wrong "
                        "answer cannot be shown to follow from the intended "
                        "misconception.",
                    )
                )
            else:
                try:
                    flawed = run_solver(flawed_solver)
                    claimed = normalise(challenge.ai_final_answer)
                    if flawed != claimed:
                        results.append(
                            ValidationResult(
                                False,
                                "flawed_solver",
                                f"Intended misconception yields {flawed!r} but the AI "
                                f"claims {claimed!r} - the artifact contains an "
                                "unintended error.",
                            )
                        )
                    elif challenge.answer_coincidentally_correct:
                        # PRD section 28.9: invalid reasoning that lands on the
                        # right answer. Here agreement is the whole point, so
                        # the materiality check is inverted - we require it.
                        if flawed == canonical_computed:
                            results.append(
                                ValidationResult(
                                    True,
                                    "reasoning_only_failure",
                                    f"Invalid reasoning reaches the correct answer "
                                    f"{flawed}; the failure is in the reasoning, not "
                                    "the result.",
                                )
                            )
                        else:
                            results.append(
                                ValidationResult(
                                    False,
                                    "reasoning_only_failure",
                                    "Challenge is flagged as coincidentally correct "
                                    f"but the flawed path yields {flawed!r} against a "
                                    f"canonical {canonical_computed!r}.",
                                )
                            )
                    elif canonical_computed is not None and flawed == canonical_computed:
                        results.append(
                            ValidationResult(
                                False,
                                "failure_is_material",
                                f"Flawed and canonical paths agree on {flawed!r}; "
                                "there is no detectable failure. If the reasoning is "
                                "invalid but the answer is right, set "
                                "answer_coincidentally_correct.",
                            )
                        )
                    else:
                        results.append(
                            ValidationResult(
                                True,
                                "flawed_solver",
                                f"Misconception reproduces the AI's answer {flawed}.",
                            )
                        )
                except SolverError as exc:
                    results.append(ValidationResult(False, "flawed_solver", str(exc)))
        elif challenge.truth_state == TruthState.INSUFFICIENT_INFORMATION:
            # PRD v0.2 section 4.1. What makes this state provable rather than a
            # matter of opinion is the existence of two or more readings, each
            # consistent with the supplied facts, that disagree. Without them a
            # reviewer cannot tell a genuine gap from a badly worded question.
            results.append(self._check_insufficient(challenge, canonical_computed))
        else:
            # A valid artifact (PRD v0.2 section 3.2): the AI is correct, so its
            # answer must match the computed canonical answer.
            if canonical_computed is not None:
                if canonical_computed == normalise(challenge.ai_final_answer):
                    results.append(
                        ValidationResult(
                            True,
                            "correct_artifact",
                            "AI answer matches the computed canonical answer.",
                        )
                    )
                else:
                    results.append(
                        ValidationResult(
                            False,
                            "correct_artifact",
                            "Challenge is marked correct but the AI's answer "
                            f"({challenge.ai_final_answer}) does not match the "
                            f"computed canonical answer ({canonical_computed}).",
                        )
                    )

        # --- 4. the declared failure location must exist --------------------
        results.append(self._check_failure_location(challenge))
        return results

    def _check_rivals(
        self, challenge: Challenge, canonical_computed: str | None
    ) -> list[ValidationResult]:
        """Each rival's stated answer must be reproduced by its own solver.

        `solver_a` and `solver_b` encode the two lines of reasoning as the
        rivals actually argue them. Requiring each to land on the answer that
        rival states rules out the worst Mode G authoring failure: a "wrong"
        solution whose reasoning is fine and whose stated answer was simply
        mistyped, which makes the item unlearnable.
        """
        results: list[ValidationResult] = []
        payload = challenge.validation_payload
        for solution in challenge.competing:
            key = f"solver_{solution.label.lower()}"
            name = f"rival_solver_{solution.label.lower()}"
            source = payload.get(key)
            if not source:
                results.append(
                    ValidationResult(
                        self.require_solver is False,
                        name,
                        f"No {key} supplied, so solution {solution.label}'s "
                        "stated answer is asserted rather than computed.",
                    )
                )
                continue
            try:
                computed = run_solver(source)
            except SolverError as exc:
                results.append(ValidationResult(False, name, str(exc)))
                continue
            stated = normalise(solution.ai_final_answer)
            if computed == stated:
                results.append(
                    ValidationResult(
                        True,
                        name,
                        f"Solution {solution.label}'s reasoning reproduces its "
                        f"stated answer {computed}.",
                    )
                )
            else:
                results.append(
                    ValidationResult(
                        False,
                        name,
                        f"Solution {solution.label} states "
                        f"{solution.ai_final_answer!r} but its reasoning computes "
                        f"{computed!r} - the item contains an unintended error.",
                    )
                )

        if (
            challenge.comparison
            and challenge.comparison.verdict == Judgment.UNDERDETERMINED
        ):
            results.append(self._check_insufficient(challenge, canonical_computed))
        return results

    def _check_insufficient(
        self, challenge: Challenge, computed: str | None
    ) -> ValidationResult:
        """An insufficient-information challenge must carry its own proof."""
        if len(challenge.resolving_scenarios) < 2:
            return ValidationResult(
                False,
                "insufficient_information",
                "Needs at least two resolving scenarios that are each consistent "
                "with the supplied facts and reach different answers; without "
                "them this is indistinguishable from accidental ambiguity, which "
                "is a content defect rather than a learning scenario.",
            )
        if not challenge.missing_information.strip():
            return ValidationResult(
                False,
                "insufficient_information",
                "Needs `missing_information` naming the absent fact.",
            )
        if computed is not None and computed != normalise(challenge.canonical_answer):
            return ValidationResult(
                False,
                "insufficient_information",
                f"Solver returned {computed!r} but canonical_answer is "
                f"{challenge.canonical_answer!r}; the solver should demonstrate "
                "that the readings disagree.",
            )
        return ValidationResult(
            True,
            "insufficient_information",
            f"{len(challenge.resolving_scenarios)} competing readings supplied; "
            "the gap is demonstrable.",
        )

    def _check_failure_location(self, challenge: Challenge) -> ValidationResult:
        steps = {s.index for s in challenge.ai_solution}
        if not challenge.contains_failure:
            if challenge.failure is not None:
                return ValidationResult(
                    False,
                    "failure_location",
                    f"Challenge is marked {challenge.truth_state.value} but carries "
                    "a failure object.",
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
        location = challenge.failure.location
        if location is None:
            return ValidationResult(
                False,
                "failure_location",
                "Failure has no location; students must be able to localise the "
                "first incorrect step (PRD section 41).",
            )
        if location not in steps:
            return ValidationResult(
                False,
                "failure_location",
                f"Failure location step {location} is not among the reasoning steps "
                f"{sorted(steps)}.",
            )
        return ValidationResult(
            True, "failure_location", f"First failure localised at step {location}."
        )


class NumericAdapter(AptitudeAdapter):
    """Solver checking for subjects that mix computable and textual artifacts.

    Identical to the Aptitude validator except that a challenge without a
    solver is accepted rather than rejected - Data Analytics, for instance,
    has arithmetic challenges alongside metric-definition ones.
    """

    require_solver = False
