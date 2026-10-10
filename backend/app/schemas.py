"""API request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicSummary(BaseModel):
    """One registered topic (app/subjects/topics.py), in curriculum order.

    Every registered topic is listed, including those with no published
    challenges yet, so the UI can show the whole curriculum under a subject.
    """

    key: str
    number: int
    name: str
    challenge_count: int
    # Sum of its investigations' estimates (app/engine/duration.py).
    estimated_minutes: int = 0


class SubjectSummary(BaseModel):
    key: str
    number: int
    name: str
    tagline: str
    tier: str
    topics: list[TopicSummary]
    tools: list[dict[str, str]]
    evidence_types: list[str]
    failure_categories: list[str]
    challenge_count: int
    estimated_minutes: int = 0
    has_deterministic_validator: bool
    accent: str


class ChallengeCard(BaseModel):
    """Listing entry - deliberately says nothing about correctness."""

    id: str
    subject: str
    topic: str
    subtopic: str
    difficulty: str
    challenge_mode: str
    artifact_type: str
    question: str
    simulated_confidence: int
    estimated_minutes: int = 0
    attempted: bool = False
    completed: bool = False


class StartAttemptResponse(BaseModel):
    attempt_id: int
    challenge: dict[str, Any]
    tools: list[dict[str, str]]
    evidence_types: list[str]
    max_debate_turns: int
    hints_used: int
    resumed: bool = False


class JudgeRequest(BaseModel):
    judgment: str = Field(
        description="Trust-or-Challenge: approve | challenge | "
        "insufficient_information. Which-AI-Is-Wrong: a_correct | b_correct | "
        "both_correct | neither_correct | underdetermined. The server rejects "
        "a verdict that does not belong to the challenge's mode."
    )
    located_step: int | None = Field(
        default=None, description="Step the student believes fails first"
    )
    confidence: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="How sure the student was, 0-100, chosen before the verdict "
        "was resolved. Optional for API callers; the player always sends it. "
        "Omitted means 'never asked', which calibration skips rather than "
        "reading as 50.",
    )


class JudgeResponse(BaseModel):
    correct: bool
    truth_state: str = Field(description="flawed | valid | insufficient_information")
    located_first_failure: bool
    message: str
    requires_evidence: bool
    outcome_task: str = Field(
        description="repair | justify | clarify | break_tests"
    )
    confidence: int | None = Field(
        default=None, description="Echoed back as recorded, so the client can show it"
    )
    ai_confidence: int = Field(
        default=0, description="The confidence badge the artifact displayed"
    )
    calibration_note: str = Field(
        default="",
        description="One line about the student's certainty rather than their "
        "answer - empty when no confidence was given.",
    )


class EvidenceResponse(BaseModel):
    """One evaluated submission (PRD v0.2 sections 6.4, 9.2).

    `checks_passed` and `accepted` are deliberately separate: the UI must
    distinguish "Calculation checked" from "Evidence supports your claim".
    """

    revision: int
    status: str = Field(
        description="supported | needs_revision | review_pending | technical_error"
    )
    accepted: bool
    strength: float
    feedback: str
    missing: str
    reason_code: str
    dimensions: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    checks_passed: bool = False
    replayed: bool = Field(
        default=False, description="Idempotent replay of an earlier submission"
    )


class AppealRequest(BaseModel):
    """PRD v0.2 section 9.4 - request review of an evaluation."""

    reason: str = Field(min_length=10, max_length=2000)
    submission_id: int | None = None


class AppealResponse(BaseModel):
    id: int
    status: str
    message: str


class TransferRequest(BaseModel):
    """PRD v0.2 sections 5.2, 8.3 - a short check on new values."""

    answer: str = Field(min_length=1, max_length=200)


class TransferResponse(BaseModel):
    correct: bool
    expected: str
    message: str


class HintResponse(BaseModel):
    level: int
    kind: str
    text: str
    hints_used: int
    hints_remaining: int


class DebateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class DebateResponse(BaseModel):
    reply: str
    turn: int
    turns_remaining: int
    conceded: bool
    exhausted: bool


class RepairRequest(BaseModel):
    repair: str = Field(min_length=1, max_length=4000)


class RepairResponse(BaseModel):
    accepted: bool
    strength: float
    feedback: str
    reference_repair: str


class BreakTestRequest(BaseModel):
    """Mode F - one candidate test input (PRD v0.2 section 4.2)."""

    test_input: str = Field(
        min_length=1,
        max_length=500,
        description="Literal argument value(s), e.g. '0' or '[1, 1], 2'. "
        "Parsed as literals, never executed.",
    )
    rationale: str = Field(
        default="",
        max_length=1000,
        description="Why the student expects this input to expose the failure. "
        "Recorded for review; it does not affect the verdict.",
    )


class BreakTestResponse(BaseModel):
    accepted: bool
    reason_code: str = Field(
        description="suite_broken | no_divergence | already_covered | "
        "unparseable_input | execution_error"
    )
    message: str
    normalised_input: str = ""
    shipped_result: str = ""
    correct_result: str = ""
    submissions: int = Field(description="How many inputs this attempt has tried")


class ReplayStep(BaseModel):
    index: int
    text: str
    status: str = Field(description="valid | first_failure | derived | divergence")
    solution: str = Field(
        default="",
        description="Which solution this step belongs to. Empty for "
        "single-artifact modes; 'A' or 'B' in which_ai_is_wrong.",
    )


class AutopsyResponse(BaseModel):
    """Failure Replay + Autopsy + score (PRD sections 41-44, 52)."""

    challenge_id: str
    truth_state: str
    missing_information: str = ""
    resolving_scenarios: list[str] = Field(default_factory=list)
    assisted: bool = False
    answer_coincidentally_correct: bool
    failure_category: str
    failure_label: str
    failure_location: int | None
    misconception: str
    why_convincing: str
    first_failure_step: int | None
    replay: list[ReplayStep]
    canonical_solution: str
    canonical_answer: str
    ai_final_answer: str
    repair: str
    debrief: str
    counterexamples: list[str]
    score: dict[str, Any]
    hints_used: int
    debate_turns: int
    counterfactual: str

    # Mode G. Empty for every other mode.
    comparison_verdict: str = ""
    divergence_step: int | None = None
    comparison_explanation: str = ""

    # Mode F. Empty for every other mode.
    test_input: str = ""
    test_submissions: int = 0
    test_broke_suite: bool = False
    # The question only. Its answer stays server-side until the student
    # submits, exactly as with the challenge itself.
    transfer_question: str = ""


class ReportRequest(BaseModel):
    reason: str
    detail: str = ""


# --- Challenge Studio (PRD sections 55-58, 80, 108) ------------------------


class GenerateRequest(BaseModel):
    subject: str = "aptitude"
    topic: str
    concept: str
    difficulty: str = "3"
    count: int = Field(default=3, ge=1, le=10)
    desired_failure: str = Field(
        default="", description="Blank rotates through failure types across the batch"
    )
    challenge_mode: str = "trust_or_challenge"
    make_correct: bool = Field(
        default=False, description="Generate a false-failure challenge (PRD 28.10)"
    )


class GenerationJobView(BaseModel):
    id: int
    status: str
    params: dict[str, Any]
    requested: int
    survived: int
    rejected: int
    funnel: list[Any]
    error: str
    created_by: str
    created_at: str
    finished_at: str | None


class AdminChallengeRow(BaseModel):
    challenge_id: str
    subject: str
    topic: str
    subtopic: str
    difficulty: str
    artifact_type: str
    status: str
    truth_state: str
    failure_category: str
    failure_label: str
    quality_score: float
    version: int
    question: str
    reports: int
    failed_validators: int
    reviewed_by: str
    updated_at: str


class AdminChallengeDetail(BaseModel):
    row: AdminChallengeRow
    body: dict[str, Any]
    student_view: dict[str, Any]
    validations: list[dict[str, Any]]
    critic_summary: dict[str, Any]
    versions: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    allowed_transitions: list[str]


class TransitionRequest(BaseModel):
    status: str
    note: str = ""
    force: bool = False


class EditChallengeRequest(BaseModel):
    body: dict[str, Any]
    note: str = ""


class TemplateRequest(BaseModel):
    key: str
    name: str
    description: str = ""
    desired_failure: str = ""
    difficulty: str = "3"
    make_correct: bool = False
    applicable_subjects: list[str] = Field(default_factory=list)


class TemplateView(TemplateRequest):
    pass


class ReviewItem(BaseModel):
    """One item in the staff review queue (PRD v0.2 sections 9.4, 11.2)."""

    kind: str = Field(description="appeal | evaluation")
    id: int
    attempt_id: int
    challenge_id: str
    subject: str
    question: str
    truth_state: str
    learner_judgment: str
    reason: str
    evaluator_feedback: str
    cards: list[dict[str, Any]]
    created_at: str


class ResolveReviewRequest(BaseModel):
    outcome: str = Field(description="uphold | accept | quarantine")
    note: str = Field(default="", max_length=2000)
    strength: float = Field(default=8.0, ge=0, le=10)
    reasoning_quality: float = Field(default=8.0, ge=0, le=10)


class QueueCounts(BaseModel):
    by_status: dict[str, int]
    in_review: int
    published: int
    reports: int
    reviews: int = 0
    ai_configured: bool
    ai_provider: str = ""
    ai_models: dict[str, str] = Field(default_factory=dict)


class StudioAnalytics(BaseModel):
    published: int
    subjects_with_content: int
    total_subjects: int
    challenges: list[dict[str, Any]]
    evidence_submitted: int
    evidence_acceptance_rate: float
    failure_distribution: dict[str, int]
    model_calls: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int


class StatsResponse(BaseModel):
    """Investigation statistics, not mastery (PRD v0.2 sections 10, 15.1).

    Rates are `None` below the minimum sample so the UI shows "Not enough
    evidence yet" rather than a percentage computed from three attempts.
    """

    claims_investigated: int
    resolved_mixed_mode: int
    failures_found: int
    correct_approvals: int
    correct_insufficient: int
    false_alarms: int
    missed_failures: int
    strong_evidence: int
    first_judgment_accuracy: float | None
    false_alarm_rate: float | None
    missed_failure_rate: float | None
    judgment_matrix: list[dict[str, Any]]
    min_sample: int
    investigation_score: float
    score_components: dict[str, float]
    assisted_attempts: int
    independent_completions: int
    streak_days: int
    verification_skills: dict[str, float]
    failure_categories: dict[str, int]
    achievements: list[str]
    #: Confidence calibration (app/engine/calibration.py): Brier score, the
    #: over- and under-trust counts, and accuracy per confidence band.
    calibration: dict[str, Any]
