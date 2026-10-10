"""Subject catalog and challenge listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.deps import SessionDep, UserDep
from app.engine.duration import estimated_minutes
from app.engine.registry import all_configs, config_for, has_deterministic_validator
from app.models import Attempt, AttemptStatus, ChallengeRecord, ChallengeStatus
from app.schemas import ChallengeCard, SubjectSummary, TopicSummary
from app.subjects import topics as topic_registry
from app.subjects.base import SubjectConfig

router = APIRouter(tags=["subjects"])


Totals = dict[tuple[str, str], tuple[int, int]]


def _published_totals(session, subject_key: str | None = None) -> Totals:
    """Published challenges per (subject, topic): (count, estimated minutes).

    Grouped by difficulty and mode as well, since those set each challenge's
    estimate; the rows are then folded back to one total per topic.
    """
    stmt = (
        select(
            ChallengeRecord.subject,
            ChallengeRecord.topic,
            ChallengeRecord.difficulty,
            ChallengeRecord.challenge_mode,
            func.count(ChallengeRecord.id),
        )
        .where(ChallengeRecord.status == ChallengeStatus.PUBLISHED)
        .group_by(
            ChallengeRecord.subject,
            ChallengeRecord.topic,
            ChallengeRecord.difficulty,
            ChallengeRecord.challenge_mode,
        )
    )
    if subject_key:
        stmt = stmt.where(ChallengeRecord.subject == subject_key)
    totals: Totals = {}
    for subject, topic, difficulty, mode, n in session.execute(stmt).all():
        count, minutes = totals.get((subject, topic), (0, 0))
        totals[(subject, topic)] = (
            count + n,
            minutes + n * estimated_minutes(difficulty, mode),
        )
    return totals


def _summary(config: SubjectConfig, totals: Totals) -> SubjectSummary:
    """A subject with every registered topic, in order, and its live counts.

    `challenge_count` and `estimated_minutes` are subject totals, so a
    published challenge whose topic is not registered (possible only in a
    database that predates the registry) still counts rather than silently
    vanishing from the numbers.
    """
    own = [v for (s, _), v in totals.items() if s == config.key]
    return SubjectSummary(
        key=config.key,
        number=config.number,
        name=config.name,
        tagline=config.tagline,
        tier=config.tier,
        topics=[
            TopicSummary(
                key=t.key,
                number=t.number,
                name=t.name,
                challenge_count=totals.get((config.key, t.name), (0, 0))[0],
                estimated_minutes=totals.get((config.key, t.name), (0, 0))[1],
            )
            for t in topic_registry.topics_for(config.key)
        ],
        tools=[{"key": t.key, "label": t.label, "icon": t.icon} for t in config.tools],
        evidence_types=[e.value for e in config.evidence_types],
        failure_categories=list(config.failure_categories),
        challenge_count=sum(n for n, _ in own),
        estimated_minutes=sum(m for _, m in own),
        has_deterministic_validator=has_deterministic_validator(config.key),
        accent=config.accent,
    )


@router.get("/subjects", response_model=list[SubjectSummary])
def list_subjects(session: SessionDep) -> list[SubjectSummary]:
    """All 19 subjects, in registry order, each with its full topic list and
    live published counts (PRD sections 36.3, 100)."""
    totals = _published_totals(session)
    return [_summary(c, totals) for c in all_configs()]


@router.get("/subjects/{subject_key}", response_model=SubjectSummary)
def get_subject(subject_key: str, session: SessionDep) -> SubjectSummary:
    config = config_for(subject_key)
    if config is None:
        raise HTTPException(status_code=404, detail=f"unknown subject {subject_key}")
    return _summary(config, _published_totals(session, subject_key))


def _cards(session, user, records: list[ChallengeRecord]) -> list[ChallengeCard]:
    if not records:
        return []
    pks = [r.id for r in records]
    attempts = session.execute(
        select(Attempt.challenge_pk, Attempt.status).where(
            Attempt.user_id == user.id, Attempt.challenge_pk.in_(pks)
        )
    ).all()
    started = {pk for pk, _ in attempts}
    done = {pk for pk, st in attempts if st == AttemptStatus.COMPLETED}
    return [
        ChallengeCard(
            id=r.challenge_id,
            subject=r.subject,
            topic=r.topic,
            subtopic=r.subtopic,
            difficulty=r.difficulty,
            challenge_mode=r.challenge_mode,
            artifact_type=r.artifact_type,
            question=r.body.get("question", ""),
            simulated_confidence=_card_confidence(r.body),
            estimated_minutes=estimated_minutes(r.difficulty, r.challenge_mode),
            attempted=r.id in started,
            completed=r.id in done,
        )
        for r in records
    ]


def _card_confidence(body: dict) -> int:
    """The confidence badge for a listing card.

    Which-AI-Is-Wrong has no single artifact, so it has no single confidence.
    The card shows the higher of the two rivals: it is the number that makes
    the card honest about how assertive the item looks, and it is the one a
    student is most likely to over-trust.
    """
    competing = body.get("competing") or []
    if competing:
        return max(int(c.get("simulated_confidence", 0)) for c in competing)
    return int(body.get("simulated_confidence") or 90)


@router.get("/challenges", response_model=list[ChallengeCard])
def list_challenges(
    session: SessionDep,
    user: UserDep,
    subject: str | None = None,
    topic: str | None = None,
    difficulty: str | None = None,
    # The default is the cap, so a subject listing is never silently truncated.
    # Aptitude has 60 published challenges and will keep growing; a default of
    # 50 quietly hid ten of them, with nothing in the response to say so. When
    # the catalog outgrows 200 this needs real pagination, and having the
    # default sit on the cap makes that a visible decision rather than a slow
    # leak of missing content.
    limit: int = Query(default=200, le=200),
) -> list[ChallengeCard]:
    stmt = select(ChallengeRecord).where(
        ChallengeRecord.status == ChallengeStatus.PUBLISHED
    )
    if subject:
        stmt = stmt.where(ChallengeRecord.subject == subject)
    if topic:
        stmt = stmt.where(ChallengeRecord.topic == topic)
    if difficulty:
        stmt = stmt.where(ChallengeRecord.difficulty == difficulty)
    records = list(
        session.scalars(stmt.order_by(ChallengeRecord.difficulty).limit(limit))
    )
    return _cards(session, user, records)


@router.get("/challenges/daily", response_model=ChallengeCard | None)
def daily_challenge(session: SessionDep, user: UserDep) -> ChallengeCard | None:
    """Today's Breakpoint (PRD sections 35, 36.1).

    Prefers a challenge the student has not attempted, so the daily slot stays
    useful rather than recycling completed work.
    """
    attempted = select(Attempt.challenge_pk).where(Attempt.user_id == user.id)
    stmt = (
        select(ChallengeRecord)
        .where(
            ChallengeRecord.status == ChallengeStatus.PUBLISHED,
            ChallengeRecord.id.not_in(attempted),
        )
        .order_by(ChallengeRecord.difficulty, ChallengeRecord.id)
        .limit(1)
    )
    record = session.scalar(stmt)
    if record is None:
        record = session.scalar(
            select(ChallengeRecord)
            .where(ChallengeRecord.status == ChallengeStatus.PUBLISHED)
            .order_by(ChallengeRecord.id)
            .limit(1)
        )
    if record is None:
        return None
    return _cards(session, user, [record])[0]


@router.get("/challenges/continue", response_model=list[ChallengeCard])
def continue_investigations(session: SessionDep, user: UserDep) -> list[ChallengeCard]:
    """Started but not completed (PRD section 36.2)."""
    pks = list(
        session.scalars(
            select(Attempt.challenge_pk).where(
                Attempt.user_id == user.id,
                # WITHDRAWN, not ABANDONED - the latter is not a member of
                # AttemptStatus, so this raised AttributeError on every call.
                Attempt.status.not_in(
                    [AttemptStatus.COMPLETED, AttemptStatus.WITHDRAWN]
                ),
            )
        )
    )
    if not pks:
        return []
    records = list(
        session.scalars(select(ChallengeRecord).where(ChallengeRecord.id.in_(pks)))
    )
    return _cards(session, user, records)
