"""Subject-independent structural checks for the P1 challenge modes.

PRD v0.2 section 9.1 puts structure first in the validation hierarchy, before
anything deterministic and long before any rubric. These checks belong to the
*mode*, not the subject: a Which-AI-Is-Wrong item whose "wrong" solution
actually states the correct answer is broken in Aptitude, in DSA and in MLOps
alike, so the check lives once, here, and every subject inherits it.

Nothing in this module runs a model or executes content code. It reads what the
author declared and checks it is internally consistent.
"""

from __future__ import annotations

from app.engine.arithmetic import values_agree
from app.engine.contracts import Challenge, ChallengeMode, Judgment
from app.subjects.base import ValidationResult


def validate_mode(challenge: Challenge) -> list[ValidationResult]:
    """Structural checks for the challenge's mode. Empty when there are none."""
    if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
        return _check_comparison(challenge)
    if challenge.challenge_mode == ChallengeMode.BREAK_THE_TESTS:
        return _check_test_gap_shape(challenge)
    return []


# --- Mode G ----------------------------------------------------------------

# Which solutions must state the canonical answer, for each verdict. `None`
# means "no constraint from this rule".
_MUST_AGREE: dict[Judgment, tuple[bool | None, bool | None]] = {
    Judgment.A_CORRECT: (True, False),
    Judgment.B_CORRECT: (False, True),
    Judgment.BOTH_CORRECT: (True, True),
    Judgment.NEITHER_CORRECT: (False, False),
    # Underdetermined has no canonical answer to agree with, so the constraint
    # is on the pair instead: they must actually disagree with each other.
    Judgment.UNDERDETERMINED: (None, None),
}


