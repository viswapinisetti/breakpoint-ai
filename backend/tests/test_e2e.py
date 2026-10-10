"""The student investigation loop, one test case per assertion.

The journey is deliberately sequential - a judgment depends on the attempt
that preceded it, and the stats at the end depend on every judgment before.
Splitting it into independent tests would mean rebuilding that state many
times over, so the journey runs once at import and each of its ~106 checks
becomes a separately named case:

    pytest tests/test_e2e.py                       # the whole journey
    pytest tests/test_e2e.py -k "leak"             # just the leak check
    pytest tests/test_e2e.py -k "calibration"

A failure then names the step that broke instead of the whole suite.
"""

from __future__ import annotations

import pytest

from scripts import e2e_test

# Runs the full journey exactly once, populating e2e_test.results. Collection
# needs the labels, so this cannot be deferred into a fixture.
_EXIT_CODE = e2e_test.main()
RESULTS = e2e_test.results

assert RESULTS, "the e2e journey recorded no checks - did main() change shape?"


def _case_id(phase: str, label: str) -> str:
    return f"{phase}::{label}".replace(" ", "_")


@pytest.mark.parametrize(
    "phase,label,passed,detail",
    RESULTS,
    ids=[_case_id(phase, label) for phase, label, _, _ in RESULTS],
)
def test_journey_check(phase: str, label: str, passed: bool, detail: str) -> None:
    assert passed, f"[{phase}] {label}" + (f"\n  {detail}" if detail else "")


def test_journey_exit_code_is_clean() -> None:
    """Backstop: catches a failure that main() reported without recording a
    check, which would otherwise pass silently above."""
    assert _EXIT_CODE == 0, f"e2e journey exited {_EXIT_CODE}: {e2e_test.failures}"
