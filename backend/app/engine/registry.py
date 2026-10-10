"""Subject adapter registry (PRD section 50).

The engine resolves adapters through this module only. Tier A subjects register
a real validator; every other subject falls back to `DefaultAdapter`, which is
why all 19 subjects work on day one without 19 implementations.
"""

from __future__ import annotations

from app.subjects.aptitude import AptitudeAdapter, NumericAdapter
from app.subjects.databases import SqlAdapter
from app.subjects.programming import ProgrammingAdapter
from app.subjects.base import DefaultAdapter, SubjectAdapter, SubjectConfig
from app.subjects.catalog import SUBJECTS, BY_KEY

# Subjects with a deterministic domain validator. Add a key here as each
# subject graduates from Tier B to Tier A.
_SPECIALISED: dict[str, type] = {
    "aptitude": AptitudeAdapter,
    "programming": ProgrammingAdapter,
    # DSA artifacts are code too, so the same executable validator applies:
    # a claimed bug must actually differ from the reference on some input.
    "dsa": ProgrammingAdapter,
    # Numeric artifacts get their arithmetic checked; textual ones in the same
    # subject are judged on reasoning.
    "data-analytics": NumericAdapter,
    "mathematics": NumericAdapter,
    # SQL artifacts are executed against their own seeded tables; schema,
    # NoSQL and query-plan artifacts in the same subject fall back to review.
    "databases": SqlAdapter,
}

_cache: dict[str, SubjectAdapter] = {}


def adapter_for(subject_key: str) -> SubjectAdapter:
    """Return the adapter for a subject, or raise KeyError if unknown."""
    if subject_key in _cache:
        return _cache[subject_key]
    config = BY_KEY.get(subject_key)
    if config is None:
        raise KeyError(f"unknown subject {subject_key!r}")
    factory = _SPECIALISED.get(subject_key)
    adapter = factory(config) if factory else DefaultAdapter(config)
    _cache[subject_key] = adapter
    return adapter


def config_for(subject_key: str) -> SubjectConfig | None:
    return BY_KEY.get(subject_key)


def all_configs() -> tuple[SubjectConfig, ...]:
    return SUBJECTS


def has_deterministic_validator(subject_key: str) -> bool:
    return subject_key in _SPECIALISED