def _check_comparison(challenge: Challenge) -> list[ValidationResult]:
    comparison = challenge.comparison
    if comparison is None:  # pragma: no cover - contract validator prevents it
        return [
            ValidationResult(False, "comparison_verdict", "no comparison verdict")
        ]

    results: list[ValidationResult] = []
    a, b = challenge.competing[0], challenge.competing[1]
    verdict = comparison.verdict

    # 1. Both solutions must actually be shown. A single-step rival is not a
    #    rival, it is a distractor, and the mode collapses into a coin flip.
    for solution in (a, b):
        if len(solution.ai_solution) < 2:
            results.append(
                ValidationResult(
                    False,
                    "competing_solutions_shown",
                    f"Solution {solution.label} has "
                    f"{len(solution.ai_solution)} step(s); a rival solution "
                    "needs a visible line of reasoning to investigate.",
                )
            )
    if not results:
        results.append(
            ValidationResult(
                True,
                "competing_solutions_shown",
                f"Both solutions shown in full ({len(a.ai_solution)} and "
                f"{len(b.ai_solution)} steps).",
            )
        )

    # 2. The declared answers must match the declared verdict. This is the
    #    check that catches the authoring slip that matters most: labelling B
    #    wrong while B states the right answer.
    want_a, want_b = _MUST_AGREE[verdict]
    agree_a = values_agree(a.ai_final_answer, challenge.canonical_answer)
    agree_b = values_agree(b.ai_final_answer, challenge.canonical_answer)
    mismatches = [
        label
        for label, want, got in (("A", want_a, agree_a), ("B", want_b, agree_b))
        if want is not None and want != got
    ]
    if mismatches:
        results.append(
            ValidationResult(
                False,
                "verdict_matches_answers",
                f"Verdict is {verdict.value}, but solution "
                f"{' and '.join(mismatches)} does not behave that way against "
                f"the canonical answer {challenge.canonical_answer!r} "
                f"(A states {a.ai_final_answer!r}, B states "
                f"{b.ai_final_answer!r}).",
            )
        )
    else:
        results.append(
            ValidationResult(
                True,
                "verdict_matches_answers",
                f"Stated answers are consistent with a {verdict.value} verdict.",
            )
        )

    # 3. Two solutions that state the same answer cannot be told apart by the
    #    answer, so unless the verdict is `both_correct` the item is unfair.
    same_answer = values_agree(a.ai_final_answer, b.ai_final_answer)
    if same_answer and verdict != Judgment.BOTH_CORRECT:
        results.append(
            ValidationResult(
                False,
                "solutions_are_distinguishable",
                f"Both solutions state {a.ai_final_answer!r}, so the verdict "
                f"{verdict.value} cannot be reached from the answers - and if "
                "the difference is only in the reasoning, say so in the "
                "question.",
            )
        )
    elif not same_answer and verdict == Judgment.BOTH_CORRECT:
        results.append(
            ValidationResult(
                False,
                "solutions_are_distinguishable",
                f"Verdict is both_correct but the answers differ "
                f"({a.ai_final_answer!r} vs {b.ai_final_answer!r}).",
            )
        )
    else:
        results.append(
            ValidationResult(
                True,
                "solutions_are_distinguishable",
                "The pair of stated answers is consistent with the verdict.",
            )
        )

    # 4. An underdetermined comparison must carry its proof, exactly as an
    #    insufficient-information artifact does (PRD v0.2 section 4.1): the
    #    missing fact, plus at least two readings that disagree.
    if verdict == Judgment.UNDERDETERMINED:
        if challenge.missing_information and len(challenge.resolving_scenarios) >= 2:
            results.append(
                ValidationResult(
                    True,
                    "underdetermined_is_provable",
                    f"{len(challenge.resolving_scenarios)} competing readings "
                    "declared, with the missing fact named.",
                )
            )
        else:
            results.append(
                ValidationResult(
                    False,
                    "underdetermined_is_provable",
                    "An underdetermined verdict needs missing_information and "
                    "at least two resolving_scenarios, or it is indistinguishable "
                    "from an ambiguous question.",
                )
            )

    # 5. The divergence step must exist in both solutions, since it is the
    #    answer to "where do these part company" and gets marked in both.
    step = comparison.divergence_step
    if step is None:
        results.append(
            ValidationResult(
                False,
                "divergence_step_exists",
                "No divergence_step declared; the debrief has nothing to point at.",
            )
        )
    else:
        missing = [
            s.label
            for s in (a, b)
            if step not in {x.index for x in s.ai_solution}
        ]
        results.append(
            ValidationResult(
                not missing,
                "divergence_step_exists",
                f"Divergence at step {step} is present in both solutions."
                if not missing
                else f"Step {step} does not exist in solution "
                f"{' and '.join(missing)}.",
            )
        )

    # 6. If the author documented the misconception, its location must sit in
    #    the solution that actually loses. Pointing it at the winner would send
    #    the autopsy to argue against a step that is fine.
    if challenge.failure is not None and challenge.failure.location is not None:
        losers = {
            Judgment.A_CORRECT: ("B",),
            Judgment.B_CORRECT: ("A",),
            Judgment.NEITHER_CORRECT: ("A", "B"),
            Judgment.BOTH_CORRECT: (),
            Judgment.UNDERDETERMINED: ("A", "B"),
        }[verdict]
        location = challenge.failure.location
        holders = {
            s.label.upper()
            for s in (a, b)
            if location in {x.index for x in s.ai_solution}
        }
        ok = bool(losers) and bool(holders & set(losers))
        results.append(
            ValidationResult(
                ok,
                "failure_in_losing_solution",
                f"Declared failure at step {location} lies in solution "
                f"{'/'.join(sorted(holders & set(losers)))}."
                if ok
                else f"Declared failure at step {location} is not in a losing "
                f"solution (verdict {verdict.value}, losers "
                f"{'/'.join(losers) or 'none'}).",
            )
        )

    return results


# --- Mode F ----------------------------------------------------------------


def _check_test_gap_shape(challenge: Challenge) -> list[ValidationResult]:
    """Declared shape only. Whether the gap is *reachable* needs execution and
    is checked by the executable adapter (`programming._check_test_gap`)."""
    gap = challenge.test_gap
    if gap is None:  # pragma: no cover - contract validator prevents it
        return [ValidationResult(False, "test_gap_declared", "no test_gap")]

    results: list[ValidationResult] = []
    if gap.existing_tests:
        results.append(
            ValidationResult(
                True,
                "test_gap_declared",
                f"{len(gap.existing_tests)} shipped test(s) on "
                f"{gap.entry_point}/{gap.arity}.",
            )
        )
    else:
        results.append(
            ValidationResult(
                False,
                "test_gap_declared",
                "No existing_tests declared. The premise of the mode is a suite "
                "that already passes; with an empty suite there is nothing to "
                "have trusted.",
            )
        )
    return results
