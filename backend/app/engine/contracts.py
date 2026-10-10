"""Universal Breakpoint contracts (PRD sections 8, 29, 31, 49, 67, 74).

Nothing in this module knows about any specific subject. A challenge is
CONCEPT -> ARTIFACT -> HIDDEN FAILURE -> EVIDENCE -> VERIFICATION -> REPAIR -> DEBRIEF,
and that shape is identical for Aptitude, DevOps or MLOps.

All model-facing objects live here too, so every LLM call returns a validated
schema rather than parsed prose (PRD section 74).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChallengeMode(StrEnum):
    """PRD section 29."""

    FIND_THE_FAILURE = "find_the_failure"        # Mode A
    TRUST_OR_CHALLENGE = "trust_or_challenge"    # Mode B - default intermediate
    PROVE_IT = "prove_it"                        # Mode C
    REPAIR_IT = "repair_it"                      # Mode D
    AI_DEBATE = "ai_debate"                      # Mode E
    BREAK_THE_TESTS = "break_the_tests"          # Mode F
    WHICH_AI_IS_WRONG = "which_ai_is_wrong"      # Mode G


class EvidenceType(StrEnum):
    """The Evidence Board card types (PRD section 31)."""

    COUNTEREXAMPLE = "counterexample"
    CALCULATION = "calculation"
    CONTRADICTION = "contradiction"
    RULE = "rule"
    TEST_CASE = "test_case"
    DATA_POINT = "data_point"
    TRACE = "trace"
    REWRITE = "rewrite"


class TruthState(StrEnum):
    """What is actually true about the artifact (PRD v0.2 section 4.1).

    Three states, not two. `INSUFFICIENT_INFORMATION` is a deliberately
    authored and reviewed learning scenario - the supplied facts cannot settle
    the claim - and is distinct from accidental ambiguity, which is a content
    defect. Teaching students to say "this cannot be decided from what I was
    given" is a verification skill in its own right.
    """

    FLAWED = "flawed"
    VALID = "valid"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class Judgment(StrEnum):
    """Every verdict a student can record.

    The first three mirror TruthState and belong to Trust-or-Challenge. The
    rest belong to Which-AI-Is-Wrong (Mode G), where the student adjudicates
    between two competing solutions. PRD v0.2 section 4.2 requires that mode to
    permit `both`, `neither` and `underdetermined` - forcing a choice between
    A and B would teach students that one of two confident answers must be
    right, which is the opposite of the point.
    """

    # Trust or Challenge (Mode B)
    CHALLENGE = "challenge"
    APPROVE = "approve"
    INSUFFICIENT_INFORMATION = "insufficient_information"

    # Which AI Is Wrong (Mode G)
    A_CORRECT = "a_correct"
    B_CORRECT = "b_correct"
    BOTH_CORRECT = "both_correct"
    NEITHER_CORRECT = "neither_correct"
    UNDERDETERMINED = "underdetermined"


# A judgment is correct when it names the artifact's actual truth state.
JUDGMENT_FOR: dict[TruthState, Judgment] = {
    TruthState.FLAWED: Judgment.CHALLENGE,
    TruthState.VALID: Judgment.APPROVE,
    TruthState.INSUFFICIENT_INFORMATION: Judgment.INSUFFICIENT_INFORMATION,
}

TRUST_JUDGMENTS = (
    Judgment.CHALLENGE,
    Judgment.APPROVE,
    Judgment.INSUFFICIENT_INFORMATION,
)
COMPARISON_JUDGMENTS = (
    Judgment.A_CORRECT,
    Judgment.B_CORRECT,
    Judgment.BOTH_CORRECT,
    Judgment.NEITHER_CORRECT,
    Judgment.UNDERDETERMINED,
)

# Which verdicts each mode will accept. The judge endpoint rejects anything
# outside its mode's set, so a client cannot approve a comparison challenge or
# name a winner in a single-artifact one.
ALLOWED_JUDGMENTS: dict[ChallengeMode, tuple[Judgment, ...]] = {
    ChallengeMode.WHICH_AI_IS_WRONG: COMPARISON_JUDGMENTS,
}


def allowed_judgments(mode: ChallengeMode) -> tuple[Judgment, ...]:
    return ALLOWED_JUDGMENTS.get(mode, TRUST_JUDGMENTS)


class Difficulty(StrEnum):
    """Subject difficulty. Stored separately from investigation demand
    (PRD v0.2 section 8.5) - trust-or-challenge is a mode, not a difficulty."""

    VISIBLE_FAILURE = "1"
    ONE_STEP_HIDDEN = "2"
    PLAUSIBLE = "3"
    EXPERT_TRAP = "4"
    ADVERSARIAL = "5"


class ReasoningStep(BaseModel):
    """One step of the AI's visible reasoning, addressable by the student."""

    index: int = Field(ge=1, description="1-indexed step number")
    text: str
    # Set only after verification - never sent to the student before they judge.
    is_first_failure: bool = False
    derived_from_failure: bool = False


