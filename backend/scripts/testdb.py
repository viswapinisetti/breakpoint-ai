"""Give a test script its own throwaway database.

The suites assert on absolute state - "the review queue starts empty", "five
investigations recorded", "this judgment has not been made yet". Against the
shared development database those assertions hold exactly once, and every run
after the first fails on leftovers rather than on a defect. That is worse than
no test, because the failure is uninformative and people learn to ignore it.

Call `use_temp_database()` *before* importing anything from `app`: settings are
read at import time, so the environment has to be set first.

    from scripts.testdb import use_temp_database

    use_temp_database()

    from app.main import app  # noqa: E402 - must follow use_temp_database
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


PREFIX = "bp-test-db-"


def use_temp_database() -> Path:
    """Point the app at a fresh SQLite file, removed when the process exits.

    Idempotent: under pytest the root conftest calls this before collection,
    and a suite module imported afterwards calls it again at import time. The
    second call reuses the first database rather than silently stranding it,
    so the whole pytest process shares one throwaway file. Run standalone,
    each script still gets its own.
    """
    existing = os.environ.get("BREAKPOINT_DATABASE_URL", "")
    if PREFIX in existing:
        return Path(existing.removeprefix("sqlite:///"))

    if "app.config" in sys.modules:
        raise RuntimeError(
            "app.config is already imported, so the database URL is fixed. "
            "Call use_temp_database() before any `app` import."
        )

    directory = Path(tempfile.mkdtemp(prefix=PREFIX))
    path = directory / "breakpoint.db"
    os.environ["BREAKPOINT_DATABASE_URL"] = f"sqlite:///{path}"
    atexit.register(shutil.rmtree, directory, True)
    return path
