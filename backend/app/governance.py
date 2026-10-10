"""Content governance: lifecycle transitions and version history.

PRD section 108:

    DRAFT -> GENERATED -> AUTO-VALIDATED -> HUMAN-REVIEWED
          -> APPROVED -> PUBLISHED -> FLAGGED -> RETIRED

Two rules are enforced here rather than in the router, so every caller gets
them - the generation job, the review UI and the seeder alike:

* **A challenge cannot be published unless it currently validates.** Approval is
  a human judgment layered on top of a machine check, never a replacement for
  one. An edit that breaks the solver un-publishes the challenge.
* **Every accepted body change is snapshotted** before it is overwritten, so
  published content always has history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engine.contracts import Challenge
from app.engine.modes import validate_mode
from app.engine.registry import adapter_for
from app.models import ChallengeRecord, ChallengeStatus, ChallengeVersion, Validation
from app.subjects.base import ValidationResult
from app.subjects.topics import validate_topic

logger = logging.getLogger(__name__)

# Transitions a human reviewer may drive. Generation owns everything up to
# AUTO_VALIDATED; a published challenge can only be flagged or retired.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ChallengeStatus.DRAFT: {ChallengeStatus.GENERATED, ChallengeStatus.REJECTED},
    ChallengeStatus.GENERATED: {
        ChallengeStatus.AUTO_VALIDATED,
        ChallengeStatus.REJECTED,
    },
    ChallengeStatus.AUTO_VALIDATED: {
        ChallengeStatus.HUMAN_REVIEWED,
        ChallengeStatus.APPROVED,
        ChallengeStatus.REJECTED,
    },
    ChallengeStatus.HUMAN_REVIEWED: {
        ChallengeStatus.APPROVED,
        ChallengeStatus.REJECTED,
    },
    ChallengeStatus.APPROVED: {
        ChallengeStatus.PUBLISHED,
        ChallengeStatus.REJECTED,
    },
    ChallengeStatus.PUBLISHED: {ChallengeStatus.FLAGGED, ChallengeStatus.RETIRED},
    ChallengeStatus.FLAGGED: {
        ChallengeStatus.PUBLISHED,
        ChallengeStatus.RETIRED,
        ChallengeStatus.REJECTED,
    },
    ChallengeStatus.RETIRED: {ChallengeStatus.PUBLISHED},
    ChallengeStatus.REJECTED: {ChallengeStatus.DRAFT},
}


class GovernanceError(RuntimeError):
    """A lifecycle transition was refused."""


@dataclass
class TransitionResult:
    status: str
    validations: list[ValidationResult]
    revalidated: bool


def validate(challenge: Challenge) -> list[ValidationResult]:
    """Run every deterministic check a challenge is subject to.

    Three layers, cheapest first, in the order PRD v0.2 section 9.1 sets out:
    the topic must be registered for the subject (a challenge filed under a
    topic the curriculum does not have has nowhere to appear), then mode
    structure (subject-independent), then the subject's domain validator
    (which may execute code). This is the single funnel - every caller that
    validates a challenge goes through here, so a new check is added once.
    """
    return [
        validate_topic(challenge.subject, challenge.topic),
        *validate_mode(challenge),
        *adapter_for(challenge.subject).validate(challenge),
    ]


def record_validations(
    session: Session, record: ChallengeRecord, results: list[ValidationResult]
) -> None:
    """Replace the stored validator run for a challenge."""
    session.query(Validation).filter(
        Validation.challenge_pk == record.id
    ).delete(synchronize_session=False)
    for r in results:
        session.add(
            Validation(
                challenge_pk=record.id,
                validator=r.validator,
                passed=r.passed,
                detail=r.detail,
            )
        )


def snapshot(
    session: Session, record: ChallengeRecord, *, note: str, author: str
) -> None:
    """Append an audit row capturing the challenge's current state.

    `seq` is allocated as max+1 for this challenge, so status transitions and
    body edits interleave in one honest timeline. `body_version` records which
    body the row captured, which is what a rollback needs.
    """
    last = session.scalar(
        select(func.max(ChallengeVersion.seq)).where(
            ChallengeVersion.challenge_pk == record.id
        )
    )
    session.add(
        ChallengeVersion(
            challenge_pk=record.id,
            seq=(last or 0) + 1,
            body_version=record.version,
            status=record.status,
            body=record.body,
            note=note,
            author=author,
        )
    )


def apply_edit(
    session: Session,
    record: ChallengeRecord,
    challenge: Challenge,
    *,
    note: str,
    author: str,
) -> list[ValidationResult]:
    """Replace a challenge body, snapshotting the previous version first.

    A published challenge whose edit no longer validates is moved back to
    AUTO_VALIDATED rather than left serving broken content to students.
    """
    results = validate(challenge)
    snapshot(session, record, note=note or "edited", author=author)

    challenge.validators = [r.validator for r in results if r.passed]
    record.version += 1
    record.body = challenge.model_dump(mode="json")
    record.subject = challenge.subject
    record.topic = challenge.topic
    record.subtopic = challenge.subtopic
    record.difficulty = challenge.difficulty.value
    record.challenge_mode = challenge.challenge_mode.value
    record.artifact_type = challenge.artifact_type
    record.truth_state = challenge.truth_state.value
    record.failure_category = challenge.failure.category if challenge.failure else ""
    record.quality_score = challenge.quality_score
    record.review_note = note
    record.reviewed_by = author
    record_validations(session, record, results)

    if any(not r.passed for r in results) and record.status == ChallengeStatus.PUBLISHED:
        logger.warning(
            "unpublishing %s: edit broke validation", record.challenge_id
        )
        record.status = ChallengeStatus.AUTO_VALIDATED

    return results


def transition(
    session: Session,
    record: ChallengeRecord,
    target: str,
    *,
    author: str = "",
    note: str = "",
    force: bool = False,
) -> TransitionResult:
    """Move a challenge to a new lifecycle status.

    Publishing always re-runs the domain validator. Content can rot - a solver
    that no longer reproduces its answer must not reach students because a
    reviewer clicked approve last week.
    """
    current = record.status
    if target == current:
        return TransitionResult(current, [], False)

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed and not force:
        raise GovernanceError(
            f"cannot move {record.challenge_id} from {current} to {target}; "
            f"allowed: {sorted(allowed) or 'none'}"
        )

    results: list[ValidationResult] = []
    revalidated = False
    if target == ChallengeStatus.PUBLISHED:
        challenge = Challenge.model_validate(record.body)
        results = validate(challenge)
        revalidated = True
        failed = [r for r in results if not r.passed]
        if failed:
            record_validations(session, record, results)
            raise GovernanceError(
                f"refusing to publish {record.challenge_id}: "
                + "; ".join(f"{r.validator}: {r.detail}" for r in failed)
            )
        record_validations(session, record, results)

    snapshot(session, record, note=note or f"{current} -> {target}", author=author)
    record.status = target
    if note:
        record.review_note = note
    if author:
        record.reviewed_by = author

    return TransitionResult(target, results, revalidated)
