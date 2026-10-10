"""The sandbox child process. Never imported - only run as a script.

Runs untrusted-ish code (challenge solvers, reference implementations) in a
fresh interpreter started with `-I -S`, so it inherits no site packages, no
PYTHONPATH and no user site directory. Everything below runs *before* the
payload and cannot be undone by it, because by the time the payload executes
the dangerous machinery is already gone.

Protocol: one JSON object on stdin, one JSON object on stdout. Nothing else is
written to stdout - diagnostics go to stderr - so the parent can parse the
result even when the payload prints.
"""

from __future__ import annotations

import builtins
import io
import json
import sys

# Modules the payload may import. Everything here is pure computation: no
# filesystem, no network, no process control, no reflection into the host.
ALLOWED_MODULES = frozenset(
    {
        "math",
        "cmath",
        "fractions",
        "decimal",
        "statistics",
        "itertools",
        "functools",
        "operator",
        "collections",
        "collections.abc",
        "heapq",
        "bisect",
        "array",
        "string",
        "re",
        "textwrap",
        "unicodedata",
        "datetime",
        "calendar",
        "copy",
        "json",
        "enum",
        "dataclasses",
        "typing",
        "numbers",
        "abc",
        "types",
    }
)

# Builtins the payload may call. Absent by design: open, input, exec, eval,
# compile, __import__ (replaced below), globals, locals, vars, dir, getattr,
# setattr, delattr, breakpoint, help, memoryview, exit, quit.
ALLOWED_BUILTINS = (
    "abs all any ascii bin bool bytearray bytes callable chr complex dict divmod "
    "enumerate filter float format frozenset hash hex int isinstance issubclass "
    "iter len list map max min next object oct ord pow print range repr reversed "
    "round set slice sorted str sum tuple type zip "
    # Class machinery: `class` statements compile to __build_class__, and
    # super/property/staticmethod/classmethod are ordinary language features.
    # None of them reach the filesystem, network or host process.
    "__build_class__ super property staticmethod classmethod "
    "True False None NotImplemented Ellipsis "
    "ArithmeticError AssertionError AttributeError BaseException Exception "
    "EOFError FloatingPointError IndexError KeyError KeyboardInterrupt LookupError "
    "MemoryError NameError NotImplementedError OverflowError RecursionError "
    "RuntimeError StopIteration TypeError UnboundLocalError ValueError "
    "ZeroDivisionError"
).split()


class SandboxViolation(Exception):
    """The payload tried to reach outside the sandbox."""


def _blocked(name: str):
    def _raise(*_args, **_kwargs):
        raise SandboxViolation(f"{name} is not available inside the sandbox")

    return _raise


