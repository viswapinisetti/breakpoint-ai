"""Breakpoint code tools for one investigation's Python code.

Loaded into Pyodide (real CPython compiled to WebAssembly) by pyWorker.ts, so
the Editor, Terminal, Test Runner and Debugger behave exactly as Python does.
Every entry point takes and returns JSON text, so the worker never has to
translate Python objects.

    bp_run(code)          run the program; it becomes the Terminal's namespace
    bp_repl(code, src)    evaluate Terminal input against that namespace
    bp_tests(code, cases) evaluate call/expected pairs in one fresh module
    bp_trace(code, src)   run src with a line-by-line trace of the code

Also runnable under plain CPython, which is how harness_test.py checks it.
"""

import ast
import builtins
import io
import json
import linecache
import reprlib
import sys
import time
import traceback

PROGRAM = "<investigation>"
TERMINAL = "<terminal>"
TEST = "<test>"
TRACE = "<trace>"
USER_FILES = {PROGRAM, TERMINAL, TEST, TRACE}

MAX_OUTPUT = 20_000
MAX_STEPS = 400

_short = reprlib.Repr()
_short.maxstring = 60
_short.maxother = 60
_short.maxlist = 10
_short.maxtuple = 10
_short.maxdict = 10
_short.maxset = 10
_short.maxlevel = 3

_state = {"code": None, "ns": None}


def _no_input(*_args):
    raise RuntimeError(
        "input() is not available in the sandbox; pass values as arguments instead."
    )


class _Capped(io.StringIO):
    """Collects printed output, keeping at most MAX_OUTPUT characters."""

    truncated = False

    def write(self, s):
        room = MAX_OUTPUT - self.tell()
        if room <= 0:
            self.truncated = True
            return len(s)
        if len(s) > room:
            self.truncated = True
        return super().write(s[:room])


class _Capture:
    def __enter__(self):
        self.out, self.err = _Capped(), _Capped()
        self._saved = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = self.out, self.err
        return self

    def __exit__(self, *exc):
        sys.stdout, sys.stderr = self._saved
        return False

    def text(self):
        out = self.out.getvalue()
        if self.out.truncated:
            out += "\n... output truncated ..."
        return out, self.err.getvalue()


def _register(filename, source):
    """Let tracebacks quote lines from our pseudo-files."""
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)


def _format_error(exc):
    """A traceback showing only the student's code, not this harness."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_frame.f_code.co_filename not in USER_FILES:
        tb = tb.tb_next
    lines = traceback.format_exception(type(exc), exc, tb)
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(lines).rstrip(),
    }


def _fresh_namespace():
    return {"__name__": "__main__", "__builtins__": builtins, "input": _no_input}


def _defined(ns):
    return sorted(
        name
        for name, value in ns.items()
        if not name.startswith("_")
        and name != "input"
        and callable(value)
        and getattr(value, "__module__", None) == "__main__"
    )


def _load(code):
    """Run the program in a fresh namespace. Returns (ns, stdout, stderr, error)."""
    _register(PROGRAM, code)
    ns = _fresh_namespace()
    error = None
    with _Capture() as cap:
        try:
            exec(compile(code, PROGRAM, "exec"), ns)
        except BaseException as exc:  # noqa: BLE001 - the student's program may raise anything
            error = _format_error(exc)
    out, err = cap.text()
    return ns, out, err, error


def _current(code):
    """The Terminal's namespace for this code, loading it if the code changed."""
    if _state["code"] != code or _state["ns"] is None:
        ns, _out, _err, error = _load(code)
        _state.update(code=code, ns=ns)
        return ns, error
    return _state["ns"], None


def _exec_with_value(source, filename, ns):
    """exec `source`; if its last statement is an expression, return its value."""
    _register(filename, source)
    tree = ast.parse(source, filename, "exec")
    last = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last = ast.Expression(tree.body.pop().value)
    if tree.body:
        exec(compile(tree, filename, "exec"), ns)
    if last is not None:
        return True, eval(compile(last, filename, "eval"), ns)
    return False, None


def _ms(started):
    return round((time.perf_counter() - started) * 1000)


# --- entry points ------------------------------------------------------------


def bp_run(code):
    started = time.perf_counter()
    ns, out, err, error = _load(code)
    _state.update(code=code, ns=ns)
    return json.dumps(
        {
            "ok": error is None,
            "stdout": out,
            "stderr": err,
            "error": error,
            "defined": _defined(ns),
            "ms": _ms(started),
        }
    )


