"""Investigation Score, verification skills, and trust metrics.

PRD v0.2 sections 10.1, 15.1. Deliberately *not* a mastery score: it measures
one attempt's investigation quality, and Topic Mastery stays in its own system.

Two properties of the v0.2 model are easy to get wrong and are enforced here:

* **Band anchors, not linear scales.** Each dimension has discrete rubric
  bands. Interpolating between them would invent precision the rubric does not
  claim and would make two reviewers' scores incomparable.
* **Assistance is not a scoring dimension.** Hints and reveals do not deduct
  points - the v0.2 rubric drops the old "independence" component entirely.
  Instead the attempt is flagged `assisted`, which excludes it from
  independent-success metrics. Penalising help teaches students to avoid it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.contracts import Judgment, TruthState

# PRD v0.2 section 10.1 - maximum points per dimension, summing to 100.
MAX_POINTS = {
    "initial_judgment": 20,
    "evidence": 35,
    "reasoning": 25,
    "outcome_task": 20,
}


def _evidence_band(strength: float, accepted: bool) -> int:
    """0 absent/irrelevant | 10 relevant but insufficient |
    20 materially useful but incomplete | 35 reproducible and sufficient."""
    if strength < 2.0:
        return 0
    if not accepted:
        # Relevant work that did not establish the claim tops out at
        # "materially useful but incomplete".
        return 10 if strength < 6.0 else 20
    if strength < 7.5:
        return 20
    return 35


def _reasoning_band(quality: float) -> int:
    """0 absent/incorrect | 10 partial connection | 25 explains the governing
    assumption and the first cause (or the basis of validity)."""
    if quality < 3.0:
        return 0
    if quality < 7.0:
        return 10
    return 25


def _outcome_band(*, attempted: bool, accepted: bool, partial: bool) -> int:
    """0 incorrect | 10 partial | 20 complete and verified.

    "Outcome task" is repair for a flawed artifact, justification for a valid
    one, and naming the missing condition for an insufficient-information one.
    """
    if accepted:
        return 20
    if partial or attempted:
        return 10
    return 0


@dataclass(frozen=True)
class ScoreBreakdown:
    """One attempt's Investigation Score, out of 100."""

    initial_judgment: int
    evidence: int
    reasoning: int
    outcome_task: int
    assisted: bool = False

    @property
    def total(self) -> int:
        return (
            self.initial_judgment + self.evidence + self.reasoning + self.outcome_task
        )

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "initial_judgment": self.initial_judgment,
            "evidence": self.evidence,
            "reasoning": self.reasoning,
            "outcome_task": self.outcome_task,
            "total": self.total,
            "assisted": self.assisted,
        }


def score_attempt(
    *,
    initial_judgment_correct: bool,
    evidence_strength: float,
    evidence_accepted: bool,
    reasoning_quality: float,
    outcome_attempted: bool,
    outcome_accepted: bool,
    outcome_partial: bool = False,
    assisted: bool = False,
) -> ScoreBreakdown:
    """Score one completed investigation.

    `evidence_strength` and `reasoning_quality` are 0-10 from the evaluator.
    `initial_judgment_correct` is recorded *before* any reveal, so a student
    who revises after help keeps the evidence and reasoning credit they earned
    while the record still shows the first judgment was wrong (PRD v0.2 10.1).
    """
    return ScoreBreakdown(
        initial_judgment=MAX_POINTS["initial_judgment"] if initial_judgment_correct else 0,
        evidence=_evidence_band(evidence_strength, evidence_accepted),
        reasoning=_reasoning_band(reasoning_quality),
        outcome_task=_outcome_band(
            attempted=outcome_attempted,
            accepted=outcome_accepted,
            partial=outcome_partial,
        ),
        assisted=assisted,
    )


# --- Verification skills (PRD section 53) ----------------------------------

SKILL_KEYS = (
    "counterexample_building",
    "assumption_checking",
    "logical_verification",
    "error_localization",
    "evidence_quality",
)

