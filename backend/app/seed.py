"""Load reviewed content files into the database as published challenges.

Content files are the source of truth; the database is a serving cache. Re-running
this is safe - a challenge whose body changed is re-published as a new version,
and one that no longer validates is refused rather than overwritten.
"""

from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.engine.contracts import Challenge
from app.governance import validate as validate_challenge
from app.governance import snapshot
from app.models import (
    ChallengeRecord,
    ChallengeStatus,
    ChallengeTemplate,
    Validation,
)

logger = logging.getLogger(__name__)


def _content_of(body: dict) -> dict:
    """A challenge body minus the field the seeder itself writes into it."""
    return {k: v for k, v in body.items() if k != "validators"}


def _upsert(session: Session, challenge: Challenge) -> tuple[str, bool]:
    """Insert or update one challenge. Returns (action, ok)."""
    record = session.scalar(
        select(ChallengeRecord).where(ChallengeRecord.challenge_id == challenge.id)
    )
    if (
        record is not None
        and record.status == ChallengeStatus.PUBLISHED
        and _content_of(record.body or {}) == _content_of(challenge.model_dump(mode="json"))
    ):
        # Already validated and published with exactly this content. Validation
        # runs solvers and test code in a fresh sandboxed process per case, so
        # repeating it for every challenge on every start kept the API port
        # closed for minutes. New or edited content still takes the full path
        # below, and `scripts.validate_content` re-checks everything.
        return ("unchanged", True)

    results = validate_challenge(challenge)
    if any(not r.passed for r in results):
        detail = "; ".join(r.detail for r in results if not r.passed)
        logger.error("refusing %s: %s", challenge.id, detail)
        return ("refused", False)

    challenge.validators = [r.validator for r in results]
    body = challenge.model_dump(mode="json")

    action = "created"
    if record is None:
        record = ChallengeRecord(challenge_id=challenge.id)
        session.add(record)
    elif record.body != body:
        # Snapshot the outgoing body before overwriting it, so file-driven
        # updates carry the same history as Studio edits (PRD section 108).
        snapshot(session, record, note="content file update", author="content-seed")
        record.version += 1
        action = "updated"
    else:
        action = "unchanged"

    record.subject = challenge.subject
    record.topic = challenge.topic
    record.subtopic = challenge.subtopic
    record.difficulty = challenge.difficulty.value
    record.challenge_mode = challenge.challenge_mode.value
    record.artifact_type = challenge.artifact_type
    record.truth_state = challenge.truth_state.value
    record.failure_category = challenge.failure.category if challenge.failure else ""
    record.status = ChallengeStatus.PUBLISHED
    record.quality_score = challenge.quality_score
    record.body = body

    if action != "unchanged":
        session.flush()
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
    return (action, True)


# Cross-subject authoring patterns (PRD section 58). These are what let one
# template scale across many subjects instead of re-describing the same trap.
DEFAULT_TEMPLATES = [
    {
        "key": "correct-answer-invalid-reasoning",
        "name": "Correct final answer, invalid reasoning",
        "description": (
            "The AI reaches the right answer through reasoning that does not "
            "hold. Teaches that verifying an output says nothing about the "
            "method that produced it."
        ),
        "desired_failure": "unsupported conclusion",
        "difficulty": "4",
        "make_correct": False,
        "applicable_subjects": [
            "aptitude",
            "mathematics",
            "dsa",
            "machine-learning",
            "data-science",
        ],
    },
    {
        "key": "confident-unsupported-conclusion",
        "name": "Confident but unsupported conclusion",
        "description": (
            "Every stated fact is true, but the conclusion does not follow from "
            "them. Trains students to separate evidence from inference."
        ),
        "desired_failure": "unsupported conclusion",
        "difficulty": "3",
        "make_correct": False,
        "applicable_subjects": [
            "english",
            "computer-science",
            "ai",
            "data-analytics",
            "prompt-engineering",
        ],
    },
    {
        "key": "changing-base-assumption",
        "name": "Assumption invalidated by a later change",
        "description": (
            "A rate, ratio or base established early is reused after the "
            "scenario has changed. The arithmetic stays flawless throughout."
        ),
        "desired_failure": "hidden assumption",
        "difficulty": "3",
        "make_correct": False,
        "applicable_subjects": ["aptitude", "mathematics", "data-analytics"],
    },
    {
        "key": "actually-correct",
        "name": "Actually correct artifact",
        "description": (
            "A genuinely correct solution that looks like a classic trap. "
            "Prevents students from learning that everything here is wrong."
        ),
        "desired_failure": "",
        "difficulty": "3",
        "make_correct": True,
        "applicable_subjects": [s for s in ("aptitude", "programming", "databases")],
    },
]


def seed_templates(session: Session) -> int:
    """Install the default authoring templates if they are absent."""
    added = 0
    for spec in DEFAULT_TEMPLATES:
        exists = session.scalar(
            select(ChallengeTemplate).where(ChallengeTemplate.key == spec["key"])
        )
        if exists is None:
            session.add(ChallengeTemplate(**spec))
            added += 1
    if added:
        session.commit()
    return added


def seed_from_content(session: Session) -> dict[str, int]:
    """Load every content file. Returns a summary of actions taken."""
    summary = {"created": 0, "updated": 0, "unchanged": 0, "refused": 0}
    files = sorted(settings.content_dir.rglob("*.json"))
    if not files:
        logger.warning("no content files under %s", settings.content_dir)
        return summary
    started = time.perf_counter()
    logger.info(
        "loading content from %d files; new or changed challenges are validated "
        "first, which can take a few minutes on a fresh database",
        len(files),
    )

    for path in files:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("skipping malformed %s: %s", path.name, exc)
            continue
        for entry in entries:
            try:
                challenge = Challenge.model_validate(entry)
            except Exception as exc:
                logger.error("skipping invalid challenge in %s: %s", path.name, exc)
                summary["refused"] += 1
                continue
            action, _ = _upsert(session, challenge)
            summary[action] += 1

    session.commit()
    logger.info(
        "content seed: %s in %.1fs", summary, time.perf_counter() - started
    )
    return summary
