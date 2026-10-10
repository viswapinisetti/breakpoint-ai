"""Process-isolated execution for challenge code (PRD v0.2 section 12.6).

Everything the platform executes - Aptitude solvers, reference implementations,
Break-the-Tests comparisons - goes through here. The guarantees, stated plainly
so nobody over-trusts them:

* **Process isolation.** A fresh `python -I -S` child per run. No site
  packages, no `PYTHONPATH`, no inherited interpreter state. A crash, a
  `SystemExit` or a segfault takes down the child, not the API worker.
* **Wall-clock timeout.** Enforced by the parent, which kills the whole child
  process tree on expiry. This is the backstop that always holds.
* **Import allowlist and restricted builtins.** No `open`, no `exec`, no
  `__import__` of `os`/`socket`/`subprocess`. Enforced in the child before the
  payload runs (see `_sandbox_child.py`).
* **No environment inheritance.** The child gets a minimal env, so API keys and
  database URLs are not visible to it.
* **Empty working directory.** A throwaway temp directory, removed afterwards.

What this is *not*: a security boundary against a determined attacker. CPython
in-process restrictions have known escapes, and on Windows there is no
`setrlimit`, so **memory is bounded only on POSIX** - on Windows a payload can
allocate until the OS pushes back, and the timeout is what stops it. That is
acceptable here because payloads are authored or reviewed content, not
arbitrary student uploads; student input reaches the sandbox only as *data*
(`ast.literal_eval`-parsed test arguments), never as code. If that ever changes,
this needs a container or a jailed worker, not a bigger allowlist.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CHILD = Path(__file__).with_name("_sandbox_child.py")

DEFAULT_TIMEOUT = 5.0
MAX_SOURCE_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 256 * 1024


class SandboxError(RuntimeError):
    """The run could not be completed (timeout, crash, protocol failure)."""


@dataclass(slots=True)
class CallOutcome:
    """One invocation of the entry point."""

    ok: bool
    value: Any = None
    error: str = ""


@dataclass(slots=True)
class SandboxResult:
    ok: bool
    calls: list[CallOutcome] = field(default_factory=list)
    names: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    violation: bool = False
    stdout: str = ""
    duration_ms: int = 0

    @property
    def value(self) -> Any:
        """The single call's value, for the common one-call case."""
        if not self.calls:
            raise SandboxError("no calls were made")
        first = self.calls[0]
        if not first.ok:
            raise SandboxError(first.error)
        return first.value


def _child_env() -> dict[str, str]:
    """A minimal environment. Nothing from the parent's secrets survives."""
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    # Windows needs SYSTEMROOT for the C runtime to initialise; POSIX needs
    # nothing. Deliberately no PATH, no HOME, no API keys, no DATABASE_URL.
    for passthrough in ("SYSTEMROOT", "SystemRoot", "COMSPEC"):
        if passthrough in os.environ:
            env[passthrough] = os.environ[passthrough]
    return env


def run(
    source: str,
    *,
    entry_point: str | None = None,
    calls: list[list[Any]] | None = None,
    read_names: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> SandboxResult:
    """Execute `source` in a sandboxed child and return what happened.

    With an `entry_point`, each element of `calls` is an argument list applied
    to it. Without one, the values of `read_names` are read back out of the
    module namespace - the shape the Aptitude solvers use.

    A failing call is *data*, not an exception: a reference implementation
    raising on an input is a legitimate outcome that Break-the-Tests compares.
    Only a failure of the sandbox itself raises `SandboxError`.
    """
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SandboxError("source exceeds the sandbox size limit")

    payload = json.dumps(
        {
            "source": source,
            "entry_point": entry_point,
            "calls": calls or [],
            "read_names": read_names or [],
        }
    )

    workdir = tempfile.mkdtemp(prefix="bp-sandbox-")
    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-I", "-S", "-B", str(_CHILD)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            cwd=workdir,
            env=_child_env(),
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(
            f"execution exceeded the {timeout:g}s limit and was terminated"
        ) from exc
    except OSError as exc:
        raise SandboxError(f"sandbox could not start: {exc}") from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    duration_ms = int((time.perf_counter() - started) * 1000)

    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise SandboxError("sandbox produced more output than the limit allows")

    if not completed.stdout.strip():
        detail = completed.stderr.strip().splitlines()[-1:] or ["no output"]
        raise SandboxError(
            f"sandbox exited with code {completed.returncode}: {detail[0]}"
        )

    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SandboxError("sandbox returned a malformed result") from exc

    return SandboxResult(
        ok=bool(raw.get("ok")),
        calls=[
            CallOutcome(
                ok=bool(c.get("ok")),
                value=c.get("value"),
                error=str(c.get("error", "")),
            )
            for c in raw.get("calls", [])
        ],
        names=raw.get("names", {}) or {},
        error=str(raw.get("error", "")),
        violation=bool(raw.get("violation")),
        stdout=str(raw.get("stdout", "")),
        duration_ms=duration_ms,
    )


# --- Student-supplied test arguments ---------------------------------------
#
# Student input is parsed, never executed. `ast.literal_eval` accepts only
# literal containers and constants, so `__import__("os").system(...)` is a
# SyntaxError-equivalent rather than a payload. This is the single most
# important line of defence in Mode F, and it is why Mode F does not need the
# sandbox to be a security boundary.

MAX_ARG_SOURCE = 500


class TestInputError(ValueError):
    """The student's test input is not an admissible literal."""


def parse_test_args(raw: str, *, arity: int) -> list[Any]:
    """Parse a student's test input into an argument list.

    Accepts `3`, `3, 4`, `(3, 4)`, `[1, 2], 3`, `"abc"`. Rejects names,
    operators, calls, comprehensions - anything that is not a literal.
    """
    text = raw.strip().rstrip(",")
    if not text:
        raise TestInputError("Enter the input your test should use.")
    if len(text) > MAX_ARG_SOURCE:
        raise TestInputError("That input is longer than a test case needs to be.")

    try:
        node = ast.parse(text, mode="eval").body
    except SyntaxError as exc:
        raise TestInputError(f"That is not a valid literal value ({exc.msg}).") from exc

    # A bare `3, 4` parses as a tuple, which we read as two arguments. A single
    # argument that is genuinely a tuple has to be written `(3, 4),` or passed
    # for arity 1, where we keep it whole.
    if isinstance(node, ast.Tuple) and arity > 1:
        elements = node.elts
    else:
        elements = [node]

    try:
        args = [ast.literal_eval(el) for el in elements]
    except (ValueError, SyntaxError, TypeError) as exc:
        raise TestInputError(
            "Test inputs must be plain literal values - numbers, strings, "
            "lists, tuples, dicts, True/False/None. No function calls, "
            "variables or expressions."
        ) from exc

    if len(args) != arity:
        raise TestInputError(
            f"This function takes {arity} argument(s); you supplied {len(args)}."
        )
    return args


def canonical_args(args: list[Any]) -> str:
    """A stable string form of an argument list, for duplicate detection."""
    return repr(tuple(args))
