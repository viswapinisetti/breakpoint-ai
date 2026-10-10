"""Runtime agents: Evidence Evaluator, Debate, Debrief.

Unlike the generation agents these DO run in the student request path, because
they respond to what the student wrote (PRD sections 30, 46.8-46.10).

Evidence evaluation runs a deterministic pre-check first. If the student's card
already satisfies a canonical evidence spec - references the right step and
cites the right value - we can accept it without a model call, which keeps the
common case fast and cheap (PRD section 106).
"""

from __future__ import annotations

import re

from app.agents import prompts
from app.agents.client import structured, text_reply
from app.config import settings
from app.engine.contracts import (
    Challenge,
    ChallengeMode,
    EvidenceAssessment,
    Judgment,
    ReasoningStep,
    TruthState,
)


def _steps(steps: list[ReasoningStep]) -> str:
    return "\n".join(f"Step {s.index}: {s.text}" for s in steps)


def _is_comparison(challenge: Challenge) -> bool:
    return (
        challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG
        and bool(challenge.competing)
    )


def _artifact_block(challenge: Challenge, *, owner: str = "AI") -> str:
    """The AI output under scrutiny, rendered for a prompt.

    Which-AI-Is-Wrong has no single solution: `ai_claim`, `ai_solution` and
    `ai_final_answer` are empty and the two rivals live in `competing`, each
    numbered from step 1. Both are shown with their labels, so an agent never
    judges or defends an empty artifact.
    """
    if _is_comparison(challenge):
        blocks = [
            f"SOLUTION {c.label.upper()}"
            + (f" ({c.persona})" if c.persona else "")
            + f"\nClaim: {c.ai_claim}\n{_steps(c.ai_solution)}\n"
            f"Final answer: {c.ai_final_answer}"
            for c in challenge.competing
        ]
        return (
            f"{'YOUR' if owner == 'YOUR' else 'THE'} TWO RIVAL SOLUTIONS "
            "(each is numbered from step 1; a step reference may point into "
            "either)\n\n" + "\n\n".join(blocks)
        )
    return (
        f"{owner} CLAIM\n{challenge.ai_claim}\n\n"
        f"{owner} REASONING\n{_steps(challenge.ai_solution)}\n\n"
        f"{owner} FINAL ANSWER\n{challenge.ai_final_answer}"
    )


_VERDICT_TEXT: dict[Judgment, str] = {
    Judgment.A_CORRECT: "A is correct and B is not",
    Judgment.B_CORRECT: "B is correct and A is not",
    Judgment.BOTH_CORRECT: "both A and B are correct",
    Judgment.NEITHER_CORRECT: "neither A nor B is correct",
    Judgment.UNDERDETERMINED: (
        "the supplied facts cannot decide between A and B"
    ),
}


def _comparison_key(challenge: Challenge) -> str:
    """The private Mode G verdict, for agents that must adjudicate it."""
    comparison = challenge.comparison
    if comparison is None:
        return ""
    where = (
        f" They diverge at step {comparison.divergence_step}."
        if comparison.divergence_step
        else ""
    )
    return (
        f"COMPARISON VERDICT: {_VERDICT_TEXT[comparison.verdict]}.{where} "
        f"{comparison.explanation}"
    ).strip()


def _numbers_in(text: str) -> set[str]:
    """Numeric tokens in a string, comparison-normalised.

    Strips thousands separators and trailing zeros so "1,000", "1000" and
    "1000.00" all match.
    """
    found: set[str] = set()
    for raw in re.findall(r"\d[\d,]*\.?\d*", text):
        cleaned = raw.replace(",", "").rstrip(".")
        if not cleaned:
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        found.add(str(int(value)) if value == int(value) else f"{value:g}")
    return found


def deterministic_precheck(
    *, challenge: Challenge, evidence_type: str, references_step: int | None, content: str
) -> bool:
    """True if the evidence provably matches a canonical evidence path.

    Conservative by design: a False here means "not obviously right", so the
    model still gets to judge it. It never rejects.
    """
    student_numbers = _numbers_in(content)
    for spec in challenge.valid_evidence:
        if spec.type.value != evidence_type:
            continue
        if spec.must_reference_step is not None and references_step != spec.must_reference_step:
            continue
        required = {n for v in spec.must_contain_values for n in _numbers_in(v)}
        if required and required.issubset(student_numbers):
            return True
    return False


