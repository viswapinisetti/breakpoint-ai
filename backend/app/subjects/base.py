"""Subject adapter contract (PRD section 50).

A new subject implements six things and nothing else:

    1. artifact types          4. evidence types
    2. failure taxonomy        5. domain validator
    3. verification tools      6. subject-specific UI tools

Everything else - dashboard, challenge flow, Evidence Board, debate, replay,
scoring, analytics, history, streak, orchestration, admin - is universal and
must never be forked per subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.engine.contracts import Challenge, EvidenceType


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a domain validator run (PRD section 46.6)."""

    passed: bool
    validator: str
    detail: str = ""

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True)
class Tool:
    """An investigation tool the student may open (PRD section 39)."""

    key: str
    label: str
    icon: str = ""


@dataclass(frozen=True)
class SubjectConfig:
    """Static, data-driven description of a subject.

    Adding a subject means adding one of these to the catalog. No engine change.
    """

    key: str
    number: int
    name: str
    tagline: str
    tier: str  # "A" = deep (Aptitude), "B" = representative
    topics: tuple[str, ...]
    artifact_types: tuple[str, ...]
    failure_categories: tuple[str, ...]
    evidence_types: tuple[EvidenceType, ...]
    tools: tuple[Tool, ...] = field(default_factory=tuple)
    accent: str = "#2563EB"


class SubjectAdapter(Protocol):
    """Runtime behaviour a subject may contribute.

    Tier B subjects get the default adapter (no deterministic validation);
    Tier A subjects (Aptitude) implement `validate` with real computation,
    which is what makes generated challenges safe to publish.
    """

    config: SubjectConfig

    def validate(self, challenge: Challenge) -> list[ValidationResult]:
        """Deterministically check a challenge before publication."""
        ...


class DefaultAdapter:
    """Adapter for subjects with no deterministic validator yet.

    Returns a single informational result so the pipeline records that
    deterministic checking was unavailable rather than silently passing.
    """

    def __init__(self, config: SubjectConfig) -> None:
        self.config = config

    def validate(self, challenge: Challenge) -> list[ValidationResult]:
        return [
            ValidationResult(
                passed=True,
                validator="no_deterministic_validator",
                detail=(
                    f"{self.config.name} has no deterministic validator; "
                    "relying on critic + human review."
                ),
            )
        ]
