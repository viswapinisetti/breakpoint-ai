"""Generation agents: Composer, Failure Injector + Solver, Critic, Quality.

PRD sections 46.2-46.7, 47, 76. These run **offline**, never in the student
request path (PRD section 106), and their output is gated by the deterministic
validator before a human ever reviews it.

The division of labour is deliberate:

* the **Composer** never sees a failure - it writes an honest problem and the
  solver code that computes the true answer;
* the **Injector** never sees the critic - it introduces one pedagogically
  chosen error and must supply the flawed solver that reproduces its own wrong
  answer, which is what makes the failure checkable by computation;
* the **Critic** never sees the intended failure - it gets exactly the student
  view. If it cannot find the failure, the challenge is unfair; if it finds a
  *second* error, the artifact is broken and gets rejected (PRD section 75).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents import prompts
from app.agents.client import structured
from app.engine.contracts import CriticVerdict, QualityScore


class ArtifactField(BaseModel):
    """One student-visible artifact entry.

    A list of key/value pairs rather than a free-form dict: strict JSON Schema
    modes cannot express an open-ended map (they require `additionalProperties:
    false` plus declared properties), so a map silently forces every provider
    down to a weaker structured-output mode. The pipeline folds this back into
    a dict immediately.
    """

    key: str = Field(description="e.g. caption, columns, rows")
    value: str


class BaseProblem(BaseModel):
    """Composer output (PRD section 46.2)."""

    question: str = Field(description="The problem statement shown to the student")
    canonical_solution: str = Field(description="Correct worked solution, plain text")
    canonical_answer: str = Field(description="The correct final answer, bare value")
    solver: str = Field(
        description=(
            "Python that computes the correct answer and assigns it to `answer`. "
            "No imports; `math` and `Fraction` are already available."
        )
    )
    artifact_type: str = Field(description="numeric_solution, logical_argument, ...")
    artifact: list[ArtifactField] = Field(
        default_factory=list,
        description=(
            "Student-visible payload such as table rows, as key/value entries. "
            "For a data table use keys: caption, columns (comma separated), "
            "rows (cells comma separated, rows pipe separated). "
            "Never put solution data here - it is sent to the student."
        ),
    )


class InjectedStep(BaseModel):
    index: int = Field(ge=1)
    text: str


class InjectedFailure(BaseModel):
    """Failure Injection + Solver output (PRD sections 46.3, 46.4)."""

    ai_claim: str = Field(description="The confident one-line claim shown to students")
    ai_solution: list[InjectedStep] = Field(
        description="The AI's visible reasoning, one step per entry"
    )
    ai_final_answer: str = Field(description="The wrong answer the AI arrives at")
    flawed_solver: str = Field(
        description=(
            "Python reproducing the AI's wrong answer via the misconception, "
            "assigning to `answer`. Must equal ai_final_answer when run."
        )
    )
    failure_category: str = Field(description="Taxonomy code F01-F16")
    failure_location: int = Field(
        ge=1, description="1-indexed step where validity first breaks"
    )
    misconception: str
    explanation: str
    why_convincing: str = Field(description="Why a strong student would miss it")
    hint_attention: str
    hint_direction: str
    hint_concept: str
    hint_strong: str
    counterexamples: list[str] = Field(default_factory=list)
    repair: str = Field(description="How the flawed reasoning should be corrected")
    debrief: str = Field(description="Concise post-challenge explanation")
    evidence_summaries: list[str] = Field(
        default_factory=list,
        description="What a valid piece of student evidence would establish",
    )


class CorrectArtifact(BaseModel):
    """Solver output for a false-failure challenge (PRD section 28.10)."""

    ai_claim: str
    ai_solution: list[InjectedStep]
    ai_final_answer: str = Field(description="Must equal the canonical answer")
    why_it_looks_suspicious: str = Field(
        description="What may tempt a student to challenge this correct solution"
    )
    hint_attention: str
    hint_direction: str
    hint_concept: str
    hint_strong: str
    repair: str = Field(default="", description="Empty - nothing to repair")
    debrief: str


def compose(
    *, subject: str, topic: str, concept: str, difficulty: str
) -> BaseProblem:
    """Produce an honest, correct base problem plus its deterministic solver."""
    return structured(
        agent="composer",
        role="generation",
        system=prompts.COMPOSER,
        prompt=(
            f"Subject: {subject}\nTopic: {topic}\nConcept: {concept}\n"
            f"Difficulty level: {difficulty} of 5\n\n"
            "Write one problem for this concept."
        ),
        output_format=BaseProblem,
    )


def inject_failure(
    *,
    problem: BaseProblem,
    desired_failure: str,
    difficulty: str,
) -> InjectedFailure:
    """Introduce one pedagogically meaningful, verifiable failure."""
    return structured(
        agent="failure_injector",
        role="generation",
        system=prompts.INJECTOR,
        prompt=(
            f"QUESTION\n{problem.question}\n\n"
            f"CORRECT SOLUTION\n{problem.canonical_solution}\n\n"
            f"CORRECT ANSWER\n{problem.canonical_answer}\n\n"
            f"DESIRED FAILURE TYPE\n{desired_failure}\n\n"
            f"DIFFICULTY\n{difficulty} of 5\n\n"
            "Produce the flawed AI solution."
        ),
        output_format=InjectedFailure,
    )


def solve_correctly(
    *, problem: BaseProblem, difficulty: str
) -> CorrectArtifact:
    """Produce a genuinely correct artifact for a false-failure challenge."""
    return structured(
        agent="solver_correct",
        role="generation",
        system=prompts.CORRECT_SOLVER,
        prompt=(
            f"QUESTION\n{problem.question}\n\n"
            f"CORRECT SOLUTION\n{problem.canonical_solution}\n\n"
            f"CORRECT ANSWER\n{problem.canonical_answer}\n\n"
            f"DIFFICULTY\n{difficulty} of 5\n\n"
            "Produce the correct, confident solution."
        ),
        output_format=CorrectArtifact,
    )


def critique(*, student_view: dict) -> CriticVerdict:
    """Independent critic. Sees only what a student sees (PRD section 46.5)."""
    steps = "\n".join(
        f"Step {s['index']}: {s['text']}" for s in student_view["ai_solution"]
    )
    return structured(
        agent="critic",
        role="critic",
        system=prompts.CRITIC,
        prompt=(
            f"QUESTION\n{student_view['question']}\n\n"
            f"AI CLAIM\n{student_view['ai_claim']}\n\n"
            f"AI REASONING\n{steps}\n\n"
            f"AI FINAL ANSWER\n{student_view['ai_final_answer']}\n\n"
            "Audit this solution."
        ),
        output_format=CriticVerdict,
        effort="max",
    )


def score_quality(*, challenge_json: str) -> QualityScore:
    """Eight-dimension quality score (PRD section 76)."""
    return structured(
        agent="quality",
        role="critic",
        system=prompts.QUALITY,
        prompt=f"CHALLENGE\n{challenge_json}\n\nScore this challenge.",
        output_format=QualityScore,
    )