_EVIDENCE_SKILL_MAP = {
    "counterexample": "counterexample_building",
    "test_case": "counterexample_building",
    "calculation": "logical_verification",
    "data_point": "logical_verification",
    "contradiction": "assumption_checking",
    "rule": "assumption_checking",
    "trace": "error_localization",
    "rewrite": "evidence_quality",
}


def skill_from_evidence(evidence_type: str) -> str | None:
    """The verification skill an evidence card exercises."""
    return _EVIDENCE_SKILL_MAP.get(evidence_type)


# --- Trust metrics (PRD v0.2 section 15.1) ---------------------------------

# Below this many resolved eligible attempts, show "Not enough evidence yet"
# rather than a rate computed from a handful of samples.
MIN_SAMPLE_FOR_RATES = 10


@dataclass(frozen=True)
class JudgmentMatrix:
    """The full three-way judgment matrix (PRD v0.2 section 15.1).

    A two-way "right or wrong" summary hides the distinction that matters: a
    student who says "insufficient information" about a determinate artifact is
    wrong, but is making a different error from one who approves a flawed
    artifact - and neither is a false alarm.

    Counts cover mixed-mode, resolved, non-demo attempts only. Guided
    Find-the-Failure attempts disclose that a failure exists, so including them
    would inflate detection rates (PRD v0.2 section 3.2).
    """

    counts: dict[tuple[str, str], int]

    @classmethod
    def build(cls, pairs: list[tuple[str, str]]) -> JudgmentMatrix:
        """`pairs` are (truth_state, judgment) for each resolved attempt."""
        counts: dict[tuple[str, str], int] = {}
        for truth, judgment in pairs:
            key = (truth, judgment)
            counts[key] = counts.get(key, 0) + 1
        return cls(counts=counts)

    def _sum(self, *, truth: str | None = None, judgment: str | None = None) -> int:
        return sum(
            n
            for (t, j), n in self.counts.items()
            if (truth is None or t == truth) and (judgment is None or j == judgment)
        )

    @property
    def resolved(self) -> int:
        return sum(self.counts.values())

    @property
    def correct(self) -> int:
        return sum(
            n
            for (t, j), n in self.counts.items()
            if j == Judgment(JUDGMENT_BY_TRUTH[t]).value
        )

    @property
    def first_judgment_accuracy(self) -> float | None:
        """None when the sample is too small to report honestly."""
        if self.resolved < MIN_SAMPLE_FOR_RATES:
            return None
        return round(self.correct / self.resolved * 100, 1)

    @property
    def false_alarm_rate(self) -> float | None:
        """Valid artifacts that were challenged, over resolved valid artifacts.

        Note the denominator: it is *valid artifacts*, not all attempts. Saying
        "insufficient information" about a valid artifact is an error but not a
        false alarm, so it is excluded from the numerator.
        """
        valid = self._sum(truth=TruthState.VALID.value)
        if valid < MIN_SAMPLE_FOR_RATES:
            return None
        challenged = self._sum(
            truth=TruthState.VALID.value, judgment=Judgment.CHALLENGE.value
        )
        return round(challenged / valid * 100, 1)

    @property
    def missed_failure_rate(self) -> float | None:
        """Flawed artifacts that were approved, over resolved flawed artifacts."""
        flawed = self._sum(truth=TruthState.FLAWED.value)
        if flawed < MIN_SAMPLE_FOR_RATES:
            return None
        approved = self._sum(
            truth=TruthState.FLAWED.value, judgment=Judgment.APPROVE.value
        )
        return round(approved / flawed * 100, 1)

    def as_grid(self) -> list[dict[str, object]]:
        """Row per truth state, column per judgment - for the progress screen."""
        return [
            {
                "truth_state": truth.value,
                "total": self._sum(truth=truth.value),
                "judgments": {
                    j.value: self._sum(truth=truth.value, judgment=j.value)
                    for j in Judgment
                },
            }
            for truth in TruthState
        ]


JUDGMENT_BY_TRUTH = {
    TruthState.FLAWED.value: Judgment.CHALLENGE.value,
    TruthState.VALID.value: Judgment.APPROVE.value,
    TruthState.INSUFFICIENT_INFORMATION.value: Judgment.INSUFFICIENT_INFORMATION.value,
}
