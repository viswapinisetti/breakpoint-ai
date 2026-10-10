"""The remaining suites, run as subprocesses.

These are not yet converted to native pytest. Each is wrapped here so CI gates
on them and a failure is attributed to the right suite, while they keep the
property the originals rely on: a fresh process means a fresh throwaway
database, which is what lets them assert on absolute state ("the review queue
starts empty", "five investigations recorded").

Converting one means moving it to its own `test_<name>.py` and deleting its
entry from SUITES - the pattern is in tests/test_e2e.py.

`check_provider` is deliberately absent: it needs a live API key and spends
money, so it is never part of an automated run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent

SUITES = [
    ("modes", "scripts.modes_test", "modes F and G, decided by execution"),
    ("admin", "scripts.admin_test", "Challenge Studio and governance"),
    ("review", "scripts.review_test", "appeals and the staff review queue"),
    ("auth", "scripts.auth_check", "identity config and the claim contract"),
    ("calibration", "scripts.calibration_test", "confidence calibration maths"),
    ("accounts", "scripts.accounts_test", "sign-up, sessions, Google (offline)"),
]


@pytest.mark.parametrize(
    "name,module,description",
    SUITES,
    ids=[name for name, _, _ in SUITES],
)
def test_suite_passes(name: str, module: str, description: str) -> None:
    """Run one suite in a clean process and require exit code 0."""
    completed = subprocess.run(
        [sys.executable, "-m", module],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        # A fresh environment without the pytest temp DB, so the suite creates
        # its own exactly as it does when run by hand.
        env={
            k: v
            for k, v in __import__("os").environ.items()
            if k != "BREAKPOINT_DATABASE_URL"
        },
    )
    if completed.returncode != 0:
        pytest.fail(
            f"{module} ({description}) exited {completed.returncode}\n\n"
            f"--- stdout ---\n{completed.stdout[-4000:]}\n"
            f"--- stderr ---\n{completed.stderr[-2000:]}"
        )


def test_every_suite_script_is_covered() -> None:
    """A new scripts/*_test.py that nobody wired up is a silent coverage hole."""
    wired = {module.split(".")[-1] for _, module, _ in SUITES}
    wired |= {"e2e_test", "validate_content"}  # converted to native pytest
    wired |= {"check_provider"}  # needs a live key; never automated

    on_disk = {
        path.stem
        for path in (BACKEND_ROOT / "scripts").glob("*.py")
        if path.stem.endswith("_test") or path.stem in {"auth_check", "check_provider"}
    }

    missing = on_disk - wired
    assert not missing, (
        f"suite script(s) not run by any test: {sorted(missing)}. "
        "Add to SUITES, convert to native pytest, or document the exclusion."
    )
