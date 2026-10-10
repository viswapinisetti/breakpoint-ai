"""Typed evidence cards and the validation hierarchy (PRD v0.2 sections 6.4, 9.1).

An evidence card is structured, not a paragraph. That is the whole point: a
free-text box lets "I think step 3 is wrong" look like evidence, whereas a
Calculation card with an expression, a value and a referenced step either
checks out or does not.

Fields vary by card type (PRD v0.2 section 6.4):

    Calculation    expression, value, unit, reference
    Contradiction  two references and the conflict between them
    Counterexample input, expected outcome, observed outcome
    TestCase       condition, expected, observed
    DataPoint      cell reference and value
    Rule           the principle and how it is violated
    Trace          the execution path and where it fails
    Rewrite        the original reference and the replacement

Every card also carries `why_supports` - "Why this supports my judgment" -
because a checked calculation is not on its own an argument.

The validation hierarchy runs in the order section 9.1 sets out. Stages 1 and 2
here are deterministic and cheap; stages 3-5 (relevance, rubric, human review)
happen in the runtime evaluator. Two rules from section 9.2 are load-bearing:

    Deterministic success is necessary but NOT sufficient for relevance.
    Deterministic failure CANNOT be overridden by a fluent model response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engine.arithmetic import ExpressionError, evaluate, values_agree

# PRD v0.2 section 6.4 - "The board supports 1-5 cards per submission by default."
MIN_CARDS = 1
MAX_CARDS = 5


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class CheckResult:
    """One deterministic check against one card.

    `reason_code` is machine-readable so analytics can count failure modes
    without parsing prose (PRD v0.2 section 9.2).
    """

    card_index: int
    check: str
    status: CheckStatus
    reason_code: str
    detail: str
    computed: str | None = None

    @property
    def failed(self) -> bool:
        return self.status == CheckStatus.FAILED

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_index": self.card_index,
            "check": self.check,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "computed": self.computed,
        }


# --- card payloads ---------------------------------------------------------


class EvidenceCard(BaseModel):
    """Base card. `type` selects which extra fields are required."""

    type: str
    # A reference into the artifact: a step index, a table cell, a line.
    reference: str = Field(default="", max_length=120)
    references_step: int | None = None
    why_supports: str = Field(default="", max_length=2000)

    # Type-specific fields. Kept flat rather than a discriminated union so the
    # board can hold partially-filled drafts while the student is still typing;
    # completeness is enforced at submission by `validate_card`.
    expression: str = Field(default="", max_length=500)
    value: str = Field(default="", max_length=120)
    unit: str = Field(default="", max_length=40)
    reference_b: str = Field(default="", max_length=120)
    conflict: str = Field(default="", max_length=2000)
    input: str = Field(default="", max_length=2000)
    expected: str = Field(default="", max_length=500)
    observed: str = Field(default="", max_length=500)
    rule: str = Field(default="", max_length=2000)
    replacement: str = Field(default="", max_length=2000)

    def summary(self) -> str:
        """Human-readable rendering, used in evaluator prompts and history."""
        bits: list[str] = [f"[{self.type}]"]
        if self.references_step:
            bits.append(f"step {self.references_step}")
        elif self.reference:
            bits.append(self.reference)
        for label, val in (
            ("expression", self.expression),
            ("value", f"{self.value} {self.unit}".strip()),
            ("vs", self.reference_b),
            ("conflict", self.conflict),
            ("input", self.input),
            ("expected", self.expected),
            ("observed", self.observed),
            ("rule", self.rule),
            ("replacement", self.replacement),
        ):
            if val and val.strip():
                bits.append(f"{label}: {val.strip()}")
        if self.why_supports.strip():
            bits.append(f"because: {self.why_supports.strip()}")
        return " | ".join(bits)


class EvidenceSubmissionRequest(BaseModel):
    """One immutable submission of 1-5 cards (PRD v0.2 sections 6.4, 13.3)."""

    cards: list[EvidenceCard] = Field(min_length=MIN_CARDS, max_length=MAX_CARDS)
    # Required so a retried request cannot create a second submission
    # (PRD v0.2 section 13.3).
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def _reject_empty(self) -> EvidenceSubmissionRequest:
        """PRD v0.2 section 6.4 - "Empty evidence cannot be submitted."."""
        for i, card in enumerate(self.cards, 1):
            if not _has_content(card):
                raise ValueError(f"card {i} is empty")
        return self


def _has_content(card: EvidenceCard) -> bool:
    return any(
        (getattr(card, f) or "").strip()
        for f in (
            "expression",
            "value",
            "conflict",
            "input",
            "expected",
            "observed",
            "rule",
            "replacement",
            "why_supports",
        )
    )


# Required fields per card type (PRD v0.2 section 6.4).
REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "calculation": ("expression", "value"),
    "contradiction": ("reference", "reference_b", "conflict"),
    "counterexample": ("input", "expected", "observed"),
    "test_case": ("input", "expected"),
    "data_point": ("reference", "value"),
    "rule": ("rule",),
    "trace": ("input",),
    "rewrite": ("replacement",),
}


@dataclass
class ValidationOutcome:
    """Result of the deterministic stages of the hierarchy."""

    structural_errors: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def has_structural_errors(self) -> bool:
        return bool(self.structural_errors)

    @property
    def deterministic_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.failed]

    @property
    def any_check_ran(self) -> bool:
        return any(c.status != CheckStatus.NOT_APPLICABLE for c in self.checks)


def validate_structure(
    cards: list[EvidenceCard], *, step_count: int, allowed_types: set[str]
) -> list[str]:
    """Stage 1: schema, references, input domain.

    Returns human-readable errors. An empty list means the submission is
    well-formed enough to check arithmetically.
    """
    errors: list[str] = []
    for i, card in enumerate(cards, 1):
        if card.type not in REQUIRED_FIELDS:
            errors.append(f"Card {i}: unknown evidence type {card.type!r}.")
            continue
        if allowed_types and card.type not in allowed_types:
            errors.append(
                f"Card {i}: {card.type} evidence is not accepted for this subject."
            )
        for required in REQUIRED_FIELDS[card.type]:
            if not (getattr(card, required) or "").strip():
                errors.append(
                    f"Card {i} ({card.type}): {required.replace('_', ' ')} is required."
                )
        if card.references_step is not None and not (
            1 <= card.references_step <= step_count
        ):
            errors.append(
                f"Card {i}: step {card.references_step} does not exist "
                f"(this artifact has {step_count} steps)."
            )
    return errors


def run_deterministic_checks(cards: list[EvidenceCard]) -> list[CheckResult]:
    """Stage 2: arithmetic and self-consistency checks that need no model.

    Only checks that can be settled by computation appear here. A card type
    with nothing computable returns NOT_APPLICABLE rather than a pass, so a
    later stage cannot mistake "we did not check" for "this checks out".
    """
    results: list[CheckResult] = []
    for i, card in enumerate(cards, 1):
        if card.type == "calculation":
            results.append(_check_calculation(i, card))
        elif card.type == "contradiction":
            results.append(_check_contradiction(i, card))
        elif card.type in ("counterexample", "test_case"):
            results.append(_check_differing_outcomes(i, card))
        else:
            results.append(
                CheckResult(
                    card_index=i,
                    check="deterministic",
                    status=CheckStatus.NOT_APPLICABLE,
                    reason_code="no_deterministic_check",
                    detail=f"{card.type} evidence is judged on its reasoning.",
                )
            )
    return results


def _check_calculation(index: int, card: EvidenceCard) -> CheckResult:
    """Evaluate the expression and compare it with the stated value."""
    try:
        result = evaluate(card.expression)
    except ExpressionError as exc:
        return CheckResult(
            card_index=index,
            check="arithmetic",
            status=CheckStatus.FAILED,
            reason_code="expression_invalid",
            detail=f"Could not evaluate {card.expression!r}: {exc}",
        )

    if values_agree(result.normalised, card.value):
        return CheckResult(
            card_index=index,
            check="arithmetic",
            status=CheckStatus.PASSED,
            reason_code="arithmetic_verified",
            detail=f"{card.expression} = {result.normalised}, as stated.",
            computed=result.normalised,
        )
    return CheckResult(
        card_index=index,
        check="arithmetic",
        status=CheckStatus.FAILED,
        reason_code="value_mismatch",
        detail=(
            f"{card.expression} evaluates to {result.normalised}, but you wrote "
            f"{card.value}."
        ),
        computed=result.normalised,
    )


def _check_contradiction(index: int, card: EvidenceCard) -> CheckResult:
    """A contradiction must point at two *different* places."""
    a = card.reference.strip().lower()
    b = card.reference_b.strip().lower()
    if a and b and a == b:
        return CheckResult(
            card_index=index,
            check="references",
            status=CheckStatus.FAILED,
            reason_code="same_reference_twice",
            detail=(
                f"Both references point at {card.reference!r}. A contradiction "
                "needs two different statements that conflict."
            ),
        )
    return CheckResult(
        card_index=index,
        check="references",
        status=CheckStatus.PASSED,
        reason_code="references_distinct",
        detail=f"Compares {card.reference} against {card.reference_b}.",
    )


def _check_differing_outcomes(index: int, card: EvidenceCard) -> CheckResult:
    """A counterexample is only a counterexample if the outcomes differ."""
    if card.observed.strip() and values_agree(card.expected, card.observed):
        return CheckResult(
            card_index=index,
            check="outcomes",
            status=CheckStatus.FAILED,
            reason_code="outcomes_identical",
            detail=(
                f"Expected and observed are both {card.expected!r}, so this input "
                "does not break the claim."
            ),
        )
    return CheckResult(
        card_index=index,
        check="outcomes",
        status=CheckStatus.PASSED,
        reason_code="outcomes_differ",
        detail=(
            f"Input {card.input!r} gives {card.observed or 'a different result'} "
            f"where {card.expected!r} was claimed."
        )
        if card.observed.strip()
        else f"Input {card.input!r} supplied against an expected {card.expected!r}.",
    )


def validate(
    cards: list[EvidenceCard], *, step_count: int, allowed_types: set[str]
) -> ValidationOutcome:
    """Run stages 1 and 2 of the validation hierarchy."""
    errors = validate_structure(
        cards, step_count=step_count, allowed_types=allowed_types
    )
    if errors:
        # No point checking arithmetic on a malformed submission.
        return ValidationOutcome(structural_errors=errors)
    return ValidationOutcome(checks=run_deterministic_checks(cards))


def detect_conflicts(cards: list[EvidenceCard]) -> str | None:
    """Contradictory cards get clarification, not a silent pick (PRD v0.2 9.2).

    If two calculation cards reference the same step with different values, the
    submission argues against itself. Choosing one arbitrarily would tell the
    student their reasoning was accepted when part of it was discarded.
    """
    by_step: dict[int, list[tuple[int, str]]] = {}
    for i, card in enumerate(cards, 1):
        if card.type != "calculation" or card.references_step is None:
            continue
        if not card.value.strip():
            continue
        by_step.setdefault(card.references_step, []).append((i, card.value.strip()))

    for step, entries in by_step.items():
        distinct = {v for _, v in entries}
        if len(distinct) > 1:
            listed = ", ".join(f"card {i} says {v}" for i, v in entries)
            return (
                f"Your cards disagree about step {step}: {listed}. Decide which "
                "value you are claiming and remove or correct the other."
            )
    return None