class CompetingSolution(BaseModel):
    """One of two rival solutions in Which-AI-Is-Wrong (PRD v0.2 section 4.2).

    Both are shown in full, with their own confidence badges, and neither is
    marked. The student's task is to work out which - if either - is right and
    where the two lines of reasoning diverge.
    """

    label: str = Field(description="A or B")
    persona: str = Field(default="", description="e.g. 'AI Alpha'")
    ai_claim: str
    ai_solution: list[ReasoningStep]
    ai_final_answer: str
    simulated_confidence: int = Field(ge=0, le=100)


class ComparisonVerdict(BaseModel):
    """The private adjudication key for Which-AI-Is-Wrong.

    `divergence_step` is the 1-indexed step at which the two solutions first
    part company - the thing the student is really being asked to find. It is
    not always the step where one of them becomes wrong, and the debrief says
    so when they differ.
    """

    verdict: Judgment
    divergence_step: int | None = None
    explanation: str = ""

    @model_validator(mode="after")
    def _verdict_in_range(self) -> "ComparisonVerdict":
        if self.verdict not in COMPARISON_JUDGMENTS:
            raise ValueError(
                f"comparison verdict must be one of "
                f"{[j.value for j in COMPARISON_JUDGMENTS]}, got {self.verdict!r}"
            )
        return self


class TestGap(BaseModel):
    """Mode F - Break the Tests (PRD v0.2 section 4.2).

    The artifact arrives with a test suite that passes, which is exactly why it
    is dangerous: passing tests are the most common reason a wrong
    implementation ships. The student must supply one further input on which
    the implementation and the correct behaviour disagree.

    Student input is parsed as Python literals only - never executed - so a
    test case can never become an execution vector.
    """

    entry_point: str = Field(description="Function the test calls")
    signature: str = Field(default="", description="Human-readable call shape")
    arity: int = Field(default=1, ge=1, le=4)
    existing_tests: list[str] = Field(
        default_factory=list,
        description="Inputs the shipped suite already covers, shown to the "
        "student. Re-submitting one of these is rejected: it proves nothing.",
    )
    input_guidance: str = Field(
        default="", description="What shape of input is admissible, e.g. 'one integer'"
    )


class Failure(BaseModel):
    """The intended, controlled failure (PRD sections 8.3, 49, 75)."""

    category: str = Field(description="FailureCategory code, e.g. F03")
    location: int | None = Field(
        default=None, description="1-indexed step where validity first breaks"
    )
    misconception: str = Field(description="The reasoning trap being exercised")
    explanation: str
    why_convincing: str = Field(
        default="", description="PRD section 44 - why smart people miss this"
    )


class EvidenceSpec(BaseModel):
    """A canonical evidence path the engine will accept as proof."""

    type: EvidenceType
    summary: str = Field(description="What this evidence establishes")
    # Deterministic acceptance signals, checked before any LLM is consulted.
    must_reference_step: int | None = None
    must_contain_values: list[str] = Field(default_factory=list)


