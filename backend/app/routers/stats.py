"""Evidence Stats, verification skills and achievements.

PRD sections 36.4-36.7, 52-54, 61. Every metric here describes verification
behaviour, never topic mastery - that separation is the product's whole
positioning (PRD sections 1, 59, 110 risk 6).
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.deps import SessionDep, UserDep
from app.engine import calibration
from app.engine import taxonomy
from app.engine.contracts import TRUST_JUDGMENTS, Judgment, TruthState
from app.engine.scoring import (
    MIN_SAMPLE_FOR_RATES,
    SKILL_KEYS,
    JudgmentMatrix,
    skill_from_evidence,
)
from app.models import (
    Achievement,
    Attempt,
    AttemptStatus,
    ChallengeRecord,
    Evaluation,
    EvidenceCardRecord,
    EvidenceSubmission,
)
from app.schemas import StatsResponse

# The verdicts the three-way trust matrix is defined over.
TRUST_JUDGMENT_VALUES = frozenset(j.value for j in TRUST_JUDGMENTS)

router = APIRouter(tags=["stats"])

# PRD section 61.
ACHIEVEMENTS = {
    "first_break": "FIRST BREAK - Find your first AI failure.",
    "edge_case_hunter": "EDGE-CASE HUNTER - Break 10 solutions using edge cases.",
    "the_skeptic": "THE SKEPTIC - Challenge 25 AI claims correctly.",
    "the_judge": "THE JUDGE - Correctly approve 10 valid AI answers.",
    "assumption_checker": "ASSUMPTION CHECKER - Correctly identify 5 artifacts "
    "that could not be settled from the information given.",
    "bug_whisperer": "BUG WHISPERER - Locate the exact first failure 20 times.",
}


def _evaluate_achievements(session, user, stats: dict) -> list[str]:
    """Unlock any newly earned achievements and return all unlocked keys."""
    unlocked = set(
        session.scalars(select(Achievement.key).where(Achievement.user_id == user.id))
    )
    earned = set()
    if stats["failures_found"] >= 1:
        earned.add("first_break")
    if stats["counterexamples"] >= 10:
        earned.add("edge_case_hunter")
    if stats["failures_found"] >= 25:
        earned.add("the_skeptic")
    if stats["correct_approvals"] >= 10:
        earned.add("the_judge")
    if stats["correct_insufficient"] >= 5:
        earned.add("assumption_checker")
    if stats["localised"] >= 20:
        earned.add("bug_whisperer")

    for key in earned - unlocked:
        session.add(Achievement(user_id=user.id, key=key))
    if earned - unlocked:
        session.commit()
    return sorted(earned | unlocked)


@router.get("/stats", response_model=StatsResponse)
def student_stats(session: SessionDep, user: UserDep) -> StatsResponse:
    rows = session.execute(
        select(Attempt, ChallengeRecord)
        .join(ChallengeRecord, Attempt.challenge_pk == ChallengeRecord.id)
        .where(Attempt.user_id == user.id, Attempt.judgment.is_not(None))
    ).all()

    # Only mixed-mode, non-demo attempts count toward trust metrics: guided
    # modes disclose that a failure exists (PRD v0.2 section 3.2).
    #
    # Comparison verdicts are excluded as well. The three-way matrix answers
    # "when the artifact was X, what did the student say" - and "A is right"
    # is not an answer to that question. Counting those attempts would inflate
    # every row total while contributing nothing to any cell, which reads as a
    # collapse in accuracy that never happened.
    eligible = [
        (a, r)
        for a, r in rows
        if a.mixed_mode
        and not a.is_demo
        and a.judgment in TRUST_JUDGMENT_VALUES
    ]
    matrix = JudgmentMatrix.build(
        [(r.truth_state, a.judgment) for a, r in eligible if a.judgment]
    )

    failures_found = correct_approvals = correct_insufficient = 0
    false_alarms = missed = localised = 0
    categories: dict[str, int] = {}
    completed_scores: list[dict] = []

    for attempt, record in rows:
        judgment, truth = attempt.judgment, record.truth_state
        if truth == TruthState.FLAWED:
            if judgment == Judgment.CHALLENGE:
                failures_found += 1
            elif judgment == Judgment.APPROVE:
                missed += 1
        elif truth == TruthState.VALID:
            if judgment == Judgment.APPROVE:
                correct_approvals += 1
            elif judgment == Judgment.CHALLENGE:
                false_alarms += 1
        elif truth == TruthState.INSUFFICIENT_INFORMATION:
            if judgment == Judgment.INSUFFICIENT_INFORMATION:
                correct_insufficient += 1

        if attempt.located_first_failure:
            localised += 1
        if record.failure_category:
            label = taxonomy.label(record.failure_category)
            categories[label] = categories.get(label, 0) + 1
        if attempt.status == AttemptStatus.COMPLETED and attempt.score_breakdown:
            completed_scores.append(attempt.score_breakdown)

    # Skills are attributed per card, so a submission mixing a counterexample
    # and a calculation credits both skills rather than only the first.
    card_rows = session.execute(
        select(EvidenceCardRecord, Evaluation)
        .join(
            EvidenceSubmission,
            EvidenceCardRecord.submission_id == EvidenceSubmission.id,
        )
        .join(Attempt, EvidenceSubmission.attempt_id == Attempt.id)
        .outerjoin(Evaluation, Evaluation.submission_id == EvidenceSubmission.id)
        .where(Attempt.user_id == user.id)
    ).all()

    strong_evidence = session.scalar(
        select(func.count(Evaluation.id))
        .join(
            EvidenceSubmission, Evaluation.submission_id == EvidenceSubmission.id
        )
        .join(Attempt, EvidenceSubmission.attempt_id == Attempt.id)
        .where(Attempt.user_id == user.id, Evaluation.accepted.is_(True))
    ) or 0
    counterexamples = sum(
        1
        for card, ev in card_rows
        if ev is not None
        and ev.accepted
        and card.evidence_type in ("counterexample", "test_case")
    )

    skill_totals: dict[str, list[float]] = {k: [] for k in SKILL_KEYS}
    for card, ev in card_rows:
        skill = skill_from_evidence(card.evidence_type)
        if skill:
            skill_totals[skill].append(ev.strength if ev else 0.0)
    skill_totals["error_localization"].extend(
        [10.0 if a.located_first_failure else 3.0 for a, _ in rows]
    )
    skills = {
        k: round(sum(v) / len(v) * 10, 1) if v else 0.0 for k, v in skill_totals.items()
    }

    components = {k: 0.0 for k in ("initial_judgment", "evidence", "reasoning", "outcome_task")}
    if completed_scores:
        for key in components:
            components[key] = round(
                sum(float(s.get(key, 0) or 0) for s in completed_scores)
                / len(completed_scores),
                1,
            )
    investigation_score = (
        round(
            sum(float(s.get("total", 0) or 0) for s in completed_scores)
            / len(completed_scores),
            1,
        )
        if completed_scores
        else 0.0
    )

    assisted = sum(1 for a, _ in rows if a.assisted)
    independent = sum(
        1
        for a, _ in rows
        if a.status == AttemptStatus.COMPLETED and not a.assisted and a.judged_correctly
    )

    # Calibration reads every judgment that carries a confidence, including
    # comparison verdicts: "how sure were you, and were you right" is a fair
    # question in every mode, unlike the three-way matrix above. The AI's
    # displayed badge comes from the stored body, so an artifact edited since
    # is still scored against what this student actually saw.
    report = calibration.build(
        [
            calibration.Judgment(
                confidence=a.confidence,
                correct=bool(a.judged_correctly),
                ai_confidence=_displayed_confidence(r.body),
                sided_with_ai=a.judgment == Judgment.APPROVE,
                judged_at=a.started_at,
            )
            for a, r in rows
            if not a.is_demo
        ]
    )

    achievements = _evaluate_achievements(
        session,
        user,
        {
            "failures_found": failures_found,
            "correct_approvals": correct_approvals,
            "correct_insufficient": correct_insufficient,
            "counterexamples": counterexamples,
            "localised": localised,
        },
    )

    return StatsResponse(
        claims_investigated=len(rows),
        resolved_mixed_mode=matrix.resolved,
        failures_found=failures_found,
        correct_approvals=correct_approvals,
        correct_insufficient=correct_insufficient,
        false_alarms=false_alarms,
        missed_failures=missed,
        strong_evidence=strong_evidence,
        first_judgment_accuracy=matrix.first_judgment_accuracy,
        false_alarm_rate=matrix.false_alarm_rate,
        missed_failure_rate=matrix.missed_failure_rate,
        judgment_matrix=matrix.as_grid(),
        min_sample=MIN_SAMPLE_FOR_RATES,
        investigation_score=investigation_score,
        score_components=components,
        assisted_attempts=assisted,
        independent_completions=independent,
        streak_days=user.streak_days,
        verification_skills=skills,
        failure_categories=categories,
        achievements=[ACHIEVEMENTS[k] for k in achievements if k in ACHIEVEMENTS],
        calibration=report.as_dict(),
    )


def _displayed_confidence(body: dict) -> int:
    """The confidence badge the artifact showed, louder rival first (Mode G)."""
    competing = body.get("competing") or []
    if competing:
        return max(int(c.get("simulated_confidence", 0)) for c in competing)
    return int(body.get("simulated_confidence") or 0)


@router.get("/history")
def history(session: SessionDep, user: UserDep) -> list[dict]:
    """Recent Breakpoints (PRD section 36.6)."""
    rows = session.execute(
        select(Attempt, ChallengeRecord)
        .join(ChallengeRecord, Attempt.challenge_pk == ChallengeRecord.id)
        .where(Attempt.user_id == user.id)
        .order_by(Attempt.started_at.desc())
        .limit(25)
    ).all()
    return [
        {
            "attempt_id": a.id,
            "challenge_id": r.challenge_id,
            "subject": r.subject,
            "topic": r.topic,
            "subtopic": r.subtopic,
            "difficulty": r.difficulty,
            "question": r.body.get("question", ""),
            "status": a.status,
            "judgment": a.judgment,
            "judged_correctly": a.judged_correctly,
            "score": a.score_total,
            "started_at": a.started_at.isoformat() if a.started_at else None,
        }
        for a, r in rows
    ]