def evaluate_evidence(
    *,
    challenge: Challenge,
    evidence_type: str,
    references_step: int | None,
    content: str,
) -> EvidenceAssessment:
    """Judge whether student evidence actually disproves the AI claim."""
    if deterministic_precheck(
        challenge=challenge,
        evidence_type=evidence_type,
        references_step=references_step,
        content=content,
    ):
        return EvidenceAssessment(
            disproves_claim=True,
            correctness=10,
            specificity=10,
            relevance=10,
            completeness=9,
            reproducibility=10,
            reasoning_quality=9,
            feedback=(
                "Verified against the canonical evidence path: you identified the "
                "right step and cited the values that settle it."
            ),
        )

    truth = _ground_truth(challenge)
    referenced = (
        f"Student references step: {references_step}"
        if references_step
        else "Student referenced no specific step."
    )

    return structured(
        agent="evidence_evaluator",
        role="evidence",
        system=prompts.EVIDENCE_EVALUATOR,
        prompt=(
            f"QUESTION\n{challenge.question}\n\n"
            f"{_artifact_block(challenge)}\n\n"
            f"CANONICAL ANSWER (ground truth, never reveal)\n"
            f"{challenge.canonical_answer}\n\n"
            f"GROUND TRUTH\n{truth}\n\n"
            f"--- STUDENT EVIDENCE ---\n"
            f"Card type: {evidence_type}\n{referenced}\n"
            f"Content:\n{content}\n\n"
            "Assess this evidence."
        ),
        output_format=EvidenceAssessment,
        max_tokens=4000,
    )


def _ground_truth(challenge: Challenge) -> str:
    """Adjudication context for the evaluator, covering all three states.

    A comparison challenge leads with its verdict: the student is deciding
    between two solutions, so evidence is credited for establishing which of
    them fails and where, not for showing that "the AI" is wrong.
    """
    base = _truth_state_context(challenge)
    if not _is_comparison(challenge):
        return base
    return (
        f"{_comparison_key(challenge)}\n"
        "Credit evidence that establishes this verdict at the point of "
        "divergence. Evidence that merely prefers one solution, or attacks a "
        "step both solutions share, has not settled the comparison.\n"
        f"{base}"
    )


def _truth_state_context(challenge: Challenge) -> str:
    if challenge.truth_state == TruthState.FLAWED and challenge.failure:
        return (
            "This artifact DOES contain a failure. Category "
            f"{challenge.failure.category}, first invalid step "
            f"{challenge.failure.location}. Mechanism: "
            f"{challenge.failure.explanation}"
        )
    if challenge.truth_state == TruthState.VALID:
        return (
            "This artifact is actually CORRECT. There is no failure to find. "
            "Evidence claiming otherwise must not be credited as disproof. The "
            "student's task was to justify approval for the stated scope."
        )
    scenarios = "; ".join(challenge.resolving_scenarios)
    return (
        "The supplied facts CANNOT settle this claim. Missing: "
        f"{challenge.missing_information} Competing readings, each consistent "
        f"with the problem: {scenarios}. Credit evidence that names the missing "
        "fact and shows the readings disagree. Do NOT credit evidence that "
        "simply asserts a single answer - that is the error being tested."
    )