def _harden() -> dict:
    """Strip the interpreter down before the payload can look at it.

    Returns the restricted builtins mapping the payload will run against.
    """
    # 0. Pre-import the allowlist while imports are still unrestricted, so
    #    their private C/py dependencies (`datetime` -> `_datetime`, `re` ->
    #    `enum`/`sre_*`) are already resolved. Without this the guard would
    #    reject a legitimate `import datetime` for a transitive dependency the
    #    payload never asked for.
    for _mod in sorted(ALLOWED_MODULES):
        try:
            real_import_bootstrap = builtins.__import__
            real_import_bootstrap(_mod)
        except Exception:  # noqa: BLE001 - an unavailable stdlib module is fine
            pass

    # 1. Drop every module already imported that could be used to escape, and
    #    poison sys.modules so a re-import cannot bring them back.
    for name in ("os", "posix", "nt", "subprocess", "socket", "shutil", "ctypes",
                 "signal", "threading", "multiprocessing", "importlib",
                 "pathlib", "tempfile", "http", "urllib", "ssl", "pickle",
                 "marshal", "webbrowser", "platform", "pty", "fcntl", "mmap"):
        sys.modules[name] = None  # type: ignore[assignment]

    # 2. Replace the import machinery with an allowlist. Setting a module to
    #    None in sys.modules already makes `import` raise, but an explicit
    #    check gives a clear error and also covers modules never imported.
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if name not in ALLOWED_MODULES and root not in ALLOWED_MODULES:
            raise SandboxViolation(f"importing {name!r} is not allowed in the sandbox")
        return real_import(name, globals, locals, fromlist, level)

    # 3. Build the restricted builtins mapping the payload will see.
    safe = {n: getattr(builtins, n) for n in ALLOWED_BUILTINS if hasattr(builtins, n)}
    safe["__import__"] = guarded_import
    for gone in ("open", "input", "exec", "eval", "compile", "breakpoint", "help",
                 "exit", "quit", "globals", "locals", "vars", "dir"):
        safe[gone] = _blocked(gone)

    # 4. Recursion and output caps. A runaway recursion would otherwise take
    #    down the child with a native stack overflow rather than an exception
    #    we can report, and unbounded printing would fill the parent's pipe.
    sys.setrecursionlimit(2000)

    # 5. Address-space cap where the platform has one. Windows has no
    #    setrlimit; the parent's wall-clock timeout is the backstop there, and
    #    that limitation is documented in sandbox.py rather than hidden.
    try:
        import resource  # noqa: PLC0415 - POSIX only, absent on Windows

        soft_cap = 256 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (soft_cap, soft_cap))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    except Exception:  # noqa: BLE001 - best effort, never fatal
        pass

    return safe


class _CappedWriter(io.TextIOBase):
    """Absorbs payload prints up to a cap, then silently discards."""

    def __init__(self, cap: int = 16_384) -> None:
        self.cap = cap
        self.parts: list[str] = []
        self.size = 0

    def write(self, text: str) -> int:  # type: ignore[override]
        if self.size < self.cap:
            self.parts.append(text[: self.cap - self.size])
            self.size += len(text)
        return len(text)

    def value(self) -> str:
        return "".join(self.parts)


def _jsonable(value):
    """Coerce a result to something JSON can carry, losslessly where possible."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else repr(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    # Exact numeric types cross the JSON boundary as their own text form:
    # Fraction(175, 12) has to arrive as "175/12", because callers compare
    # answers as strings and `repr` would hand them a constructor call.
    import numbers  # noqa: PLC0415 - allowlisted, pre-imported

    if isinstance(value, numbers.Number):
        return str(value)
    return repr(value)


def main() -> int:
    request = json.loads(sys.stdin.read())
    safe_builtins = _harden()

    scope = {"__builtins__": safe_builtins, "__name__": "__sandbox__"}
    captured = _CappedWriter()
    real_stdout = sys.stdout
    sys.stdout = captured  # type: ignore[assignment]

    result: dict = {"ok": False, "calls": [], "stdout": ""}
    try:
        # A single namespace, so functions, lambdas and comprehensions in the
        # payload can see each other. Splitting globals from locals here is a
        # classic and very confusing source of NameError.
        exec(compile(request["source"], "<sandbox>", "exec"), scope)  # noqa: S102

        entry = request.get("entry_point")
        calls = request.get("calls") or []
        if entry:
            fn = scope.get(entry)
            if not callable(fn):
                raise SandboxViolation(f"{entry!r} is not defined by the payload")
            for args in calls:
                try:
                    result["calls"].append(
                        {"ok": True, "value": _jsonable(fn(*args))}
                    )
                except SandboxViolation:
                    raise
                except BaseException as exc:  # noqa: BLE001 - report, don't crash
                    result["calls"].append(
                        {
                            "ok": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
        else:
            # No entry point: the payload is expected to define names the
            # parent will read back (the Aptitude solver style).
            wanted = request.get("read_names") or []
            result["names"] = {
                n: _jsonable(scope[n]) for n in wanted if n in scope
            }
        result["ok"] = True
    except SandboxViolation as exc:
        result["error"] = str(exc)
        result["violation"] = True
    except BaseException as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        sys.stdout = real_stdout
        result["stdout"] = captured.value()

    json.dump(result, sys.stdout)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