class Hint(BaseModel):
    """Progressive hint ladder (PRD section 40)."""

    level: int = Field(ge=1, le=5)
    kind: Literal["attention", "direction", "concept", "strong", "reveal"]
    text: str


class TransferCheck(BaseModel):
    """A short check on new values, asked after the debrief.

    PRD v0.2 sections 5.2 and 8.3: it uses different numbers or a different
    scenario so that recall of this challenge does not answer it, and it is
    evaluated separately from the attempt score.
    """

    question: str
    answer: str = Field(description="Bare expected value")
    explanation: str = Field(default="")


class Challenge(BaseModel):
    """The universal challenge object (PRD section 49)."""

    id: str
    subject: str
    topic: str
    subtopic: str = ""
    difficulty: Difficulty
    challenge_mode: ChallengeMode

    question: str
    artifact_type: str = Field(description="numeric_solution, code, sql, chart, ...")
    artifact: dict[str, Any] = Field(
        default_factory=dict,
        description="Subject-specific payload (table data, code, config). "
        "The engine passes it through untouched; the adapter renders it.",
    )

    # Empty only in which_ai_is_wrong, where there is no single solution to
    # show - the two rival solutions live in `competing`. Every other mode is
    # required to fill these, enforced in _mode_requirements below.
    ai_claim: str = ""
    ai_solution: list[ReasoningStep] = Field(default_factory=list)
    ai_final_answer: str = ""
    simulated_confidence: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Game mechanic, not model probability (section 33)",
    )

    truth_state: TruthState = Field(
        default=TruthState.FLAWED,
        description="Private adjudication key (PRD v0.2 section 4.1)",
    )
    failure: Failure | None = Field(
        default=None,
        description="Present for FLAWED artifacts; optional otherwise",
    )
    missing_information: str = Field(
        default="",
        description=(
            "For INSUFFICIENT_INFORMATION: what fact is absent and why it "
            "decides the outcome."
        ),
    )
    resolving_scenarios: list[str] = Field(
        default_factory=list,
        description=(
            "For INSUFFICIENT_INFORMATION: two or more readings, each consistent "
            "with the supplied facts, that yield different answers. This is what "
            "makes the state provable rather than a matter of opinion."
        ),
    )
    answer_coincidentally_correct: bool = Field(
        default=False,
        description=(
            "PRD v0.2 section 8.4 - the reasoning is invalid but happens to reach "
            "the correct answer. Teaches that a correct answer does not imply "
            "correct reasoning, so the answer-mismatch check must not apply."
        ),
    )

    competing: list[CompetingSolution] = Field(
        default_factory=list,
        description="Mode G only - exactly two rival solutions, both shown in "
        "full and neither marked.",
    )
    comparison: ComparisonVerdict | None = Field(
        default=None,
        description="Mode G private key. NEVER in student_view.",
    )
    test_gap: TestGap | None = Field(
        default=None,
        description="Mode F only - the shape of the test the student must supply.",
    )

    @model_validator(mode="after")
    def _mode_requirements(self) -> "Challenge":
        """Structural gate for the P1 modes (PRD v0.2 section 9.1, step 1).

        These are cheap checks that catch an authoring slip before a student
        ever sees the challenge - a Mode G item with one solution, or a Mode F
        item with nothing to test against, is broken in a way no rubric can
        recover from.
        """
        if self.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
            if len(self.competing) != 2:
                raise ValueError(
                    "which_ai_is_wrong needs exactly two competing solutions, "
                    f"got {len(self.competing)}"
                )
            labels = [c.label.upper() for c in self.competing]
            if labels != ["A", "B"]:
                raise ValueError(f"competing solutions must be labelled A then B, got {labels}")
            if self.comparison is None:
                raise ValueError("which_ai_is_wrong needs a `comparison` verdict")
        elif not (self.ai_claim and self.ai_solution and self.ai_final_answer):
            raise ValueError(
                f"{self.challenge_mode} needs ai_claim, ai_solution and "
                "ai_final_answer - only which_ai_is_wrong may leave them empty"
            )
        if self.competing and self.challenge_mode != ChallengeMode.WHICH_AI_IS_WRONG:
            raise ValueError(
                "`competing` is only meaningful for which_ai_is_wrong "
                f"(mode is {self.challenge_mode})"
            )

        if self.challenge_mode == ChallengeMode.BREAK_THE_TESTS:
            if self.test_gap is None:
                raise ValueError("break_the_tests needs a `test_gap`")
            payload = self.validation_payload
            if not (payload.get("ai_code") and payload.get("reference_code")):
                raise ValueError(
                    "break_the_tests needs validation_payload.ai_code and "
                    ".reference_code - there is nothing to differ between "
                    "without both"
                )
        elif self.test_gap is not None:
            raise ValueError(
                "`test_gap` is only meaningful for break_the_tests "
                f"(mode is {self.challenge_mode})"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_boolean(cls, data: Any) -> Any:
        """Map the pre-v0.2 `contains_failure` boolean onto `truth_state`.

        Content authored before the three-state model loads unchanged and is
        read as FLAWED / VALID. It can never produce INSUFFICIENT_INFORMATION,
        which is correct: that state has to be authored deliberately, with the
        competing scenarios that prove it.
        """
        if isinstance(data, dict) and "truth_state" not in data:
            legacy = data.get("contains_failure")
            if legacy is not None:
                data = dict(data)
                data["truth_state"] = (
                    TruthState.FLAWED if legacy else TruthState.VALID
                )
        return data

    @property
    def contains_failure(self) -> bool:
        """True only for FLAWED artifacts.

        Retained as a derived read so validators and analytics that only care
        about "is something wrong here" keep working. Anything that must
        distinguish VALID from INSUFFICIENT_INFORMATION reads `truth_state`.
        """
        return self.truth_state == TruthState.FLAWED

    @property
    def expected_judgment(self) -> Judgment:
        """The verdict that counts as correct, which depends on the mode.

        Comparison challenges are adjudicated against the authored comparison
        verdict, not against `truth_state`: "which of these two is wrong" is a
        different question from "is this one wrong", and a Mode G item can
        perfectly well have two flawed solutions.
        """
        if self.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG and self.comparison:
            return self.comparison.verdict
        return JUDGMENT_FOR[self.truth_state]

    @property
    def allowed_judgments(self) -> tuple[Judgment, ...]:
        return allowed_judgments(self.challenge_mode)

    @property
    def step_count(self) -> int:
        """The highest step number a student's evidence may reference.

        Which-AI-Is-Wrong numbers each rival solution from 1 and shows them
        side by side, so a card can point at a step in either and the bound is
        the longer of the two. `ai_solution` is empty in that mode; bounding by
        it rejected every step reference as nonexistent.
        """
        if self.challenge_mode == ChallengeMode.WHICH_AI_IS_WRONG:
            return max((len(c.ai_solution) for c in self.competing), default=0)
        return len(self.ai_solution)

    canonical_solution: str
    canonical_answer: str
    valid_evidence: list[EvidenceSpec] = Field(default_factory=list)
    counterexamples: list[str] = Field(default_factory=list)
    hints: list[Hint] = Field(default_factory=list)
    repair: str = ""
    debrief: str = ""

    transfer_check: TransferCheck | None = Field(
        default=None,
        description="Post-debrief transfer check. Never in the student view "
        "before the debrief - it carries its own answer.",
    )
    validation_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-validator inputs (e.g. Aptitude solver source). "
        "NEVER included in student_view - it contains the answer.",
    )
    validators: list[str] = Field(
        default_factory=list, description="Names of validators that passed"
    )
    quality_score: float = 0.0

    def student_view(self) -> dict[str, Any]:
        """Everything the student may see before submitting a judgment.

        Deliberately omits `contains_failure`, `failure`, the canonical
        solution, evidence specs, the repair and the debrief - leaking any of
        those turns an investigation into a reading exercise.
        """
        return {
            "id": self.id,
            "subject": self.subject,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "difficulty": self.difficulty,
            "challenge_mode": self.challenge_mode,
            "question": self.question,
            "artifact_type": self.artifact_type,
            "artifact": self.artifact,
            "ai_claim": self.ai_claim,
            "ai_solution": [
                {"index": s.index, "text": s.text} for s in self.ai_solution
            ],
            "ai_final_answer": self.ai_final_answer,
            "simulated_confidence": self.simulated_confidence,
            "hint_count": len(self.hints),
            "allowed_judgments": [j.value for j in self.allowed_judgments],
            # Mode G: both rival solutions in full, with their own confidence
            # badges. The comparison verdict and divergence step stay private.
            "competing": [
                {
                    "label": c.label,
                    "persona": c.persona,
                    "ai_claim": c.ai_claim,
                    "ai_solution": [
                        {"index": st.index, "text": st.text} for st in c.ai_solution
                    ],
                    "ai_final_answer": c.ai_final_answer,
                    "simulated_confidence": c.simulated_confidence,
                }
                for c in self.competing
            ],
            # Mode F: the call shape and the tests that already pass. The
            # reference implementation lives in validation_payload and is never
            # sent - the student is meant to reason about behaviour, not read
            # the answer off a diff.
            "test_gap": (
                {
                    "entry_point": self.test_gap.entry_point,
                    "signature": self.test_gap.signature,
                    "arity": self.test_gap.arity,
                    "existing_tests": self.test_gap.existing_tests,
                    "input_guidance": self.test_gap.input_guidance,
                }
                if self.test_gap
                else None
            ),
        }


