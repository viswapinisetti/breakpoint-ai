"""Critical quality pipeline (PRD sections 47, 48, 75, 76).

    GENERATE -> SOLVE INDEPENDENTLY -> INJECT FAILURE -> CRITIQUE
    -> DETERMINISTIC CHECK -> SECOND VALIDATION -> DIFFICULTY CHECK
    -> QUALITY FILTER -> PUBLISH

No challenge reaches a student straight from generation. Each stage can reject,
and every rejection is recorded with a reason so content developers can see
*why* the funnel narrowed (PRD section 57).

This runs offline. The student path only ever reads already-published rows.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field

from app.agents import generation
from app.agents.client import AgentError
from app.config import settings
from app.engine.contracts import (
    Challenge,
    ChallengeMode,
    Difficulty,
    EvidenceSpec,
    EvidenceType,
    Failure,
    Hint,
    QualityScore,
    ReasoningStep,
)
from app.governance import validate as validate_challenge
from app.subjects.base import ValidationResult

logger = logging.getLogger(__name__)

# Confidence band for the simulated confidence badge (PRD section 33). High and
# narrow on purpose: the point is that confidence and correctness are unrelated.
_CONFIDENCE_BY_DIFFICULTY = {
    "1": 88,
    "2": 92,
    "3": 94,
    "4": 96,
    "5": 97,
}


@dataclass
class PipelineOutcome:
    """Result of running one candidate through the pipeline."""

    challenge: Challenge | None
    published: bool
    stage: str
    reasons: list[str] = field(default_factory=list)
    validations: list[ValidationResult] = field(default_factory=list)
    quality: QualityScore | None = None
    critic_found_failure: bool | None = None

    @property
    def rejected(self) -> bool:
        return not self.published


def _hints(source: object, reveal: str) -> list[Hint]:
    """Assemble the five-level hint ladder (PRD section 40)."""
    return [
        Hint(level=1, kind="attention", text=getattr(source, "hint_attention", "")),
        Hint(level=2, kind="direction", text=getattr(source, "hint_direction", "")),
        Hint(level=3, kind="concept", text=getattr(source, "hint_concept", "")),
        Hint(level=4, kind="strong", text=getattr(source, "hint_strong", "")),
        Hint(level=5, kind="reveal", text=reveal),
    ]


def generate_candidate(
    *,
    subject: str,
    topic: str,
    concept: str,
    difficulty: str,
    desired_failure: str,
    mode: ChallengeMode = ChallengeMode.TRUST_OR_CHALLENGE,
    make_correct: bool = False,
) -> Challenge:
    """Stages 1-3: compose, then either inject a failure or solve correctly."""
    problem = generation.compose(
        subject=subject, topic=topic, concept=concept, difficulty=difficulty
    )
    challenge_id = f"{subject[:3]}-{uuid.uuid4().hex[:8]}"
    confidence = _CONFIDENCE_BY_DIFFICULTY.get(difficulty, 93)

    if make_correct:
        correct = generation.solve_correctly(problem=problem, difficulty=difficulty)
        return Challenge(
            id=challenge_id,
            subject=subject,
            topic=topic,
            subtopic=concept,
            difficulty=Difficulty(difficulty),
            challenge_mode=mode,
            question=problem.question,
            artifact_type=problem.artifact_type,
            artifact={f.key: f.value for f in problem.artifact},
            ai_claim=correct.ai_claim,
            ai_solution=[
                ReasoningStep(index=s.index, text=s.text) for s in correct.ai_solution
            ],
            ai_final_answer=correct.ai_final_answer,
            simulated_confidence=confidence,
            contains_failure=False,
            failure=None,
            canonical_solution=problem.canonical_solution,
            canonical_answer=problem.canonical_answer,
            hints=_hints(
                correct,
                "This solution is correct. Every step holds, and the answer is "
                f"{problem.canonical_answer}. The right move was to approve it.",
            ),
            repair="",
            debrief=correct.debrief,
            validation_payload={"solver": problem.solver},
        )

    injected = generation.inject_failure(
        problem=problem, desired_failure=desired_failure, difficulty=difficulty
    )
    evidence_specs = [
        EvidenceSpec(
            type=EvidenceType.CALCULATION,
            summary=summary,
            must_reference_step=injected.failure_location,
            must_contain_values=[problem.canonical_answer],
        )
        for summary in (injected.evidence_summaries or ["Recompute the failing step."])
    ]
    if injected.counterexamples:
        evidence_specs.append(
            EvidenceSpec(
                type=EvidenceType.COUNTEREXAMPLE,
                summary="A case where the AI's rule fails.",
                must_contain_values=injected.counterexamples[:1],
            )
        )

    return Challenge(
        id=challenge_id,
        subject=subject,
        topic=topic,
        subtopic=concept,
        difficulty=Difficulty(difficulty),
        challenge_mode=mode,
        question=problem.question,
        artifact_type=problem.artifact_type,
        artifact={f.key: f.value for f in problem.artifact},
        ai_claim=injected.ai_claim,
        ai_solution=[
            ReasoningStep(index=s.index, text=s.text) for s in injected.ai_solution
        ],
        ai_final_answer=injected.ai_final_answer,
        simulated_confidence=confidence,
        contains_failure=True,
        failure=Failure(
            category=injected.failure_category,
            location=injected.failure_location,
            misconception=injected.misconception,
            explanation=injected.explanation,
            why_convincing=injected.why_convincing,
        ),
        canonical_solution=problem.canonical_solution,
        canonical_answer=problem.canonical_answer,
        valid_evidence=evidence_specs,
        counterexamples=injected.counterexamples,
        hints=_hints(
            injected,
            f"{injected.explanation} The correct answer is "
            f"{problem.canonical_answer}, not {injected.ai_final_answer}.",
        ),
        repair=injected.repair,
        debrief=injected.debrief,
        validation_payload={
            "solver": problem.solver,
            "flawed_solver": injected.flawed_solver,
        },
    )


def run_pipeline(
    *,
    subject: str,
    topic: str,
    concept: str,
    difficulty: str = "3",
    desired_failure: str = "hidden assumption",
    mode: ChallengeMode = ChallengeMode.TRUST_OR_CHALLENGE,
    make_correct: bool = False,
    skip_quality: bool = False,
) -> PipelineOutcome:
    """Run one candidate through every gate."""
    # --- stages 1-3: generate -------------------------------------------------
    try:
        challenge = generate_candidate(
            subject=subject,
            topic=topic,
            concept=concept,
            difficulty=difficulty,
            desired_failure=desired_failure,
            mode=mode,
            make_correct=make_correct,
        )
    except AgentError as exc:
        return PipelineOutcome(None, False, "generate", [str(exc)])

    # --- stage 4: deterministic check (cheap, so run it before the critic) ----
    validations = validate_challenge(challenge)
    failed = [v for v in validations if not v.passed]
    if failed:
        return PipelineOutcome(
            challenge,
            False,
            "deterministic_check",
            [f"{v.validator}: {v.detail}" for v in failed],
            validations,
        )
    challenge.validators = [v.validator for v in validations]

    # --- stage 5: independent critique ---------------------------------------
    try:
        verdict = generation.critique(student_view=challenge.student_view())
    except AgentError as exc:
        return PipelineOutcome(challenge, False, "critique", [str(exc)], validations)

    reasons: list[str] = []
    if verdict.unintended_errors:
        # PRD section 75: intentional educational failure must be separable from
        # accidental model error. Any extra error voids the challenge.
        reasons.extend(f"unintended error: {e}" for e in verdict.unintended_errors)
    if verdict.ambiguity_score > settings.max_ambiguity:
        reasons.append(
            f"ambiguity {verdict.ambiguity_score:.2f} exceeds "
            f"{settings.max_ambiguity:.2f}"
        )
    if challenge.contains_failure:
        if not verdict.found_failure:
            reasons.append(
                "critic could not find the planted failure - challenge is unfair"
            )
        elif challenge.failure and verdict.location != challenge.failure.location:
            reasons.append(
                f"critic localised the failure at step {verdict.location}, "
                f"generator claimed step {challenge.failure.location}"
            )
    elif verdict.found_failure:
        reasons.append(
            "challenge is meant to be correct but the critic found a failure at "
            f"step {verdict.location}"
        )

    if reasons:
        return PipelineOutcome(
            challenge, False, "critique", reasons, validations,
            critic_found_failure=verdict.found_failure,
        )

    # --- stage 6: difficulty check (PRD sections 46.7, 68) -------------------
    steps = len(challenge.ai_solution)
    if steps < 2:
        return PipelineOutcome(
            challenge, False, "difficulty_check",
            ["fewer than two reasoning steps leaves nothing to inspect"],
            validations, critic_found_failure=verdict.found_failure,
        )

    # --- stage 7: quality filter ---------------------------------------------
    quality: QualityScore | None = None
    if not skip_quality:
        try:
            quality = generation.score_quality(
                challenge_json=json.dumps(
                    challenge.model_dump(mode="json"), indent=2, ensure_ascii=False
                )
            )
        except AgentError as exc:
            return PipelineOutcome(
                challenge, False, "quality_filter", [str(exc)], validations,
                critic_found_failure=verdict.found_failure,
            )
        challenge.quality_score = quality.total
        if quality.total < settings.quality_threshold:
            return PipelineOutcome(
                challenge, False, "quality_filter",
                [
                    f"quality {quality.total:.2f} below threshold "
                    f"{settings.quality_threshold:.2f}: {quality.notes}"
                ],
                validations, quality, verdict.found_failure,
            )

    # --- stage 8: publishable -------------------------------------------------
    return PipelineOutcome(
        challenge, True, "publish", [], validations, quality, verdict.found_failure
    )
