"""Challenge Studio - the content developer's surface.

PRD sections 55-58, 76, 80, 108, 109. Content teams create challenges by
describing what they want and reviewing what survives, rather than authoring
every interaction by hand.

Nothing here serves students. The student routers only ever read PUBLISHED
rows, so a mistake in review cannot leak an unvetted challenge into the app.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from sqlalchemy import func, select

from app.agents.client import (
    AgentError,
    drain_run_log,
    is_configured,
    provider_status,
)
from app.config import settings
from app.db import SessionLocal
from app.deps import SessionDep, StaffDep, get_record
from app.engine import taxonomy
from app.engine.contracts import Challenge, ChallengeMode
from app.engine.registry import all_configs, config_for
from app.governance import (
    ALLOWED_TRANSITIONS,
    GovernanceError,
    apply_edit,
    transition,
)
from app.models import (
    Appeal,
    Attempt,
    AttemptStatus,
    ChallengeRecord,
    ChallengeStatus,
    ChallengeTemplate,
    ChallengeVersion,
    ContentReport,
    Evaluation,
    EvaluationStatus,
    EvidenceCardRecord,
    EvidenceSubmission,
    GenerationJob,
    ModelRun,
    Validation,
)
from app.pipeline import run_pipeline
from app.subjects.topics import validate_topic
from app.schemas import (
    AdminChallengeDetail,
    AdminChallengeRow,
    EditChallengeRequest,
    GenerateRequest,
    GenerationJobView,
    QueueCounts,
    ResolveReviewRequest,
    ReviewItem,
    StudioAnalytics,
    TemplateRequest,
    TemplateView,
    TransitionRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["challenge-studio"])


# --- generation ------------------------------------------------------------


def _run_generation_job(job_id: int, params: dict) -> None:
    """Execute a generation job. Runs in a background thread with its own session.

    Each surviving candidate is written as GENERATED -> AUTO_VALIDATED (the
    pipeline already ran the deterministic check), so it lands in the review
    queue rather than in front of students.
    """
    session = SessionLocal()
    try:
        job = session.get(GenerationJob, job_id)
        if job is None:
            return
        job.status = "running"
        session.commit()

        rotation = [
            "hidden assumption",
            "wrong shortcut",
            "calculation trap",
            "interpretation trap",
            "rule misapplication",
        ]
        funnel: list[dict] = []
        survived = rejected = 0

        for i in range(params["count"]):
            failure = params.get("desired_failure") or rotation[i % len(rotation)]
            try:
                outcome = run_pipeline(
                    subject=params["subject"],
                    topic=params["topic"],
                    concept=params["concept"],
                    difficulty=params["difficulty"],
                    desired_failure=failure,
                    mode=ChallengeMode(params["challenge_mode"]),
                    make_correct=params["make_correct"],
                )
            except AgentError as exc:
                rejected += 1
                funnel.append(
                    {"index": i + 1, "stage": "generate", "reasons": [str(exc)]}
                )
                continue

            if outcome.published and outcome.challenge:
                survived += 1
                ch = outcome.challenge
                record = ChallengeRecord(
                    challenge_id=ch.id,
                    subject=ch.subject,
                    topic=ch.topic,
                    subtopic=ch.subtopic,
                    difficulty=ch.difficulty.value,
                    challenge_mode=ch.challenge_mode.value,
                    artifact_type=ch.artifact_type,
                    truth_state=ch.truth_state.value,
                    failure_category=ch.failure.category if ch.failure else "",
                    status=ChallengeStatus.AUTO_VALIDATED,
                    quality_score=ch.quality_score,
                    body=ch.model_dump(mode="json"),
                    critic_summary={
                        "critic_found_failure": outcome.critic_found_failure,
                        "quality": outcome.quality.model_dump()
                        if outcome.quality
                        else None,
                    },
                )
                session.add(record)
                session.flush()
                for r in outcome.validations:
                    session.add(
                        Validation(
                            challenge_pk=record.id,
                            validator=r.validator,
                            passed=r.passed,
                            detail=r.detail,
                        )
                    )
                funnel.append(
                    {
                        "index": i + 1,
                        "stage": "publish",
                        "challenge_id": ch.id,
                        "quality": ch.quality_score,
                        "reasons": [],
                    }
                )
            else:
                rejected += 1
                funnel.append(
                    {
                        "index": i + 1,
                        "stage": outcome.stage,
                        "reasons": outcome.reasons,
                    }
                )
            session.commit()

        for run in drain_run_log():
            session.add(
                ModelRun(
                    agent=run.agent,
                    provider=run.provider,
                    model=run.model,
                    input_tokens=run.input_tokens,
                    output_tokens=run.output_tokens,
                    cache_read_tokens=run.cache_read_tokens,
                    latency_ms=run.latency_ms,
                    ok=run.ok,
                    error=run.error,
                )
            )

        job = session.get(GenerationJob, job_id)
        if job is not None:
            job.status = "completed"
            job.survived = survived
            job.rejected = rejected
            job.funnel = funnel
            job.finished_at = datetime.now(UTC)
        session.commit()
    except Exception as exc:  # keep the job row truthful on unexpected failure
        logger.exception("generation job %s failed", job_id)
        session.rollback()
        job = session.get(GenerationJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.finished_at = datetime.now(UTC)
            session.commit()
    finally:
        session.close()


@router.post("/generate", response_model=GenerationJobView, status_code=202)
def start_generation(
    body: GenerateRequest,
    background: BackgroundTasks,
    session: SessionDep,
    staff: StaffDep,
) -> GenerationJobView:
    """Queue a generation run (PRD section 56).

    The request is checked before the provider: a malformed request is wrong
    whether or not a model is available, and every candidate generated under
    an unregistered topic would only die at the deterministic check after
    four paid model calls.
    """
    if config_for(body.subject) is None:
        raise HTTPException(status_code=404, detail=f"unknown subject {body.subject}")
    topic_check = validate_topic(body.subject, body.topic)
    if not topic_check.passed:
        raise HTTPException(status_code=422, detail=topic_check.detail)
    if body.count > settings.max_generation_batch:
        raise HTTPException(
            status_code=422,
            detail=f"count exceeds max batch of {settings.max_generation_batch}",
        )
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Generation needs an AI provider. Set "
                "BREAKPOINT_OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) in "
                "backend/.env and restart the API."
            ),
        )

    params = body.model_dump()
    job = GenerationJob(
        status="queued",
        params=params,
        requested=body.count,
        created_by=staff,
    )
    session.add(job)
    session.commit()

    background.add_task(_run_generation_job, job.id, params)
    return _job_view(job)


def _job_view(job: GenerationJob) -> GenerationJobView:
    return GenerationJobView(
        id=job.id,
        status=job.status,
        params=job.params,
        requested=job.requested,
        survived=job.survived,
        rejected=job.rejected,
        funnel=job.funnel or [],
        error=job.error,
        created_by=job.created_by,
        created_at=job.created_at.isoformat() if job.created_at else "",
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


@router.get("/jobs", response_model=list[GenerationJobView])
def list_jobs(session: SessionDep, staff: StaffDep) -> list[GenerationJobView]:
    jobs = session.scalars(
        select(GenerationJob).order_by(GenerationJob.id.desc()).limit(25)
    )
    return [_job_view(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=GenerationJobView)
def get_job(job_id: int, session: SessionDep, staff: StaffDep) -> GenerationJobView:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_view(job)


# --- review queue ----------------------------------------------------------

# Statuses that still need a human decision (PRD section 55, Review Queue).
REVIEW_STATUSES = (
    ChallengeStatus.GENERATED,
    ChallengeStatus.AUTO_VALIDATED,
    ChallengeStatus.HUMAN_REVIEWED,
    ChallengeStatus.APPROVED,
    ChallengeStatus.FLAGGED,
)


def _row(session, record: ChallengeRecord) -> AdminChallengeRow:
    reports = session.scalar(
        select(func.count(ContentReport.id)).where(
            ContentReport.challenge_pk == record.id
        )
    )
    failed = session.scalar(
        select(func.count(Validation.id)).where(
            Validation.challenge_pk == record.id, Validation.passed.is_(False)
        )
    )
    return AdminChallengeRow(
        challenge_id=record.challenge_id,
        subject=record.subject,
        topic=record.topic,
        subtopic=record.subtopic,
        difficulty=record.difficulty,
        artifact_type=record.artifact_type,
        status=record.status,
        truth_state=record.truth_state,
        failure_category=record.failure_category,
        failure_label=taxonomy.label(record.failure_category)
        if record.failure_category
        else "",
        quality_score=record.quality_score,
        version=record.version,
        question=record.body.get("question", ""),
        reports=reports or 0,
        failed_validators=failed or 0,
        reviewed_by=record.reviewed_by,
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
    )


@router.get("/queue", response_model=list[AdminChallengeRow])
def review_queue(
    session: SessionDep,
    staff: StaffDep,
    status: str | None = None,
    subject: str | None = None,
    reported_only: bool = False,
    limit: int = Query(default=100, le=500),
) -> list[AdminChallengeRow]:
    stmt = select(ChallengeRecord)
    if status:
        stmt = stmt.where(ChallengeRecord.status == status)
    else:
        stmt = stmt.where(ChallengeRecord.status.in_(REVIEW_STATUSES))
    if subject:
        stmt = stmt.where(ChallengeRecord.subject == subject)
    if reported_only:
        # Triage (PRD section 109) needs student reports to be reachable
        # regardless of how large the catalog grows. Without this filter a
        # reported challenge outside the first page of a date-ordered listing
        # is invisible to staff, which is the one thing a reports feed must
        # never do.
        stmt = stmt.where(
            ChallengeRecord.id.in_(select(ContentReport.challenge_pk).distinct())
        )
    records = session.scalars(
        stmt.order_by(ChallengeRecord.updated_at.desc()).limit(limit)
    )
    return [_row(session, r) for r in records]


@router.get("/counts", response_model=QueueCounts)
def queue_counts(session: SessionDep, staff: StaffDep) -> QueueCounts:
    rows = session.execute(
        select(ChallengeRecord.status, func.count(ChallengeRecord.id)).group_by(
            ChallengeRecord.status
        )
    ).all()
    by_status = {status: count for status, count in rows}
    open_reports = session.scalar(select(func.count(ContentReport.id))) or 0
    open_appeals = session.scalar(
        select(func.count(Appeal.id)).where(Appeal.status == "open")
    ) or 0
    pending_evals = session.scalar(
        select(func.count(Evaluation.id)).where(
            Evaluation.status == EvaluationStatus.REVIEW_PENDING,
            Evaluation.reviewed_at.is_(None),
        )
    ) or 0
    ai = provider_status()
    return QueueCounts(
        by_status=by_status,
        in_review=sum(by_status.get(s, 0) for s in REVIEW_STATUSES),
        published=by_status.get(ChallengeStatus.PUBLISHED, 0),
        reports=open_reports,
        reviews=open_appeals + pending_evals,
        ai_configured=ai["configured"],
        ai_provider=ai.get("provider") or "",
        ai_models=ai.get("models") or {},
    )


@router.get("/challenges/{challenge_id}", response_model=AdminChallengeDetail)
def challenge_detail(
    challenge_id: str, session: SessionDep, staff: StaffDep
) -> AdminChallengeDetail:
    """Full challenge including the solution - staff only."""
    record = get_record(session, challenge_id)
    validations = session.scalars(
        select(Validation).where(Validation.challenge_pk == record.id)
    )
    versions = session.scalars(
        select(ChallengeVersion)
        .where(ChallengeVersion.challenge_pk == record.id)
        .order_by(ChallengeVersion.seq.desc())
        .limit(20)
    )
    reports = session.scalars(
        select(ContentReport)
        .where(ContentReport.challenge_pk == record.id)
        .order_by(ContentReport.id.desc())
        .limit(20)
    )
    challenge = Challenge.model_validate(record.body)
    return AdminChallengeDetail(
        row=_row(session, record),
        body=record.body,
        student_view=challenge.student_view(),
        validations=[
            {"validator": v.validator, "passed": v.passed, "detail": v.detail}
            for v in validations
        ],
        critic_summary=record.critic_summary or {},
        versions=[
            {
                "seq": v.seq,
                "body_version": v.body_version,
                "status": v.status,
                "note": v.note,
                "author": v.author,
                "created_at": v.created_at.isoformat() if v.created_at else "",
            }
            for v in versions
        ],
        reports=[
            {
                "reason": r.reason,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in reports
        ],
        allowed_transitions=sorted(ALLOWED_TRANSITIONS.get(record.status, set())),
    )


@router.post("/challenges/{challenge_id}/transition", response_model=AdminChallengeRow)
def move_challenge(
    challenge_id: str,
    body: TransitionRequest,
    session: SessionDep,
    staff: StaffDep,
) -> AdminChallengeRow:
    """Approve, reject, publish, flag or retire (PRD sections 56, 108)."""
    record = get_record(session, challenge_id)
    try:
        transition(
            session, record, body.status, author=staff, note=body.note, force=body.force
        )
    except GovernanceError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return _row(session, record)


@router.patch("/challenges/{challenge_id}", response_model=AdminChallengeDetail)
def edit_challenge(
    challenge_id: str,
    body: EditChallengeRequest,
    session: SessionDep,
    staff: StaffDep,
) -> AdminChallengeDetail:
    """Edit a challenge body and re-run the domain validator.

    The whole body is replaced so a reviewer can fix a solver, a step or a hint
    in one operation. Validation runs on the result - an edit that breaks the
    solver un-publishes the challenge rather than silently serving it.
    """
    record = get_record(session, challenge_id)
    try:
        challenge = Challenge.model_validate(body.body)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid challenge body: {exc}"
        ) from exc
    if challenge.id != record.challenge_id:
        raise HTTPException(status_code=422, detail="challenge id cannot be changed")

    apply_edit(session, record, challenge, note=body.note, author=staff)
    session.commit()
    return challenge_detail(challenge_id, session, staff)


# --- templates (PRD section 58) --------------------------------------------


@router.get("/templates", response_model=list[TemplateView])
def list_templates(session: SessionDep, staff: StaffDep) -> list[TemplateView]:
    templates = session.scalars(select(ChallengeTemplate).order_by(ChallengeTemplate.id))
    return [
        TemplateView(
            key=t.key,
            name=t.name,
            description=t.description,
            desired_failure=t.desired_failure,
            difficulty=t.difficulty,
            make_correct=t.make_correct,
            applicable_subjects=list(t.applicable_subjects or []),
        )
        for t in templates
    ]


@router.post("/templates", response_model=TemplateView, status_code=201)
def create_template(
    body: TemplateRequest, session: SessionDep, staff: StaffDep
) -> TemplateView:
    existing = session.scalar(
        select(ChallengeTemplate).where(ChallengeTemplate.key == body.key)
    )
    template = existing or ChallengeTemplate(key=body.key)
    template.name = body.name
    template.description = body.description
    template.desired_failure = body.desired_failure
    template.difficulty = body.difficulty
    template.make_correct = body.make_correct
    template.applicable_subjects = body.applicable_subjects
    if existing is None:
        session.add(template)
    session.commit()
    return TemplateView(
        key=template.key,
        name=template.name,
        description=template.description,
        desired_failure=template.desired_failure,
        difficulty=template.difficulty,
        make_correct=template.make_correct,
        applicable_subjects=list(template.applicable_subjects or []),
    )


# --- analytics (PRD sections 80, 109) --------------------------------------


@router.get("/analytics", response_model=StudioAnalytics)
def studio_analytics(session: SessionDep, staff: StaffDep) -> StudioAnalytics:
    """Challenge-level analytics for content decisions."""
    per_challenge: list[dict] = []
    records = list(
        session.scalars(
            select(ChallengeRecord).where(
                ChallengeRecord.status == ChallengeStatus.PUBLISHED
            )
        )
    )
    for record in records:
        attempts = list(
            session.scalars(
                select(Attempt).where(Attempt.challenge_pk == record.id)
            )
        )
        if not attempts:
            continue
        judged = [a for a in attempts if a.judgment is not None]
        completed = [a for a in attempts if a.status == AttemptStatus.COMPLETED]
        correct = [a for a in judged if a.judged_correctly]
        hints = [a.hints_used for a in attempts]
        per_challenge.append(
            {
                "challenge_id": record.challenge_id,
                "subject": record.subject,
                "subtopic": record.subtopic,
                "difficulty": record.difficulty,
                "failure_label": taxonomy.label(record.failure_category)
                if record.failure_category
                else record.truth_state.replace("_", " ").title(),
                "attempts": len(attempts),
                "completion_rate": round(len(completed) / len(attempts) * 100, 1),
                "detection_rate": round(len(correct) / len(judged) * 100, 1)
                if judged
                else 0.0,
                "avg_hints": round(sum(hints) / len(hints), 2) if hints else 0.0,
                "abandonment_rate": round(
                    (len(attempts) - len(completed)) / len(attempts) * 100, 1
                ),
            }
        )

    per_challenge.sort(key=lambda r: r["detection_rate"])

    evaluations = list(session.scalars(select(Evaluation)))
    accepted = sum(1 for e in evaluations if e.accepted)
    runs = list(session.scalars(select(ModelRun)))

    by_failure: dict[str, int] = {}
    for record in records:
        label = (
            taxonomy.label(record.failure_category)
            if record.failure_category
            else record.truth_state.replace("_", " ").title()
        )
        by_failure[label] = by_failure.get(label, 0) + 1

    return StudioAnalytics(
        published=len(records),
        subjects_with_content=len({r.subject for r in records}),
        total_subjects=len(all_configs()),
        challenges=per_challenge,
        evidence_submitted=len(evaluations),
        evidence_acceptance_rate=round(accepted / len(evaluations) * 100, 1)
        if evaluations
        else 0.0,
        failure_distribution=by_failure,
        model_calls=len(runs),
        input_tokens=sum(r.input_tokens for r in runs),
        output_tokens=sum(r.output_tokens for r in runs),
        cached_tokens=sum(r.cache_read_tokens for r in runs),
    )


@router.get("/reports")
def list_reports(session: SessionDep, staff: StaffDep) -> list[dict]:
    """Student reports awaiting triage (PRD section 109)."""
    rows = session.execute(
        select(ContentReport, ChallengeRecord)
        .join(ChallengeRecord, ContentReport.challenge_pk == ChallengeRecord.id)
        .order_by(ContentReport.id.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": rep.id,
            "challenge_id": rec.challenge_id,
            "subject": rec.subject,
            "status": rec.status,
            "reason": rep.reason,
            "detail": rep.detail,
            "question": rec.body.get("question", ""),
            "created_at": rep.created_at.isoformat() if rep.created_at else "",
        }
        for rep, rec in rows
    ]


# --- appeals and pending evaluations (PRD v0.2 sections 9.4, 11.2) ---------


@router.get("/reviews", response_model=list[ReviewItem])
def review_items(session: SessionDep, staff: StaffDep) -> list[ReviewItem]:
    """Everything awaiting a human decision on a learner's work.

    Two sources feed this queue: appeals a learner raised, and submissions the
    evaluator could not settle. Both must be visible, because a submission
    parked as `review_pending` is a learner blocked through no fault of theirs.
    """
    items: list[ReviewItem] = []

    appeals = session.execute(
        select(Appeal, Attempt, ChallengeRecord)
        .join(Attempt, Appeal.attempt_id == Attempt.id)
        .join(ChallengeRecord, Attempt.challenge_pk == ChallengeRecord.id)
        .where(Appeal.status == "open")
        .order_by(Appeal.id)
    ).all()
    for appeal, attempt, record in appeals:
        items.append(
            ReviewItem(
                kind="appeal",
                id=appeal.id,
                attempt_id=attempt.id,
                challenge_id=record.challenge_id,
                subject=record.subject,
                question=record.body.get("question", ""),
                truth_state=record.truth_state,
                learner_judgment=attempt.judgment or "",
                reason=appeal.reason,
                evaluator_feedback="",
                cards=_cards_for(session, appeal.submission_id),
                created_at=appeal.created_at.isoformat() if appeal.created_at else "",
            )
        )

    pending = session.execute(
        select(Evaluation, EvidenceSubmission, Attempt, ChallengeRecord)
        .join(
            EvidenceSubmission, Evaluation.submission_id == EvidenceSubmission.id
        )
        .join(Attempt, EvidenceSubmission.attempt_id == Attempt.id)
        .join(ChallengeRecord, Attempt.challenge_pk == ChallengeRecord.id)
        .where(
            Evaluation.status == EvaluationStatus.REVIEW_PENDING,
            Evaluation.reviewed_at.is_(None),
        )
        .order_by(Evaluation.id)
    ).all()
    for evaluation, submission, attempt, record in pending:
        items.append(
            ReviewItem(
                kind="evaluation",
                id=evaluation.id,
                attempt_id=attempt.id,
                challenge_id=record.challenge_id,
                subject=record.subject,
                question=record.body.get("question", ""),
                truth_state=record.truth_state,
                learner_judgment=attempt.judgment or "",
                reason=evaluation.reason_code,
                evaluator_feedback=evaluation.feedback,
                cards=_cards_for(session, submission.id),
                created_at=evaluation.created_at.isoformat()
                if evaluation.created_at
                else "",
            )
        )

    return items


def _cards_for(session, submission_id: int | None) -> list[dict]:
    """The exact cards that were submitted, for review and appeal."""
    if submission_id is None:
        return []
    cards = session.scalars(
        select(EvidenceCardRecord)
        .where(EvidenceCardRecord.submission_id == submission_id)
        .order_by(EvidenceCardRecord.ordinal)
    )
    return [
        {
            "ordinal": c.ordinal,
            "type": c.evidence_type,
            "references_step": c.references_step,
            "payload": {k: v for k, v in (c.payload or {}).items() if v},
            "why_supports": c.why_supports,
        }
        for c in cards
    ]


@router.post("/reviews/{kind}/{item_id}/resolve", response_model=dict)
def resolve_review(
    kind: str,
    item_id: int,
    body: ResolveReviewRequest,
    session: SessionDep,
    staff: StaffDep,
) -> dict:
    """Resolve one queue item.

    `uphold` leaves the original decision; `accept` credits the learner's
    evidence and updates the score ledger; `quarantine` pulls the challenge out
    of circulation because the defect is in the content, not the answer.
    """
    if body.outcome not in ("uphold", "accept", "quarantine"):
        raise HTTPException(
            status_code=422, detail="outcome must be uphold, accept or quarantine"
        )

    if kind == "appeal":
        appeal = session.get(Appeal, item_id)
        if appeal is None:
            raise HTTPException(status_code=404, detail="appeal not found")
        attempt = session.get(Attempt, appeal.attempt_id)
        evaluation = (
            session.scalar(
                select(Evaluation).where(
                    Evaluation.submission_id == appeal.submission_id
                )
            )
            if appeal.submission_id
            else None
        )
        appeal.status = "resolved"
        appeal.outcome = body.outcome
        appeal.resolution = body.note
        appeal.resolved_by = staff
        appeal.resolved_at = datetime.now(UTC)
    elif kind == "evaluation":
        evaluation = session.get(Evaluation, item_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        submission = session.get(EvidenceSubmission, evaluation.submission_id)
        attempt = session.get(Attempt, submission.attempt_id) if submission else None
    else:
        raise HTTPException(status_code=404, detail="unknown review kind")

    if evaluation is not None:
        evaluation.reviewer = staff
        evaluation.review_note = body.note
        evaluation.reviewed_at = datetime.now(UTC)

    if body.outcome == "accept" and attempt is not None:
        # Credit the learner. The score is recomputed on completion from these
        # fields, so the correction flows through rather than being pasted onto
        # a stale total.
        if evaluation is not None:
            evaluation.status = EvaluationStatus.SUPPORTED
            evaluation.accepted = True
            evaluation.strength = max(evaluation.strength, body.strength)
            evaluation.reasoning_quality = max(
                evaluation.reasoning_quality, body.reasoning_quality
            )
        attempt.evidence_accepted = True
        attempt.evidence_strength = max(attempt.evidence_strength, body.strength)
        attempt.reasoning_quality = max(
            attempt.reasoning_quality, body.reasoning_quality
        )
        attempt.status = AttemptStatus.JUDGMENT_RESOLVED
    elif body.outcome == "uphold":
        if evaluation is not None and evaluation.status == EvaluationStatus.REVIEW_PENDING:
            evaluation.status = EvaluationStatus.NEEDS_REVISION
        if attempt is not None and attempt.status == AttemptStatus.REVIEW_PENDING:
            attempt.status = AttemptStatus.NEEDS_REVISION
    elif body.outcome == "quarantine" and attempt is not None:
        record = session.get(ChallengeRecord, attempt.challenge_pk)
        if record is not None:
            try:
                transition(
                    session,
                    record,
                    ChallengeStatus.FLAGGED,
                    author=staff,
                    note=body.note or "quarantined after review",
                    force=True,
                )
            except GovernanceError as exc:
                session.rollback()
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        # A content defect must not be scored against the learner.
        attempt.status = AttemptStatus.WITHDRAWN

    session.commit()
    return {"status": "resolved", "outcome": body.outcome}
