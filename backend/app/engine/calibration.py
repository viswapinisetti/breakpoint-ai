"""Confidence calibration: how well a student's certainty matches their accuracy.

Every other metric here asks whether a judgment was right. This one asks
whether the student *knew* - because the failure this product exists to train
is not being wrong, it is being confidently wrong about a confident AI. A
student who says "95% sure" and is wrong half the time has a different problem
from one who says "guessing" and is right half the time, and no accuracy
number tells them apart.

Definitions, all standard:

  * **Brier score** - mean squared error between stated confidence and the
    outcome, 0 (perfect) to 1 (perfectly wrong). Guessing at 50% scores 0.25.
  * **Gap** - mean confidence minus accuracy. Positive is overconfidence,
    negative underconfidence.
  * **Reliability bands** - accuracy within each confidence band. A calibrated
    student's accuracy tracks the band: about 80% right among the 80% calls.

Two named errors carry the product's own meaning:

  * **Over-trust** - confident and wrong.
  * **Under-trust** - unsure and right: the student had it and hedged.

Pure functions over plain records, so scripts/calibration_test.py can check
them without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.engine.scoring import MIN_SAMPLE_FOR_RATES

# A judgment at or above this confidence counts as confident, and one at or
# below UNSURE_AT as a hedge. They match the ends of the four-step scale the
# player offers (50 / 65 / 80 / 95), so a student's own words map onto them.
CONFIDENT_AT = 80
UNSURE_AT = 65
# An AI badge this loud is the one worth noticing when it turns out wrong.
LOUD_AI_AT = 85
RECENT_DAYS = 7

# Reliability bands. The first sits below the two-way chance line and is
# normally empty, but a student can still send it through the API, and a
# silently dropped judgment would make these counts disagree with the ledger.
BANDS: tuple[tuple[int, int, str], ...] = (
    (0, 50, "Below even"),
    (50, 65, "Guessing"),
    (65, 80, "Leaning"),
    (80, 90, "Fairly sure"),
    (90, 101, "Certain"),
)


@dataclass(frozen=True)
class Judgment:
    """One judgment, as calibration sees it."""

    confidence: int | None
    correct: bool
    #: The AI's displayed confidence badge for this artifact.
    ai_confidence: int = 0
    #: True when the verdict took the AI at its word (an approval).
    sided_with_ai: bool = False
    judged_at: datetime | None = None


@dataclass
class Band:
    label: str
    low: int
    high: int
    count: int = 0
    mean_confidence: float | None = None
    accuracy: float | None = None


@dataclass
class Report:
    judged: int = 0
    mean_confidence: float | None = None
    accuracy: float | None = None
    gap: float | None = None
    brier: float | None = None
    over_trust: int = 0
    under_trust: int = 0
    believed_confident_ai: int = 0
    bands: list[Band] = field(default_factory=list)
    recent_days: int = RECENT_DAYS
    recent_judged: int = 0
    recent_over_trust: int = 0
    recent_believed_confident_ai: int = 0
    min_sample: int = MIN_SAMPLE_FOR_RATES

    def as_dict(self) -> dict:
        return {
            "judged": self.judged,
            "mean_confidence": self.mean_confidence,
            "accuracy": self.accuracy,
            "gap": self.gap,
            "brier": self.brier,
            "over_trust": self.over_trust,
            "under_trust": self.under_trust,
            "believed_confident_ai": self.believed_confident_ai,
            "bands": [
                {
                    "label": b.label,
                    "low": b.low,
                    "high": b.high,
                    "count": b.count,
                    "mean_confidence": b.mean_confidence,
                    "accuracy": b.accuracy,
                }
                for b in self.bands
            ],
            "recent_days": self.recent_days,
            "recent_judged": self.recent_judged,
            "recent_over_trust": self.recent_over_trust,
            "recent_believed_confident_ai": self.recent_believed_confident_ai,
            "min_sample": self.min_sample,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even for timezone-aware columns, and
    comparing one against an aware cut-off raises. Stored times are UTC."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def believed_confident_ai(j: Judgment) -> bool:
    """Took a loudly confident AI at its word, and it was wrong."""
    return not j.correct and j.sided_with_ai and j.ai_confidence >= LOUD_AI_AT


def build(judgments: list[Judgment], *, now: datetime | None = None) -> Report:
    """Calibration over the judgments that carry a confidence.

    Judgments recorded before the student was asked - or sent through the API
    without one - are skipped rather than assumed: a missing confidence is not
    a 50.
    """
    rated = [j for j in judgments if j.confidence is not None]
    report = Report(judged=len(rated))
    report.bands = [Band(label=name, low=low, high=high) for low, high, name in BANDS]
    if not rated:
        return report

    confidences = [float(j.confidence or 0) for j in rated]
    outcomes = [1.0 if j.correct else 0.0 for j in rated]

    # Rates stay hidden below the sample where they would mislead, the same
    # rule the trust metrics follow.
    if len(rated) >= MIN_SAMPLE_FOR_RATES:
        report.mean_confidence = round(_mean(confidences), 1)
        report.accuracy = round(_mean(outcomes) * 100, 1)
        report.gap = round(report.mean_confidence - report.accuracy, 1)
        report.brier = round(
            _mean([(c / 100 - o) ** 2 for c, o in zip(confidences, outcomes)]), 3
        )

    # Counts are always shown: "you were 95% sure and wrong twice" needs no
    # sample size to be true, and it is the moment worth naming.
    report.over_trust = sum(
        1 for j in rated if (j.confidence or 0) >= CONFIDENT_AT and not j.correct
    )
    report.under_trust = sum(
        1 for j in rated if (j.confidence or 0) <= UNSURE_AT and j.correct
    )
    report.believed_confident_ai = sum(1 for j in rated if believed_confident_ai(j))

    for band in report.bands:
        inside = [j for j in rated if band.low <= (j.confidence or 0) < band.high]
        band.count = len(inside)
        if inside:
            band.mean_confidence = round(
                _mean([float(j.confidence or 0) for j in inside]), 1
            )
            band.accuracy = round(
                _mean([1.0 if j.correct else 0.0 for j in inside]) * 100, 1
            )

    since = (now or datetime.now(UTC)) - timedelta(days=RECENT_DAYS)
    recent = [
        j for j in rated if (moment := _aware(j.judged_at)) is not None and moment >= since
    ]
    report.recent_judged = len(recent)
    report.recent_over_trust = sum(
        1 for j in recent if (j.confidence or 0) >= CONFIDENT_AT and not j.correct
    )
    report.recent_believed_confident_ai = sum(
        1 for j in recent if believed_confident_ai(j)
    )
    return report


def judgment_note(
    *, confidence: int | None, correct: bool, ai_confidence: int, sided_with_ai: bool
) -> str:
    """What to say about this one judgment, immediately after it is recorded.

    Separate from the verdict message because it comments on the student's
    certainty rather than their answer: being right while hedging and being
    wrong while sure are both worth hearing about at the moment they happen.
    """
    if confidence is None:
        return ""
    if correct:
        if confidence <= UNSURE_AT:
            return (
                f"Right, at {confidence}% sure. You had it and hedged - worth asking "
                "what would have made you certain."
            )
        return f"Right, at {confidence}% sure. That is what calibration looks like."
    if confidence >= CONFIDENT_AT:
        if sided_with_ai and ai_confidence >= LOUD_AI_AT:
            return (
                f"You were {confidence}% sure and wrong, siding with an AI showing "
                f"{ai_confidence}%. Two confident parties, one wrong answer: "
                "confidence was never the evidence."
            )
        return (
            f"You were {confidence}% sure and wrong. Notice what made it feel "
            "settled - that is the habit this trains."
        )
    return (
        f"Wrong, but you were only {confidence}% sure, and that doubt was earned. "
        "Next time act on it: check the step you were least sure about."
    )
