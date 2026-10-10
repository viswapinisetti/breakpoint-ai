"""Tests for the Python code-tools harness, under plain CPython.

Pyodide is CPython, so behaviour here is behaviour in the browser.

    python src/lib/code/harness_test.py
"""

import json
import pathlib
import sys

sys.dont_write_bytecode = True  # no __pycache__ inside src/
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import harness as h  # noqa: E402

failures = 0


def check(label, condition, detail=""):
    global failures
    print(f"  {'ok  ' if condition else 'FAIL'} {label}{'' if condition else '  ' + str(detail)}")
    if not condition:
        failures += 1


FLOOR = 'def to_minutes(seconds):\n    """Whole minutes, truncating toward zero."""\n    return seconds // 60\n'
MUTABLE = "def add_item(item, basket=[]):\n    basket.append(item)\n    return basket\n"

print("run")
r = json.loads(h.bp_run(FLOOR))
check("a definition-only program runs cleanly", r["ok"] and r["stdout"] == "", r)
check("and reports what it defined", r["defined"] == ["to_minutes"], r["defined"])
r = json.loads(h.bp_run("print('hi')\nprint(1/0)"))
check("output before an error is kept", r["stdout"] == "hi\n", r["stdout"])
check("the error is ZeroDivisionError", r["error"]["type"] == "ZeroDivisionError", r["error"])
check("the traceback quotes the student's line", "print(1/0)" in r["error"]["traceback"], r["error"]["traceback"])
check("and not the harness", "harness" not in r["error"]["traceback"], r["error"]["traceback"])
r = json.loads(h.bp_run("x = input('age? ')"))
check("input() explains itself", "not available in the sandbox" in r["error"]["message"], r["error"])

print("\nterminal")
r = json.loads(h.bp_repl(FLOOR, "to_minutes(-5)"))
check("to_minutes(-5) is -1 in Python (floor, not truncation)", r["value"] == "-1", r)
json.loads(h.bp_repl(FLOOR, "x = 125"))
r = json.loads(h.bp_repl(FLOOR, "to_minutes(x)"))
check("terminal state persists between entries", r["value"] == "2", r)
r = json.loads(h.bp_repl(FLOOR, "y = 3\ny * 2"))
check("a multi-line entry shows its last expression", r["value"] == "6", r)
r = json.loads(h.bp_repl(FLOOR, "print('p')"))
check("print output is captured, None not echoed", r["stdout"] == "p\n" and r["value"] is None, r)
r = json.loads(h.bp_repl(FLOOR + "\n", "x"))
check("changed code reloads a fresh namespace", r["error"]["type"] == "NameError", r)
r = json.loads(h.bp_repl("def broken(:\n", "1"))
check("a program that fails to load is reported", r["loadFailed"] and r["error"]["type"] == "SyntaxError", r)

print("\ntest runner")
r = json.loads(h.bp_tests(FLOOR, json.dumps([
    {"call": "to_minutes(125)", "expected": "2"},
    {"call": "to_minutes(-5)", "expected": "0"},
    {"call": "to_minutes('a')", "expected": "raises TypeError"},
    {"call": "to_minutes(1)", "expected": "raises ValueError"},
])))
res = r["results"]
check("125 -> 2 passes", res[0]["passed"] and res[0]["actual"] == "2", res[0])
check("-5 -> 0 fails with actual -1", not res[1]["passed"] and res[1]["actual"] == "-1", res[1])
check("an expected exception passes", res[2]["passed"], res[2])
check("a missing exception fails", not res[3]["passed"], res[3])
r = json.loads(h.bp_tests(MUTABLE, json.dumps([
    {"call": "add_item('a')", "expected": "['a']"},
    {"call": "add_item('b')", "expected": "['b']"},
])))
check("cases share one module, so the mutable default shows up",
      r["results"][0]["passed"] and not r["results"][1]["passed"]
      and r["results"][1]["actual"] == "['a', 'b']", r["results"])
r = json.loads(h.bp_tests(MUTABLE, json.dumps([{"call": "add_item('a')", "expected": "['a']"}])))
check("each run starts from a fresh module", r["results"][0]["passed"], r)

print("\ndebugger")
LOOP = "def total(xs):\n    s = 0\n    for x in xs:\n        s += x\n    return s\n"
r = json.loads(h.bp_trace(LOOP, "total([2, 3])"))
events = [(s["event"], s["line"]) for s in r["steps"]]
check("call, each line, and return are traced",
      events == [("call", 1), ("line", 2), ("line", 3), ("line", 4), ("line", 3),
                 ("line", 4), ("line", 3), ("line", 5), ("return", 5)], events)
check("locals are captured per step", r["steps"][5]["locals"] == {"xs": "[2, 3]", "s": "2", "x": "3"},
      r["steps"][5])
check("the return value is recorded", r["steps"][-1]["value"] == "5" and r["value"] == "5", r["steps"][-1])
check("steps carry their source line", r["steps"][3]["source"] == "s += x", r["steps"][3])
r = json.loads(h.bp_trace(MUTABLE, "add_item('a')\nadd_item('b')"))
returns = [s["value"] for s in r["steps"] if s["event"] == "return"]
check("tracing two calls shows the shared list growing", returns == ["['a']", "['a', 'b']"], returns)
r = json.loads(h.bp_trace("def f(n):\n    while True:\n        n += 1\n", "1"))
check("tracing code that never calls the program records nothing", r["steps"] == [], r)
r = json.loads(h.bp_trace("def f():\n    i = 0\n    while i < 10**6:\n        i += 1\n    return i\n", "f()"))
check("long loops stop recording at the step limit", r["truncated"] and len(r["steps"]) == h.MAX_STEPS, len(r["steps"]))
check("but the call still completes", r["value"] == "1000000", r["value"])
r = json.loads(h.bp_trace(FLOOR, "to_minutes(None)"))
check("an exception inside the code is traced and reported",
      any(s["event"] == "exception" for s in r["steps"]) and r["error"]["type"] == "TypeError", r)

print(f"\n{failures} FAILURES" if failures else "\nall harness cases pass")
sys.exit(1 if failures else 0)
