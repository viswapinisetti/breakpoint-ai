"""Database entities (PRD sections 104, 108).

The published challenge body is stored as JSON rather than shredded into
columns: it is authored and validated as one versioned document, and the
engine treats it as opaque apart from the indexed routing fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ChallengeStatus(StrEnum):
    """Content governance lifecycle (PRD section 108)."""

    DRAFT = "draft"
    GENERATED = "generated"
    AUTO_VALIDATED = "auto_validated"
    HUMAN_REVIEWED = "human_reviewed"
    APPROVED = "approved"
    PUBLISHED = "published"
    FLAGGED = "flagged"
    RETIRED = "retired"
    REJECTED = "rejected"


class AttemptStatus(StrEnum):
    """Attempt lifecycle (PRD v0.2 section 5.3).

    `REVIEW_PENDING` matters: an evaluator that is uncertain must not mark the
    learner wrong. The attempt parks, the learner moves on, and a reviewer
    resolves it later.
    """

    IN_PROGRESS = "in_progress"
    EVALUATING = "evaluating"
    NEEDS_REVISION = "needs_revision"
    REVIEW_PENDING = "review_pending"
    JUDGMENT_RESOLVED = "judgment_resolved"
    OUTCOME_TASK = "outcome_task"
    DEBRIEF = "debrief"
    COMPLETED = "completed"
    PAUSED = "paused"
    WITHDRAWN = "withdrawn"


class EvaluationStatus(StrEnum):
    """PRD v0.2 section 9.2."""

    SUPPORTED = "supported"
    NEEDS_REVISION = "needs_revision"
    REVIEW_PENDING = "review_pending"
    TECHNICAL_ERROR = "technical_error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The identity key every mode resolves to. Header mode uses the student
    # id, OIDC the provider's subject claim, accounts mode "email:<address>"
    # or "google:<sub>", so one column keeps working for all of them.
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # --- accounts mode (app/auth/accounts.py) -----------------------------
    # The address sign-in looks up: normalised, unique, and null for students
    # who arrived by header or SSO, since "" would collide across all of them.
    login_email: Mapped[str | None] = mapped_column(
        String(320), unique=True, index=True, default=None
    )
    # scrypt, self-describing (app/auth/passwords.py). Empty for accounts
    # that only ever signed in with Google.
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    # Google's subject claim, stable across email changes on their side.
    google_sub: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True, default=None
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    # Streak state (PRD section 36.5) - rewards investigation, not completion.
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    streak_last_day: Mapped[str] = mapped_column(String(10), default="")

    attempts: Mapped[list[Attempt]] = relationship(back_populates="user")


class LoginSession(Base):
    """One signed-in browser, in accounts mode.

    Opaque tokens, stored only as a SHA-256 hash: a leaked database then
    yields no usable cookie. Rows are kept after sign-out rather than deleted
    so "signed out at" stays answerable, and expiry is checked on every
    request rather than trusted to a cleanup job.
    """

    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    # Enough to recognise a device in a future "your sessions" list. Not an
    # audit trail: it is whatever the browser claims.
    user_agent: Mapped[str] = mapped_column(String(200), default="")

    user: Mapped[User] = relationship()


class OAuthHandshake(Base):
    """One in-flight Google sign-in.

    The state, nonce and PKCE verifier live here rather than in a cookie, so
    a callback cannot be replayed: the row is consumed on first use. Rows
    expire in minutes; `purge_expired` clears the ones nobody came back for.
    """

    __tablename__ = "oauth_handshakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ChallengeRecord(Base):
    """A generated or published challenge plus its governance state."""

    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    subject: Mapped[str] = mapped_column(String(64), index=True)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    subtopic: Mapped[str] = mapped_column(String(128), default="")
    difficulty: Mapped[str] = mapped_column(String(8), index=True)
    challenge_mode: Mapped[str] = mapped_column(String(32))
    artifact_type: Mapped[str] = mapped_column(String(64), default="")

    # Private adjudication state (PRD v0.2 section 4.1). Indexed for the
    # truth-mix reports; never exposed on a student endpoint.
    truth_state: Mapped[str] = mapped_column(String(32), index=True)
    failure_category: Mapped[str] = mapped_column(String(8), default="", index=True)

    status: Mapped[str] = mapped_column(
        String(32), default=ChallengeStatus.GENERATED, index=True
    )
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    version: Mapped[int] = mapped_column(Integer, default=1)

    body: Mapped[dict[str, Any]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    # Review metadata (PRD sections 56, 108).
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(128), default="")
    critic_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    validations: Mapped[list[Validation]] = relationship(
        back_populates="challenge", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ChallengeVersion]] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        order_by="ChallengeVersion.seq.desc()",
    )
    attempts: Mapped[list[Attempt]] = relationship(back_populates="challenge")
    reports: Mapped[list[ContentReport]] = relationship(back_populates="challenge")


class ChallengeVersion(Base):
    """Append-only audit trail for one challenge (PRD section 108).

    Two distinct numbers matter here and conflating them is a mistake:

    * `seq` is this row's position in the challenge's audit history. It
      increments on every recorded event - body edits *and* status transitions -
      because "who approved this, and when" is exactly what content governance
      needs to answer.
    * `body_version` is the version of the challenge body captured by this
      snapshot. It only changes when the body actually changes, so several
      audit rows can share one body version (approved, published, flagged).
    """

    __tablename__ = "challenge_versions"
    __table_args__ = (
        UniqueConstraint("challenge_pk", "seq", name="uq_challenge_version_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_pk: Mapped[int] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    body_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    challenge: Mapped[ChallengeRecord] = relationship(back_populates="versions")


class GenerationJob(Base):
    """One Challenge Studio generation run (PRD sections 56, 57).

    Generation is slow and costs money, so it runs as a tracked background job
    rather than a blocking request. The funnel counts are kept so content
    developers can see where candidates died.
    """

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requested: Mapped[int] = mapped_column(Integer, default=0)
    survived: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    funnel: Mapped[list[Any]] = mapped_column(JSON, default=list)
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class ChallengeTemplate(Base):
    """A saved, reusable challenge shape (PRD section 58).

    Templates are how one authoring pattern - "correct final answer, invalid
    reasoning" - scales across many subjects without re-describing it each time.
    """

    __tablename__ = "challenge_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    desired_failure: Mapped[str] = mapped_column(String(128), default="")
    difficulty: Mapped[str] = mapped_column(String(8), default="3")
    make_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    applicable_subjects: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Validation(Base):
    """One validator run against one challenge (PRD sections 46.6, 47)."""

    __tablename__ = "validations"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_pk: Mapped[int] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    validator: Mapped[str] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    challenge: Mapped[ChallengeRecord] = relationship(back_populates="validations")


class Attempt(Base):
    """One student investigation of one challenge."""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    challenge_pk: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)

    status: Mapped[str] = mapped_column(
        String(32), default=AttemptStatus.IN_PROGRESS, index=True
    )
    # The first judgment is recorded before any reveal and is never overwritten
    # by a later revision (PRD v0.2 section 10.1).
    judgment: Mapped[str | None] = mapped_column(String(32), default=None)
    judged_correctly: Mapped[bool | None] = mapped_column(Boolean, default=None)
    # How sure the student was, 0-100, stated before the verdict was resolved.
    # Null for attempts judged before the question was asked, and for API
    # callers that omit it: calibration skips those rather than assuming 50.
    confidence: Mapped[int | None] = mapped_column(Integer, default=None)
    located_step: Mapped[int | None] = mapped_column(Integer, default=None)
    located_first_failure: Mapped[bool] = mapped_column(Boolean, default=False)
    # Guided modes disclose that a failure exists, so their judgments are
    # excluded from mixed-mode trust metrics (PRD v0.2 section 3.2).
    mixed_mode: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    debate_turns: Mapped[int] = mapped_column(Integer, default=0)
    # Assistance flags the attempt rather than deducting points, and excludes
    # it from independent-success metrics (PRD v0.2 section 10.1).
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    assisted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    evidence_strength: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_quality: Mapped[float] = mapped_column(Float, default=0.0)

    # The outcome task is repair (flawed), justification (valid) or naming the
    # missing condition (insufficient information).
    repair_text: Mapped[str] = mapped_column(Text, default="")
    repair_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    repair_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_correct: Mapped[bool | None] = mapped_column(Boolean, default=None)

    # Break the Tests (Mode F). The outcome task there is an executable
    # artifact, so the input itself is stored: it is the student's work, it is
    # what a reviewer would look at on appeal, and unlike prose it can be
    # re-run against the implementations to reproduce the verdict.
    test_input: Mapped[str] = mapped_column(Text, default="")
    test_submissions: Mapped[int] = mapped_column(Integer, default=0)
    test_broke_suite: Mapped[bool] = mapped_column(Boolean, default=False)

    score_total: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    user: Mapped[User] = relationship(back_populates="attempts")
    challenge: Mapped[ChallengeRecord] = relationship(back_populates="attempts")
    submissions: Mapped[list[EvidenceSubmission]] = relationship(
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="EvidenceSubmission.revision",
    )
    debate: Mapped[list[DebateTurn]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class EvidenceSubmission(Base):
    """One immutable submission of evidence cards (PRD v0.2 sections 6.4, 13.1).

    Submissions are append-only. A student who revises after "needs revision"
    creates revision 2 rather than editing revision 1, so the evaluation record
    always refers to exactly the text that was judged - which is what an appeal
    needs to be resolvable months later.

    `idempotency_key` is unique per attempt, so a retried request returns the
    existing submission instead of creating a duplicate (PRD v0.2 section 13.3).
    """

    __tablename__ = "evidence_submissions"
    __table_args__ = (
        UniqueConstraint("attempt_id", "revision", name="uq_submission_revision"),
        UniqueConstraint(
            "attempt_id", "idempotency_key", name="uq_submission_idempotency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    challenge_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempt: Mapped[Attempt] = relationship(back_populates="submissions")
    cards: Mapped[list[EvidenceCardRecord]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="EvidenceCardRecord.ordinal",
    )
    evaluation: Mapped[Evaluation | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan", uselist=False
    )


class EvidenceCardRecord(Base):
    """One typed card within a submission (PRD v0.2 section 6.4)."""

    __tablename__ = "evidence_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_submissions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    evidence_type: Mapped[str] = mapped_column(String(32), index=True)
    references_step: Mapped[int | None] = mapped_column(Integer, default=None)
    # The typed fields for this card kind, as supplied.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    why_supports: Mapped[str] = mapped_column(Text, default="")

    submission: Mapped[EvidenceSubmission] = relationship(back_populates="cards")


class Evaluation(Base):
    """The adjudication of one submission (PRD v0.2 section 9.2).

    Stores enough to reproduce and appeal the decision: which evaluator and
    rubric version ran, the criterion-level results, the deterministic check
    outputs, and a machine-readable reason code.
    """

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("evidence_submissions.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason_code: Mapped[str] = mapped_column(String(64), default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    missing: Mapped[str] = mapped_column(Text, default="")

    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning_quality: Mapped[float] = mapped_column(Float, default=0.0)

    criterion_results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    deterministic_checks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    evaluator_version: Mapped[str] = mapped_column(String(64), default="")
    rubric_version: Mapped[str] = mapped_column(String(64), default="")

    # Human review (PRD v0.2 section 9.4).
    reviewer: Mapped[str] = mapped_column(String(128), default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    submission: Mapped[EvidenceSubmission] = relationship(back_populates="evaluation")


class Appeal(Base):
    """A learner's request for review of an evaluation (PRD v0.2 section 9.4)."""

    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("evidence_submissions.id"), default=None
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[str] = mapped_column(String(128), default="")
    outcome: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class DebateTurn(Base):
    """One exchange in an AI Debate (PRD sections 30, 46.8)."""

    __tablename__ = "debate_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), index=True
    )
    turn: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # "student" | "ai"
    message: Mapped[str] = mapped_column(Text)
    conceded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempt: Mapped[Attempt] = relationship(back_populates="debate")


class Achievement(Base):
    """Unlocked achievements (PRD section 61)."""

    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_user_achievement"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ContentReport(Base):
    """Student challenge report (PRD section 109)."""

    __tablename__ = "content_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_pk: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    reason: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    challenge: Mapped[ChallengeRecord] = relationship(back_populates="reports")


class ModelRun(Base):
    """Every LLM call, for cost and quality analytics (PRD sections 73, 80)."""

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(96))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AnalyticsEvent(Base):
    """Product and learning analytics (PRD sections 78-80)."""

    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    name: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