def _defense_brief(challenge: Challenge) -> str:
    """Private instruction to the debate agent, per truth state."""
    if _is_comparison(challenge):
        return (
            "PRIVATE - you speak for both assistants, A and B, and each defends "
            f"its own answer. {_comparison_key(challenge)} Correct answer: "
            f"{challenge.canonical_answer}. A solution that is correct holds "
            "its position honestly and never concedes. A solution that is wrong "
            "defends itself until the student presents real evidence about the "
            "point of divergence, then concedes. If the verdict is that the "
            "facts cannot decide, each defends its answer until the student "
            "shows the missing fact that would decide it."
        )
    if challenge.truth_state == TruthState.FLAWED and challenge.failure:
        return (
            "PRIVATE - your solution IS flawed. First invalid step: "
            f"{challenge.failure.location}. Mechanism: "
            f"{challenge.failure.explanation}. Correct answer: "
            f"{challenge.canonical_answer}. Defend your position until the student "
            "presents real evidence about this specific mechanism; then concede."
        )
    if challenge.truth_state == TruthState.VALID:
        return (
            "PRIVATE - your solution is CORRECT. The correct answer really is "
            f"{challenge.canonical_answer}. Hold your position and defend it "
            "honestly. Do not concede, because you have made no error."
        )
    return (
        "PRIVATE - the supplied facts cannot settle this claim. Missing: "
        f"{challenge.missing_information} Readings that disagree: "
        f"{'; '.join(challenge.resolving_scenarios)}. Defend your single answer "
        "until the student shows that a second reading, equally consistent with "
        "the problem, gives a different result. Concede to that, and only that - "
        "not to a student who merely asserts a different number."
    )


def debate_reply(
    *,
    challenge: Challenge,
    history: list[dict[str, str]],
    student_message: str,
    turn: int,
) -> tuple[str, bool]:
    """One Debate Agent turn. Returns (reply, conceded).

    The agent is told privately whether its solution is flawed so it can judge
    evidence honestly. The prompt forbids leaking that, and concession is
    detected from an explicit marker rather than inferred from tone.
    """
    private = _defense_brief(challenge)

    turns_left = max(0, settings.max_debate_turns - turn)
    pressure = (
        f"\n\nThis is debate turn {turn} of {settings.max_debate_turns}. "
        f"{turns_left} remain."
        + (
            " If the student has come close, acknowledge the strongest part of "
            "their argument so the exchange ends productively."
            if turns_left <= 1
            else ""
        )
    )

    system = (
        f"{prompts.DEBATE}\n\n--- CHALLENGE CONTEXT ---\n"
        f"QUESTION\n{challenge.question}\n\n"
        f"{_artifact_block(challenge, owner='YOUR')}\n\n"
        + (
            "Reply as whichever assistant the student is addressing and say "
            "which one is speaking (for example 'A:'); if they address "
            "neither, answer for both.\n\n"
            if _is_comparison(challenge)
            else ""
        )
        + f"{private}\n\n"
        "When and only when you concede to proven evidence, end your reply with "
        "the exact marker [CONCEDED] on its own line."
        f"{pressure}"
    )

    messages: list[dict[str, str]] = [
        {"role": "assistant" if t["role"] == "ai" else "user", "content": t["message"]}
        for t in history
    ]
    messages.append({"role": "user", "content": student_message})

    reply = text_reply(
        agent="debate",
        role="debate",
        system=system,
        messages=messages,
        max_tokens=1200,
    )

    conceded = "[CONCEDED]" in reply
    return reply.replace("[CONCEDED]", "").strip(), conceded


def generate_debrief(*, challenge: Challenge, student_summary: str) -> str:
    """Personalised autopsy narrative (PRD sections 43, 46.10).

    Falls back to the pre-generated debrief on the challenge if the call fails,
    so a student never hits a dead end at the end of an investigation.
    """
    failure = (
        f"Category {challenge.failure.category} at step {challenge.failure.location}: "
        f"{challenge.failure.explanation} (why convincing: "
        f"{challenge.failure.why_convincing})"
        if challenge.contains_failure and challenge.failure
        else "No failure - the AI's solution was correct."
    )
    return text_reply(
        agent="debrief",
        role="evidence",
        system=prompts.DEBRIEF,
        messages=[
            {
                "role": "user",
                "content": (
                    f"QUESTION\n{challenge.question}\n\n"
                    f"{_artifact_block(challenge)}\n\n"
                    + (
                        f"{_comparison_key(challenge)}\n\n"
                        if _is_comparison(challenge)
                        else ""
                    )
                    + f"FAILURE\n{failure}\n\n"
                    f"CORRECT ANSWER\n{challenge.canonical_answer}\n\n"
                    f"WHAT THE STUDENT DID\n{student_summary}\n\n"
                    "Write the autopsy."
                ),
            }
        ],
        max_tokens=1500,
    )