def bp_reset():
    _state.update(code=None, ns=None)
    return json.dumps({"ok": True})


def bp_repl(code, source):
    started = time.perf_counter()
    ns, load_error = _current(code)
    if load_error is not None:
        return json.dumps(
            {"ok": False, "stdout": "", "stderr": "", "value": None,
             "error": load_error, "loadFailed": True, "ms": _ms(started)}
        )
    value_repr = None
    error = None
    with _Capture() as cap:
        try:
            has_value, value = _exec_with_value(source, TERMINAL, ns)
            if has_value and value is not None:
                value_repr = repr(value)
                ns["_"] = value
        except BaseException as exc:  # noqa: BLE001
            error = _format_error(exc)
    out, err = cap.text()
    return json.dumps(
        {"ok": error is None, "stdout": out, "stderr": err, "value": value_repr,
         "error": error, "ms": _ms(started)}
    )


def bp_tests(code, cases_json):
    """Each case is {"call": expr, "expected": expr or "raises Name"}.

    All cases run in order in one freshly loaded module, as a test file would:
    state the code keeps between calls (a mutable default argument, a cache)
    carries from one case to the next, which is often the point.
    """
    cases = json.loads(cases_json)
    ns, _out, _err, load_error = _load(code)
    if load_error is not None:
        return json.dumps({"loadError": load_error, "results": []})
    results = []
    for case in cases:
        call = (case.get("call") or "").strip()
        expected_src = (case.get("expected") or "").strip()
        result = {"call": call, "expected": expected_src, "passed": False,
                  "actual": None, "error": None, "stdout": ""}
        if not call:
            continue
        raises = expected_src.startswith("raises ")
        with _Capture() as cap:
            try:
                _register(TEST, call)
                actual = eval(compile(call, TEST, "eval"), ns)
                result["actual"] = repr(actual)
                if raises:
                    result["error"] = {"type": "", "message": "no exception was raised",
                                       "traceback": ""}
                elif expected_src:
                    expected = eval(compile(expected_src, TEST, "eval"), ns)
                    result["expectedValue"] = repr(expected)
                    result["passed"] = bool(actual == expected)
            except BaseException as exc:  # noqa: BLE001
                error = _format_error(exc)
                result["error"] = error
                if raises:
                    wanted = expected_src[len("raises "):].strip()
                    result["passed"] = type(exc).__name__ == wanted
        result["stdout"] = cap.text()[0]
        results.append(result)
    return json.dumps({"loadError": None, "results": results})


def bp_trace(code, source):
    """Run `source` against a fresh load of the code, recording every line the
    investigation's own code executes, with its local variables."""
    ns, _out, _err, load_error = _load(code)
    if load_error is not None:
        return json.dumps({"loadError": load_error, "steps": []})
    lines = code.splitlines()
    steps = []
    truncated = False

    def snapshot(frame):
        return {
            name: _short.repr(value)
            for name, value in frame.f_locals.items()
            if not name.startswith("__")
        }

    def local(frame, event, arg):
        nonlocal truncated
        if len(steps) >= MAX_STEPS:
            truncated = True
            sys.settrace(None)
            return None
        line = frame.f_lineno
        step = {
            "event": event,
            "func": frame.f_code.co_name,
            "line": line,
            "source": lines[line - 1].strip() if 0 < line <= len(lines) else "",
            "locals": snapshot(frame),
            "depth": depth(frame),
        }
        if event == "return":
            step["value"] = _short.repr(arg)
        elif event == "exception":
            step["value"] = f"{arg[0].__name__}: {arg[1]}"
        steps.append(step)
        return local

    def depth(frame):
        n = 0
        f = frame.f_back
        while f is not None:
            if f.f_code.co_filename == PROGRAM:
                n += 1
            f = f.f_back
        return n

    def dispatch(frame, event, arg):
        if frame.f_code.co_filename != PROGRAM:
            return None
        return local(frame, event, arg)

    value_repr = None
    error = None
    with _Capture() as cap:
        try:
            sys.settrace(dispatch)
            try:
                has_value, value = _exec_with_value(source, TRACE, ns)
            finally:
                sys.settrace(None)
            if has_value:
                value_repr = repr(value)
        except BaseException as exc:  # noqa: BLE001
            error = _format_error(exc)
    out, _err = cap.text()
    return json.dumps(
        {"loadError": None, "steps": steps, "truncated": truncated,
         "value": value_repr, "error": error, "stdout": out}
    )
