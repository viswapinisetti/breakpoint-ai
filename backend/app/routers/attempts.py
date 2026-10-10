"""The investigation loop: start, judge, evidence, hints, repair, autopsy.

This router is the product. Two rules are enforced here rather than trusted to
the client:

* nothing that reveals correctness leaves the server before the student commits
  to a judgment (`student_view` plus the checks in `start`);
* a judgment alone never completes an investigation - evidence is required
  (PRD section 110, risk 3).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.agents.client import AgentError
from app.agents.runtime import evaluate_evidence, generate_debrief
from app.deps import SessionDep, UserDep, get_record, load_challenge, touch_streak
from app.engine import calibration
from app.engine import taxonomy
from app.engine import arithmetic
from app.engine import break_tests
from app.engine import evidence as evidence_engine
from app.engine.contracts import (
    COMPARISON_JUDGMENTS,
    Challenge,
    ChallengeMode,
    Judgment,
    TruthState,
)
from app.engine.evidence import EvidenceSubmissionRequest
from app.engine.registry import config_for
from app.engine.scoring import score_attempt
from app.models import (
    AnalyticsEvent,
    Appeal,
    Attempt,
    AttemptStatus,
    ChallengeRecord,
    ContentReport,
    Evaluation,
    EvaluationStatus,
    EvidenceCardRecord,
    EvidenceSubmission,
)
from app.schemas import (
    AppealRequest,
    AppealResponse,
    AutopsyResponse,
    BreakTestRequest,
    BreakTestResponse,
    EvidenceResponse,
    HintResponse,
    JudgeRequest,
    JudgeResponse,
    RepairRequest,
    RepairResponse,
    ReplayStep,
    ReportRequest,
    StartAttemptResponse,
    TransferRequest,
    TransferResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["investigation"])

# Versioned so an evaluation can be reproduced and appealed against the exact
# logic that produced it (PRD v0.2 section 9.2).
EVALUATOR_VERSION = "deterministic-1+llm-1"
RUBRIC_VERSION = "v0.2-investigation-score"


def _get_attempt(session, user, attempt_id: int) -> Attempt:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="attempt not found")
    return attempt


def _challenge_of(session, attempt: Attempt) -> Challenge:
    record = session.get(ChallengeRecord, attempt.challenge_pk)
    if record is None:
        raise HTTPException(status_code=404, detail="challenge missing")
    return load_challenge(record)


def _log(session, user_id: int | None, name: str, **payload) -> None:
    session.add(AnalyticsEvent(user_id=user_id, name=name, payload=payload))


@router.post("/challenges/{challenge_id}/start", response_model=StartAttemptResponse)
def start_attempt(
    challenge_id: str, session: SessionDep, user: UserDep
) -> StartAttemptResponse:
    """Open (or resume) an investigation."""
    record = get_record(session, challenge_id)
    challenge = load_challenge(record)

    attempt = session.scalar(
        select(Attempt)
        .where(
            Attempt.user_id == user.id,
            Attempt.challenge_pk == record.id,
            Attempt.status != AttemptStatus.COMPLETED,
        )
        .order_by(Attempt.id.desc())
    )
    resumed = attempt is not None
    if attempt is None:
        attempt = Attempt(user_id=user.id, challenge_pk=record.id)
        session.add(attempt)
        touch_streak(user)
        _log(session, user.id, "challenge_started", challenge_id=challenge_id)
        session.commit()

    config = config_for(challenge.subject)
    return StartAttemptResponse(
        attempt_id=attempt.id,
        challenge=challenge.student_view(),
        tools=[
            {"key": t.key, "label": t.label, "icon": t.icon}
            for t in (config.tools if config else ())
        ],
        evidence_types=[e.value for e in (config.evidence_types if config else ())],
        max_debate_turns=settings.max_debate_turns,
        hints_used=attempt.hints_used,
        resumed=resumed,
    )


@router.post("/attempts/{attempt_id}/judge", response_model=JudgeResponse)
def judge(
    attempt_id: int, body: JudgeRequest, session: SessionDep, user: UserDep
) -> JudgeResponse:
    """Approve or Challenge (PRD section 29, Mode B).

    Recorded once. Re-judging after seeing the outcome would make the False
    Alarm metric meaningless (PRD section 54).
    """
    attempt = _get_attempt(session, user, attempt_id)
    if attempt.judgment is not None:
        raise HTTPException(status_code=409, detail="judgment already recorded")
    challenge = _challenge_of(session, attempt)
    permitted = challenge.allowed_judgments
    try:
        judgment = Judgment(body.judgment)
    except ValueError:
        judgment = None  # type: ignore[assignment]
    if judgment is None or judgment not in permitted:
        raise HTTPException(
            status_code=422,
            detail=(
                "judgment must be one of "
                + ", ".join(j.value for j in permitted)
                + f" for {challenge.challenge_mode} challenges"
            ),
        ) from None

    correct = judgment == challenge.expected_judgment

    # Localisation only counts when the student named the right step for the
    # right reason. In Mode B that is where validity first breaks; in Mode G it
    # is where the two solutions diverge, which is the harder read.
    located = False
    if correct and body.located_step is not None:
        if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
            divergence = challenge.comparison.divergence_step if challenge.comparison else None
            located = divergence is not None and body.located_step == divergence
        elif judgment == Judgment.CHALLENGE and challenge.failure is not None:
            located = body.located_step == challenge.failure.location

    attempt.judgment = judgment.value
    attempt.judged_correctly = correct
    attempt.confidence = body.confidence
    attempt.located_step = body.located_step
    attempt.located_first_failure = located
    attempt.status = AttemptStatus.JUDGMENT_RESOLVED
    # Guided modes disclose that a failure exists, so exclude them from
    # mixed-mode trust metrics (PRD v0.2 section 3.2).
    attempt.mixed_mode = challenge.challenge_mode != "find_the_failure"

    message = _judgment_message(judgment, correct)

    # Calibration comments on the student's certainty, not their answer: an
    # approval that agrees with a loud, wrong AI is the failure this product
    # exists to train, and it is worth naming the moment it happens.
    ai_confidence = _displayed_confidence(challenge)
    note = calibration.judgment_note(
        confidence=body.confidence,
        correct=correct,
        ai_confidence=ai_confidence,
        sided_with_ai=judgment == Judgment.APPROVE,
    )

    _log(
        session,
        user.id,
        "judgment_recorded",
        challenge_id=challenge.id,
        judgment=judgment.value,
        truth_state=challenge.truth_state.value,
        correct=correct,
        located_first_failure=located,
        mixed_mode=attempt.mixed_mode,
        confidence=body.confidence,
        ai_confidence=ai_confidence,
    )
    session.commit()

    return JudgeResponse(
        correct=correct,
        truth_state=challenge.truth_state.value,
        located_first_failure=located,
        message=message,
        requires_evidence=True,
        outcome_task=_outcome_task_for(challenge),
        confidence=body.confidence,
        ai_confidence=ai_confidence,
        calibration_note=note,
    )


def _displayed_confidence(challenge: Challenge) -> int:
    """The confidence badge the student actually saw.

    Which-AI-Is-Wrong shows two badges, so the louder one is the number that
    could have swayed the verdict.
    """
    if challenge.competing:
        return max(c.simulated_confidence for c in challenge.competing)
    return challenge.simulated_confidence


_COMPARISON_MESSAGE: dict[Judgment, tuple[str, str]] = {
    Judgment.A_CORRECT: (
        "Verdict recorded. Now show where B goes wrong.",
        "Verdict recorded. Submit the evidence you think settles it between A and B.",
    ),
    Judgment.B_CORRECT: (
        "Verdict recorded. Now show where A goes wrong.",
        "Verdict recorded. Submit the evidence you think settles it between A and B.",
    ),
    Judgment.BOTH_CORRECT: (
        "Verdict recorded. Show why two different-looking routes reach the same "
        "valid answer.",
        "Verdict recorded. Show what you checked in each solution.",
    ),
    Judgment.NEITHER_CORRECT: (
        "Verdict recorded. Now show the failure in each of them - two, not one.",
        "Verdict recorded. Show the failure you found in each solution.",
    ),
    Judgment.UNDERDETERMINED: (
        "Verdict recorded. Name the missing fact and show that it decides which "
        "solution is right.",
        "Verdict recorded. Show why the supplied facts cannot separate A from B.",
    ),
}


def _judgment_message(judgment: Judgment, correct: bool) -> str:
    """Feedback that never implies the score, only the next step."""
    if judgment in COMPARISON_JUDGMENTS:
        right, wrong = _COMPARISON_MESSAGE[judgment]
        return right if correct else wrong
    if judgment == Judgment.CHALLENGE:
        return (
            "Challenge recorded. Now prove it - submit the evidence that "
            "establishes the failure."
            if correct
            else "Challenge recorded. Submit the evidence you believe breaks "
            "this artifact, and we will check it."
        )
    if judgment == Judgment.APPROVE:
        return (
            "Approval recorded. Justify it - show what you checked and why the "
            "reasoning holds for the stated scope."
            if correct
            else "Approval recorded. Record what you checked and why you were "
            "satisfied."
        )
    return (
        "Recorded. Now name the missing information and show why it changes the "
        "answer."
        if correct
        else "Recorded. Show which fact is missing and why the supplied "
        "information cannot settle the claim."
    )


_COMPARISON_OUTCOME: dict[Judgment, str] = {
    Judgment.A_CORRECT: "repair",
    Judgment.B_CORRECT: "repair",
    Judgment.NEITHER_CORRECT: "repair",
    Judgment.BOTH_CORRECT: "justify",
    Judgment.UNDERDETERMINED: "clarify",
}


def _outcome_task_for(challenge: Challenge) -> str:
    """PRD v0.2 section 5.2 - the task branches on what was actually true.

    Break-the-Tests replaces the written outcome task with an executable one:
    the student's own failing test is the artifact they have to produce.
    """
    if challenge.challenge_mode == ChallengeMode.BREAK_THE_TESTS:
        return "break_tests"
    if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
        return _COMPARISON_OUTCOME[challenge.expected_judgment]
    return {
        TruthState.FLAWED: "repair",
        TruthState.VALID: "justify",
        TruthState.INSUFFICIENT_INFORMATION: "clarify",
    }[challenge.truth_state]


@router.post("/attempts/{attempt_id}/evidence", response_model=EvidenceResponse)
def submit_evidence(
    attempt_id: int,
    body: EvidenceSubmissionRequest,
    session: SessionDep,
    user: UserDep,
) -> EvidenceResponse:
    """Submit 1-5 typed evidence cards as one immutable revision.

    Runs the validation hierarchy in the order PRD v0.2 section 9.1 sets out:
    structure, then deterministic checks, then relevance and rubric. Two rules
    from section 9.2 are enforced here rather than left to the model:

      * deterministic FAILURE is final - a fluent explanation cannot talk the
        evaluator out of arithmetic that does not check out;
      * deterministic SUCCESS is necessary but not sufficient - a correct
        calculation still has to be shown relevant to the judgment.
    """
    attempt = _get_attempt(session, user, attempt_id)
    if attempt.judgment is None:
        raise HTTPException(
            status_code=409, detail="record a judgment before submitting evidence"
        )

    # Idempotency: a retried request returns the original outcome rather than
    # creating a second revision (PRD v0.2 section 13.3).
    existing = session.scalar(
        select(EvidenceSubmission).where(
            EvidenceSubmission.attempt_id == attempt.id,
            EvidenceSubmission.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None and existing.evaluation is not None:
        return _evidence_response(existing.evaluation, existing.revision, replayed=True)

    challenge = _challenge_of(session, attempt)
    config = config_for(challenge.subject)
    allowed = {e.value for e in (config.evidence_types if config else ())}

    # --- stage 1 + 2: structure, then deterministic checks -----------------
    outcome = evidence_engine.validate(
        body.cards,
        step_count=challenge.step_count,
        allowed_types=allowed,
    )
    if outcome.has_structural_errors:
        # Malformed evidence is a 422, not a wrong answer: nothing is recorded
        # against the learner for a form they have not finished filling in.
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This submission is not complete enough to evaluate.",
                "errors": outcome.structural_errors,
            },
        )

    revision = (
        session.scalar(
            select(func.coalesce(func.max(EvidenceSubmission.revision), 0)).where(
                EvidenceSubmission.attempt_id == attempt.id
            )
        )
        or 0
    ) + 1
    record = session.get(ChallengeRecord, attempt.challenge_pk)
    submission = EvidenceSubmission(
        attempt_id=attempt.id,
        revision=revision,
        idempotency_key=body.idempotency_key,
        challenge_version=record.version if record else 1,
    )
    session.add(submission)
    session.flush()
    for i, card in enumerate(body.cards, 1):
        session.add(
            EvidenceCardRecord(
                submission_id=submission.id,
                ordinal=i,
                evidence_type=card.type,
                references_step=card.references_step,
                payload=card.model_dump(exclude={"why_supports"}),
                why_supports=card.why_supports,
            )
        )

    checks = [c.as_dict() for c in outcome.checks]
    failures = outcome.deterministic_failures

    # Deterministic failure short-circuits: no model call, no ambiguity.
    if failures:
        evaluation = Evaluation(
            submission_id=submission.id,
            status=EvaluationStatus.NEEDS_REVISION,
            reason_code=failures[0].reason_code,
            feedback=" ".join(f.detail for f in failures),
            missing="Correct the checks above and resubmit.",
            accepted=False,
            strength=0.0,
            deterministic_checks=checks,
            evaluator_version=EVALUATOR_VERSION,
            rubric_version=RUBRIC_VERSION,
        )
        session.add(evaluation)
        attempt.status = AttemptStatus.NEEDS_REVISION
        _log(
            session,
            user.id,
            "evidence_submitted",
            challenge_id=challenge.id,
            revision=revision,
            status=evaluation.status,
            reason_code=evaluation.reason_code,
        )
        session.commit()
        return _evidence_response(evaluation, revision)

    # Contradictory cards get clarification rather than a silent pick.
    conflict = evidence_engine.detect_conflicts(body.cards)
    if conflict:
        evaluation = Evaluation(
            submission_id=submission.id,
            status=EvaluationStatus.NEEDS_REVISION,
            reason_code="cards_conflict",
            feedback=conflict,
            missing="Make your cards agree on what you are claiming.",
            accepted=False,
            deterministic_checks=checks,
            evaluator_version=EVALUATOR_VERSION,
            rubric_version=RUBRIC_VERSION,
        )
        session.add(evaluation)
        attempt.status = AttemptStatus.NEEDS_REVISION
        session.commit()
        return _evidence_response(evaluation, revision)

    # --- stage 3 + 4: relevance and rubric ---------------------------------
    rendered = "\n".join(f"{i}. {c.summary()}" for i, c in enumerate(body.cards, 1))
    primary = body.cards[0]
    try:
        assessment = evaluate_evidence(
            challenge=challenge,
            evidence_type=primary.type,
            references_step=primary.references_step,
            content=rendered,
        )
        status = (
            EvaluationStatus.SUPPORTED
            if assessment.is_strong
            else EvaluationStatus.NEEDS_REVISION
        )
        reason_code = "evidence_supported" if assessment.is_strong else "insufficient"
    except AgentError as exc:
        # Stage 5: a service failure parks the submission for review. It must
        # never be recorded as a wrong answer (PRD v0.2 sections 5.3, 13.3).
        logger.warning("evidence evaluation unavailable: %s", exc)
        evaluation = Evaluation(
            submission_id=submission.id,
            status=EvaluationStatus.REVIEW_PENDING,
            reason_code="evaluator_unavailable",
            feedback=(
                "Your evidence is saved. Automatic evaluation is unavailable, so "
                "this submission is queued for review - it is not marked wrong."
            ),
            accepted=False,
            deterministic_checks=checks,
            evaluator_version=EVALUATOR_VERSION,
            rubric_version=RUBRIC_VERSION,
        )
        session.add(evaluation)
        attempt.status = AttemptStatus.REVIEW_PENDING
        session.commit()
        return _evidence_response(evaluation, revision)

    evaluation = Evaluation(
        submission_id=submission.id,
        status=status,
        reason_code=reason_code,
        feedback=assessment.feedback,
        missing=assessment.missing,
        accepted=assessment.is_strong,
        strength=assessment.strength,
        reasoning_quality=float(assessment.reasoning_quality),
        criterion_results={
            "correctness": assessment.correctness,
            "specificity": assessment.specificity,
            "relevance": assessment.relevance,
            "completeness": assessment.completeness,
            "reproducibility": assessment.reproducibility,
            "reasoning_quality": assessment.reasoning_quality,
        },
        deterministic_checks=checks,
        evaluator_version=EVALUATOR_VERSION,
        rubric_version=RUBRIC_VERSION,
    )
    session.add(evaluation)

    # Keep the student's best established argument.
    if assessment.strength > attempt.evidence_strength:
        attempt.evidence_strength = assessment.strength
        attempt.reasoning_quality = float(assessment.reasoning_quality)
    attempt.evidence_accepted = attempt.evidence_accepted or assessment.is_strong
    attempt.status = (
        AttemptStatus.JUDGMENT_RESOLVED
        if assessment.is_strong
        else AttemptStatus.NEEDS_REVISION
    )

    _log(
        session,
        user.id,
        "evidence_submitted",
        challenge_id=challenge.id,
        revision=revision,
        cards=len(body.cards),
        status=status,
        strength=assessment.strength,
    )
    session.commit()
    return _evidence_response(evaluation, revision)


def _evidence_response(
    evaluation: Evaluation, revision: int, *, replayed: bool = False
) -> EvidenceResponse:
    """Render an evaluation for the client.

    `checks_passed` is reported separately from `accepted` because PRD v0.2
    section 6.4 requires the UI to distinguish "Calculation checked" from
    "Evidence supports your claim" - passing arithmetic is not the same as
    having made an argument.
    """
    checks = evaluation.deterministic_checks or []
    ran = [c for c in checks if c.get("status") != "not_applicable"]
    return EvidenceResponse(
        revision=revision,
        status=evaluation.status,
        accepted=evaluation.accepted,
        strength=evaluation.strength,
        feedback=evaluation.feedback,
        missing=evaluation.missing,
        reason_code=evaluation.reason_code,
        dimensions=evaluation.criterion_results or {},
        checks=checks,
        checks_passed=bool(ran) and all(c["status"] == "passed" for c in ran),
        replayed=replayed,
    )


@router.post("/attempts/{attempt_id}/hint", response_model=HintResponse)
def next_hint(attempt_id: int, session: SessionDep, user: UserDep) -> HintResponse:
    """Reveal the next rung of the hint ladder (PRD section 40)."""
    attempt = _get_attempt(session, user, attempt_id)
    challenge = _challenge_of(session, attempt)
    if attempt.hints_used >= len(challenge.hints):
        raise HTTPException(status_code=409, detail="no further hints available")

    hint = challenge.hints[attempt.hints_used]
    attempt.hints_used += 1
    if hint.kind == "reveal":
        attempt.revealed = True
        attempt.assisted = True
    _log(
        session,
        user.id,
        "hint_used",
        challenge_id=challenge.id,
        level=hint.level,
    )
    session.commit()
    return HintResponse(
        level=hint.level,
        kind=hint.kind,
        text=hint.text,
        hints_used=attempt.hints_used,
        hints_remaining=len(challenge.hints) - attempt.hints_used,
    )


@router.post("/attempts/{attempt_id}/repair", response_model=RepairResponse)
def submit_repair(
    attempt_id: int, body: RepairRequest, session: SessionDep, user: UserDep
) -> RepairResponse:
    """Repair the flawed artifact (PRD section 29, Mode D)."""
    attempt = _get_attempt(session, user, attempt_id)
    challenge = _challenge_of(session, attempt)

    if challenge.challenge_mode == ChallengeMode.BREAK_THE_TESTS:
        # The outcome task here is an executable test, not prose. Accepting
        # a written repair would let a student score the outcome band without
        # ever producing the artifact the mode exists to teach.
        raise HTTPException(
            status_code=409,
            detail="this challenge's outcome task is a failing test - "
            "use POST /attempts/{attempt_id}/test",
        )

    attempt.repair_text = body.repair
    attempt.repair_attempted = True
    attempt.status = AttemptStatus.OUTCOME_TASK

    if challenge.truth_state == TruthState.VALID:
        # Justification, not repair: the artifact is correct, and inventing a
        # correction would teach the wrong lesson (PRD v0.2 section 5.2).
        attempt.repair_accepted = True
        session.commit()
        return RepairResponse(
            accepted=True,
            strength=10.0,
            feedback=(
                "Recorded. This artifact was valid, so the task was to justify "
                "approval rather than change anything."
            ),
            reference_repair="",
        )

    if challenge.truth_state == TruthState.INSUFFICIENT_INFORMATION:
        attempt.repair_accepted = True
        session.commit()
        return RepairResponse(
            accepted=True,
            strength=10.0,
            feedback=(
                "Recorded. The supplied facts could not settle this claim; the "
                "task was to name what was missing."
            ),
            reference_repair=challenge.missing_information,
        )

    try:
        assessment = evaluate_evidence(
            challenge=challenge,
            evidence_type="rewrite",
            references_step=challenge.failure.location if challenge.failure else None,
            content=(
                "The student proposes the following correction to the flawed step:\n"
                f"{body.repair}\n\n"
                "Judge whether this correction actually fixes the identified failure "
                "and yields the correct result."
            ),
        )
    except AgentError as exc:
        logger.warning("repair evaluation unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="Repair evaluation is temporarily unavailable."
        ) from exc

    attempt.repair_accepted = assessment.is_strong

    _log(
        session,
        user.id,
        "repair_submitted",
        challenge_id=challenge.id,
        accepted=assessment.is_strong,
    )
    session.commit()

    return RepairResponse(
        accepted=assessment.is_strong,
        strength=assessment.strength,
        feedback=assessment.feedback,
        reference_repair=challenge.repair if assessment.is_strong else "",
    )


MAX_TEST_SUBMISSIONS = 25


@router.post("/attempts/{attempt_id}/test", response_model=BreakTestResponse)
def break_the_tests(
    attempt_id: int, body: BreakTestRequest, session: SessionDep, user: UserDep
) -> BreakTestResponse:
    """Submit a test input that should expose the failure (Mode F).

    Repeated submissions are allowed and expected: narrowing an input space by
    elimination is the skill being practised, and each rejected input tells the
    student something. Only the judgment is one-shot.
    """
    attempt = _get_attempt(session, user, attempt_id)
    challenge = _challenge_of(session, attempt)

    if challenge.challenge_mode != ChallengeMode.BREAK_THE_TESTS:
        raise HTTPException(
            status_code=409, detail="this challenge does not take test submissions"
        )
    if attempt.judgment is None:
        raise HTTPException(
            status_code=409, detail="record a judgment before submitting a test"
        )
    if attempt.test_submissions >= MAX_TEST_SUBMISSIONS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You have tried {MAX_TEST_SUBMISSIONS} inputs. Take a hint and "
                "reason about which case the suite never covers, rather than "
                "enumerating inputs."
            ),
        )

    try:
        verdict = break_tests.evaluate_test(challenge, body.test_input)
    except ValueError as exc:
        # An authoring fault in the challenge, not a student error.
        logger.error("break_the_tests challenge %s is malformed: %s", challenge.id, exc)
        raise HTTPException(
            status_code=500, detail="This challenge is misconfigured; it has been logged."
        ) from exc

    attempt.test_submissions += 1
    if verdict.reason_code != "execution_error":
        attempt.test_input = verdict.normalised_input or body.test_input
    if body.rationale:
        attempt.repair_text = body.rationale
    attempt.status = AttemptStatus.OUTCOME_TASK
    # Outcome credit is sticky: once a student has produced a breaking test,
    # continuing to explore must not cost them the band they already earned.
    attempt.repair_attempted = True
    if verdict.accepted:
        attempt.test_broke_suite = True
        attempt.repair_accepted = True

    _log(
        session,
        user.id,
        "test_submitted",
        challenge_id=challenge.id,
        reason_code=verdict.reason_code,
        accepted=verdict.accepted,
        submissions=attempt.test_submissions,
    )
    session.commit()

    return BreakTestResponse(
        accepted=verdict.accepted,
        reason_code=verdict.reason_code,
        message=verdict.message,
        normalised_input=verdict.normalised_input,
        shipped_result=verdict.shipped_result,
        correct_result=verdict.correct_result,
        submissions=attempt.test_submissions,
    )


@router.post("/attempts/{attempt_id}/complete", response_model=AutopsyResponse)
def complete(attempt_id: int, session: SessionDep, user: UserDep) -> AutopsyResponse:
    """Finish the investigation: Failure Replay, Autopsy and score."""
    attempt = _get_attempt(session, user, attempt_id)
    if attempt.judgment is None:
        raise HTTPException(
            status_code=409, detail="investigation requires a judgment first"
        )
    challenge = _challenge_of(session, attempt)

    # Assistance flags the attempt rather than deducting points; a revealed
    # answer excludes it from independent-success metrics (PRD v0.2 10.1).
    attempt.assisted = attempt.revealed or attempt.hints_used >= 3
    breakdown = score_attempt(
        initial_judgment_correct=bool(attempt.judged_correctly),
        evidence_strength=attempt.evidence_strength,
        evidence_accepted=attempt.evidence_accepted,
        reasoning_quality=attempt.reasoning_quality,
        outcome_attempted=attempt.repair_attempted,
        outcome_accepted=attempt.repair_accepted,
        assisted=attempt.assisted,
    )
    attempt.score_breakdown = breakdown.as_dict()
    attempt.score_total = float(breakdown.total)
    attempt.status = AttemptStatus.COMPLETED
    attempt.completed_at = datetime.now(UTC)

    first_failure = challenge.failure.location if challenge.failure else None
    if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
        replay = _comparison_replay(challenge)
    else:
        replay = [
            ReplayStep(
                index=s.index,
                text=s.text,
                status=(
                    "first_failure"
                    if first_failure is not None and s.index == first_failure
                    else "derived"
                    if first_failure is not None and s.index > first_failure
                    else "valid"
                ),
            )
            for s in challenge.ai_solution
        ]

    # Personalised autopsy, falling back to the reviewed debrief so the student
    # is never left without an explanation (PRD section 43).
    summary = (
        f"Judged {attempt.judgment} ({'correct' if attempt.judged_correctly else 'incorrect'}); "
        f"evidence strength {attempt.evidence_strength:.1f}/10; "
        f"{attempt.hints_used} hints; {attempt.debate_turns} debate turns; "
        f"repair {'accepted' if attempt.repair_accepted else 'not accepted'}."
    )
    if challenge.challenge_mode == ChallengeMode.BREAK_THE_TESTS:
        summary += (
            f" Tried {attempt.test_submissions} test input(s); "
            + (
                f"{attempt.test_input} broke the suite."
                if attempt.test_broke_suite
                else "none of them separated the implementations."
            )
        )
    debrief = challenge.debrief
    try:
        debrief = generate_debrief(challenge=challenge, student_summary=summary)
    except AgentError as exc:
        logger.info("using pre-generated debrief: %s", exc)

    if challenge.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
        counterfactual = _comparison_counterfactual(challenge)
    elif first_failure is not None:
        counterfactual = (
            f"If the assumption introduced at step {first_failure} actually held, "
            f"every later step would follow and the answer would be "
            f"{challenge.ai_final_answer}. It does not hold, so the correct "
            f"answer is {challenge.canonical_answer}."
        )
    elif challenge.truth_state == TruthState.INSUFFICIENT_INFORMATION:
        scenarios = "; ".join(challenge.resolving_scenarios) or "different readings"
        counterfactual = (
            "Each of these readings is consistent with everything you were given, "
            f"and they disagree: {scenarios}. That disagreement is the proof that "
            "the supplied facts cannot settle the claim."
        )
    else:
        counterfactual = (
            "The reasoning holds at every step, so there is no counterfactual to run."
        )

    _log(
        session,
        user.id,
        "investigation_completed",
        challenge_id=challenge.id,
        score=breakdown.total,
    )
    session.commit()

    return AutopsyResponse(
        challenge_id=challenge.id,
        truth_state=challenge.truth_state.value,
        missing_information=challenge.missing_information,
        resolving_scenarios=challenge.resolving_scenarios,
        assisted=attempt.assisted,
        answer_coincidentally_correct=challenge.answer_coincidentally_correct,
        failure_category=challenge.failure.category if challenge.failure else "",
        failure_label=(
            taxonomy.label(challenge.failure.category) if challenge.failure else ""
        ),
        failure_location=first_failure,
        misconception=challenge.failure.misconception if challenge.failure else "",
        why_convincing=challenge.failure.why_convincing if challenge.failure else "",
        first_failure_step=first_failure,
        replay=replay,
        canonical_solution=challenge.canonical_solution,
        canonical_answer=challenge.canonical_answer,
        ai_final_answer=challenge.ai_final_answer,
        repair=challenge.repair,
        debrief=debrief,
        counterexamples=challenge.counterexamples,
        score=breakdown.as_dict(),
        hints_used=attempt.hints_used,
        debate_turns=attempt.debate_turns,
        counterfactual=counterfactual,
        transfer_question=(
            challenge.transfer_check.question if challenge.transfer_check else ""
        ),
        comparison_verdict=(
            challenge.comparison.verdict.value if challenge.comparison else ""
        ),
        divergence_step=(
            challenge.comparison.divergence_step if challenge.comparison else None
        ),
        comparison_explanation=(
            challenge.comparison.explanation if challenge.comparison else ""
        ),
        test_input=attempt.test_input,
        test_submissions=attempt.test_submissions,
        test_broke_suite=attempt.test_broke_suite,
    )


def _comparison_replay(challenge: Challenge) -> list[ReplayStep]:
    """Replay both rival solutions side by side (Mode G).

    Steps are marked `divergence` from the point where the two solutions part
    company, in both solutions. Marking only one of them would give away which
    one the student should have distrusted, and the debrief has not made that
    argument yet.
    """
    divergence = challenge.comparison.divergence_step if challenge.comparison else None
    steps: list[ReplayStep] = []
    for solution in challenge.competing:
        for step in solution.ai_solution:
            steps.append(
                ReplayStep(
                    index=step.index,
                    text=step.text,
                    status=(
                        "divergence"
                        if divergence is not None and step.index == divergence
                        else "derived"
                        if divergence is not None and step.index > divergence
                        else "valid"
                    ),
                    solution=solution.label.upper(),
                )
            )
    return steps


def _comparison_counterfactual(challenge: Challenge) -> str:
    """What the divergence actually turned on (Mode G)."""
    if challenge.comparison is None:  # pragma: no cover - validator prevents this
        return ""
    verdict = challenge.comparison.verdict
    where = (
        f"They part company at step {challenge.comparison.divergence_step}. "
        if challenge.comparison.divergence_step
        else ""
    )
    tail = {
        Judgment.A_CORRECT: "A survives that step and B does not.",
        Judgment.B_CORRECT: "B survives that step and A does not.",
        Judgment.BOTH_CORRECT: (
            "Both survive it: the two routes differ in method, not in validity, "
            "which is why confident disagreement is not evidence of error."
        ),
        Judgment.NEITHER_CORRECT: (
            "Neither survives it. Two confident answers can both be wrong, and "
            "picking the more fluent one is not investigation."
        ),
        Judgment.UNDERDETERMINED: (
            "Which one survives depends on a fact you were never given, so the "
            "honest verdict is that it cannot be decided from this."
        ),
    }[verdict]
    return f"{where}{tail} The correct answer is {challenge.canonical_answer}."


@router.post("/challenges/{challenge_id}/report", status_code=202)
def report_challenge(
    challenge_id: str, body: ReportRequest, session: SessionDep, user: UserDep
) -> dict[str, str]:
    """Student challenge report (PRD section 109)."""
    record = get_record(session, challenge_id)
    session.add(
        ContentReport(
            challenge_pk=record.id,
            user_id=user.id,
            reason=body.reason,
            detail=body.detail,
        )
    )
    _log(session, user.id, "challenge_reported", challenge_id=challenge_id,
         reason=body.reason)
    session.commit()
    return {"status": "received"}


@router.post("/attempts/{attempt_id}/appeal", response_model=AppealResponse, status_code=202)
def request_review(
    attempt_id: int, body: AppealRequest, session: SessionDep, user: UserDep
) -> AppealResponse:
    """Request human review of an evaluation (PRD v0.2 section 9.4).

    A pending appeal must not count as a wrong judgment and must not block the
    learner from starting another investigation, so this records the request
    and returns - it changes no score.
    """
    attempt = _get_attempt(session, user, attempt_id)
    open_already = session.scalar(
        select(Appeal).where(
            Appeal.attempt_id == attempt.id, Appeal.status == "open"
        )
    )
    if open_already is not None:
        return AppealResponse(
            id=open_already.id,
            status=open_already.status,
            message="A review is already open for this investigation.",
        )

    submission_id = body.submission_id
    if submission_id is None:
        latest = session.scalar(
            select(EvidenceSubmission)
            .where(EvidenceSubmission.attempt_id == attempt.id)
            .order_by(EvidenceSubmission.revision.desc())
        )
        submission_id = latest.id if latest else None

    appeal = Appeal(
        attempt_id=attempt.id,
        submission_id=submission_id,
        user_id=user.id,
        reason=body.reason,
    )
    session.add(appeal)
    attempt.status = AttemptStatus.REVIEW_PENDING
    _log(session, user.id, "appeal_opened", attempt_id=attempt.id)
    session.commit()
    return AppealResponse(
        id=appeal.id,
        status=appeal.status,
        message=(
            "Sent for review with your exact submission and the evaluator's "
            "reasoning. This does not count as a wrong judgment, and you can "
            "start another investigation while it is open."
        ),
    )


@router.post("/attempts/{attempt_id}/transfer", response_model=TransferResponse)
def transfer_check(
    attempt_id: int, body: TransferRequest, session: SessionDep, user: UserDep
) -> TransferResponse:
    """A short check on new values after the debrief (PRD v0.2 sections 5.2, 8.3).

    Scored separately from the attempt: this measures whether the idea
    transferred, not how well the original investigation went.
    """
    attempt = _get_attempt(session, user, attempt_id)
    challenge = _challenge_of(session, attempt)
    transfer = challenge.transfer_check
    if transfer is None:
        raise HTTPException(
            status_code=404, detail="this challenge has no transfer check"
        )

    correct = arithmetic.values_agree(body.answer, transfer.answer)
    attempt.transfer_submitted = True
    attempt.transfer_correct = correct
    _log(
        session,
        user.id,
        "transfer_submitted",
        challenge_id=challenge.id,
        correct=correct,
    )
    session.commit()
    return TransferResponse(
        correct=correct,
        expected=transfer.answer,
        message=transfer.explanation
        if correct
        else f"Not quite - the answer is {transfer.answer}. {transfer.explanation}",
    )