# --- Model-facing response contracts (PRD section 74) -----------------------


class CriticVerdict(BaseModel):
    """Independent critic output. Gates publication (PRD section 46.5)."""

    found_failure: bool
    category: str = ""
    location: int | None = None
    reasoning: str
    unintended_errors: list[str] = Field(
        default_factory=list,
        description="Any error beyond the intended one - forces rejection (section 75)",
    )
    ambiguity_score: float = Field(ge=0.0, le=1.0)


class EvidenceAssessment(BaseModel):
    """Evidence Evaluation Agent output (PRD sections 32, 46.9)."""

    disproves_claim: bool
    correctness: int = Field(ge=0, le=10)
    specificity: int = Field(ge=0, le=10)
    relevance: int = Field(ge=0, le=10)
    completeness: int = Field(ge=0, le=10)
    reproducibility: int = Field(ge=0, le=10)
    reasoning_quality: int = Field(ge=0, le=10)
    feedback: str
    missing: str = Field(default="", description="What would make it stronger")

    @property
    def strength(self) -> float:
        """Mean of the six dimensions, 0-10."""
        return round(
            (
                self.correctness
                + self.specificity
                + self.relevance
                + self.completeness
                + self.reproducibility
                + self.reasoning_quality
            )
            / 6,
            2,
        )

    @property
    def is_strong(self) -> bool:
        return self.disproves_claim and self.strength >= 7.0


class QualityScore(BaseModel):
    """PRD section 76. Eight dimensions, each out of 10."""

    correctness: int = Field(ge=0, le=10)
    failure_clarity: int = Field(ge=0, le=10)
    plausibility: int = Field(ge=0, le=10)
    concept_relevance: int = Field(ge=0, le=10)
    evidence_quality: int = Field(ge=0, le=10)
    difficulty_alignment: int = Field(ge=0, le=10)
    ambiguity_risk: int = Field(ge=0, le=10, description="10 = no ambiguity risk")
    student_usefulness: int = Field(ge=0, le=10)
    notes: str = ""

    @property
    def total(self) -> float:
        """Mean across dimensions, 0-10."""
        return round(
            (
                self.correctness
                + self.failure_clarity
                + self.plausibility
                + self.concept_relevance
                + self.evidence_quality
                + self.difficulty_alignment
                + self.ambiguity_risk
                + self.student_usefulness
            )
            / 8,
            2,
        )
