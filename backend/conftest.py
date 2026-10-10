"""Pytest bootstrap.

This file exists to solve one ordering problem. `app.config` reads settings at
import time, so the database URL is fixed the moment anything under `app` is
imported. Pytest imports the root conftest before it collects any test module,
which makes this the only place that can redirect the app at a throwaway
database and still be guaranteed to run first.

Nothing from `app` may be imported at module level here - doing so would fix
the URL before the redirect happens, which is the exact bug this prevents.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.testdb import use_temp_database  # noqa: E402

TEST_DB = use_temp_database()
