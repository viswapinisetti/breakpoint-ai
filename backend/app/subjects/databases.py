"""Databases adapter - Tier A deterministic validator.

The same principle as the Aptitude solver check and the Programming executor:
correctness is *computed*, not asserted. A SQL challenge carries its tables as
data and the AI's query as the artifact, so the engine can seed a real database
and run both the AI's query and a reference query:

* a flawed challenge must produce a different result from the reference -
  otherwise there is no detectable failure, whatever the prose claims;
* a valid challenge must produce the same result;
* either way the AI's query has to *run* against the declared schema, which
  catches a query referencing a column or table the student can never see.

Three deliberate limits:

**insufficient_information challenges are skipped entirely.** Those challenges
work precisely because the data needed to decide them is withheld - see
`db-joins-aggregations-subqueries-004`, where the question is whether 900 is
one customer's total and the answer is that you cannot tell, because
`GROUP BY c.name` collapses two customers sharing a name. Seeding rows to make
it executable would resolve the ambiguity and destroy the challenge.

**This is SQLite, not PostgreSQL.** The browser-side tools use PGlite (real
PostgreSQL compiled to WebAssembly) but that cannot run server-side in Python.
Stdlib sqlite3 covers the ANSI core the content actually uses - joins,
aggregation, subqueries, CTEs and window functions - and a challenge written
against Postgres-only syntax simply fails to execute here and is reported,
rather than being silently passed.

**It is not a security boundary.** Content SQL is authored and reviewed, never
supplied by a student. The authorizer and step budget below exist to stop an
authoring mistake reaching the filesystem or hanging the validator, not to
contain an attacker.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.engine.contracts import Challenge, TruthState
from app.subjects.base import SubjectConfig, ValidationResult
from app.subjects.catalog import BY_KEY

# A cartesian product over a few seeded tables is tiny, so any query needing
# more than this is a runaway rather than a slow one.
STEP_BUDGET = 2_000_000

# Statements the validator refuses outright. Reading or writing a file, loading
# an extension or attaching another database is never part of a challenge.
_DENIED = {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}


class SqlError(RuntimeError):
    """A challenge's SQL could not be executed."""


def _authorizer(action: int, *_args: Any) -> int:
    return sqlite3.SQLITE_DENY if action in _DENIED else sqlite3.SQLITE_OK


def strip_sql_comments(sql: str) -> str:
    """SQL with comments and whitespace removed, for emptiness checks only.

    `db-normalization-schema-design-004` is why this exists: its artifact is a
    prose sketch of a proposed table split written entirely as `--` comments.
    SQLite runs that happily and returns nothing, so without this check the
    challenge reported as successfully executed while nothing had been tested.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        if sql.startswith("--", i):
            i = sql.find("\n", i)
            if i == -1:
                break
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(sql[i])
            i += 1
    return "".join(out).strip().strip(";").strip()


def seed_tables(artifact: dict) -> dict[str, dict]:
    """Table specs inside an artifact: {name: {columns, rows}}.

    A key is a table when it carries both `columns` and `rows`. `result` is
    excluded by name: it is the output a challenge displays, not an input, and
    seeding it would let a query "find" the answer it is supposed to compute.
    """
    return {
        name: spec
        for name, spec in artifact.items()
        if name != "result"
        and isinstance(spec, dict)
        and isinstance(spec.get("columns"), list)
        and isinstance(spec.get("rows"), list)
    }


def build_database(tables: dict[str, dict]) -> sqlite3.Connection:
    """An in-memory database holding the challenge's tables.

    Writes are allowed deliberately. Some challenges *are* a write - the
    update-anomaly ones turn on an UPDATE touching only part of a denormalised
    table - so the database is per-challenge, in memory and discarded, rather
    than read-only.
    """
    conn = sqlite3.connect(":memory:")
    try:
        for name, spec in tables.items():
            columns = ", ".join(f'"{c}"' for c in spec["columns"])
            conn.execute(f'CREATE TABLE "{name}" ({columns})')
            marks = ", ".join("?" * len(spec["columns"]))
            conn.executemany(f'INSERT INTO "{name}" VALUES ({marks})', spec["rows"])
        conn.commit()
    except sqlite3.Error as exc:
        conn.close()
        raise SqlError(f"could not build the schema: {exc}") from exc

    conn.set_authorizer(_authorizer)
    steps = {"n": 0}

    def _guard() -> int:
        steps["n"] += 1
        return 1 if steps["n"] > STEP_BUDGET // 1000 else 0

    conn.set_progress_handler(_guard, 1000)
    return conn


def run_query(conn: sqlite3.Connection, sql: str) -> list[tuple]:
    """Run a challenge's SQL, which may be one statement or several.

    A statement that returns rows returns them; a write returns an empty list,
    and its effect is observed in the table state instead.
    """
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.Warning:
        # sqlite3 refuses multiple statements through execute(). Scripts cannot
        # return rows, which is fine: a multi-statement artifact is a sequence
        # of writes, judged on the state it leaves behind.
        try:
            conn.executescript(sql)
            return []
        except sqlite3.Error as exc:
            raise SqlError(f"{type(exc).__name__}: {exc}") from exc
    except sqlite3.Error as exc:
        raise SqlError(f"{type(exc).__name__}: {exc}") from exc


def table_state(conn: sqlite3.Connection, tables: dict[str, dict]) -> dict[str, list]:
    """Every seeded table's contents, so a write can be compared by effect."""
    state: dict[str, list] = {}
    for name in sorted(tables):
        try:
            rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
        except sqlite3.Error as exc:
            raise SqlError(f"could not read back {name}: {exc}") from exc
        state[name] = sorted((tuple(_cell(c) for c in row) for row in rows), key=repr)
    return state


def _normalise(rows: list[tuple], ordered: bool) -> list:
    """Comparable form for a result set.

    Unordered by default: without ORDER BY, SQL makes no promise about row
    order, so comparing raw lists would report a disagreement that is not one.
    A challenge whose point *is* the ordering sets `sql_compare: "ordered"`.
    """
    shaped = [tuple(_cell(c) for c in row) for row in rows]
    return shaped if ordered else sorted(shaped, key=repr)


def _cell(value: Any) -> Any:
    """Integers and floats that are equal compare equal (1 vs 1.0)."""
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


class SqlAdapter:
    """Executes challenge SQL to prove the claimed behaviour."""

    def __init__(self, config: SubjectConfig | None = None) -> None:
        self.config = config or BY_KEY["databases"]

    def validate(self, challenge: Challenge) -> list[ValidationResult]:
        artifact = challenge.artifact if isinstance(challenge.artifact, dict) else {}
        payload = challenge.validation_payload or {}
        reference = payload.get("reference_query")
        query = artifact.get("query")
        tables = seed_tables(artifact) if artifact else {}

        if challenge.truth_state is TruthState.INSUFFICIENT_INFORMATION:
            return [
                ValidationResult(
                    True,
                    "insufficient_information",
                    "Underdetermined by design; executing it would supply the "
                    "data the challenge deliberately withholds.",
                )
            ]

        if not (query and tables and strip_sql_comments(query)):
            return [
                ValidationResult(
                    True,
                    "no_executable_validation",
                    "Challenge carries no runnable SQL (needs artifact.query "
                    "with at least one real statement, and at least one seeded "
                    "table); relying on critic and human review.",
                )
            ]

        # Two identically seeded databases, so a write made by one side cannot
        # be seen by the other.
        try:
            ai_conn = build_database(tables)
        except SqlError as exc:
            return [ValidationResult(False, "sql_execution", str(exc))]

        try:
            try:
                ai_rows = run_query(ai_conn, query)
                ai_state = table_state(ai_conn, tables)
            except SqlError as exc:
                return [
                    ValidationResult(
                        False,
                        "sql_execution",
                        f"The AI's SQL does not run against its own declared "
                        f"schema ({', '.join(sorted(tables))}): {exc}",
                    )
                ]

            results = [
                ValidationResult(
                    True,
                    "sql_execution",
                    f"The AI's SQL ran against {len(tables)} seeded table(s) "
                    f"and returned {len(ai_rows)} row(s).",
                )
            ]

            if not reference:
                results.append(
                    ValidationResult(
                        True,
                        "no_reference_query",
                        "No validation_payload.reference_query, so the SQL "
                        "could be executed but its result not judged. Add one "
                        "to make this challenge machine-verified.",
                    )
                )
                return results

            ref_conn = build_database(tables)
            try:
                ref_rows = run_query(ref_conn, reference)
                ref_state = table_state(ref_conn, tables)
            except SqlError as exc:
                return [
                    *results,
                    ValidationResult(
                        False, "reference_query", f"The reference SQL failed: {exc}"
                    ),
                ]
            finally:
                ref_conn.close()

            ordered = payload.get("sql_compare") == "ordered"
            rows_differ = _normalise(ai_rows, ordered) != _normalise(ref_rows, ordered)
            state_differs = ai_state != ref_state
            results.append(
                self._verdict(
                    challenge, rows_differ or state_differs, ai_rows, ref_rows, state_differs
                )
            )
            return results
        finally:
            ai_conn.close()

    @staticmethod
    def _verdict(
        challenge: Challenge,
        differ: bool,
        ai_rows: list[tuple],
        ref_rows: list[tuple],
        state_differs: bool,
    ) -> ValidationResult:
        """A flawed query must diverge from the reference; a valid one must not."""
        summary = (
            f"AI SQL returned {len(ai_rows)} row(s), reference {len(ref_rows)}"
            + ("; the resulting table state differs too" if state_differs else "")
        )
        if challenge.contains_failure:
            if differ:
                return ValidationResult(
                    True,
                    "failure_is_reproducible",
                    f"{summary}; the results differ, so the failure is real.",
                )
            return ValidationResult(
                False,
                "failure_is_reproducible",
                f"{summary}, and the results are identical, so the claimed "
                "failure is not detectable from the data. Change the seed rows "
                "so the two diverge, or the challenge is unfair.",
            )
        if differ:
            return ValidationResult(
                False,
                "correct_artifact",
                f"Challenge is marked {challenge.truth_state.value}, but "
                f"{summary} and the results differ.",
            )
        return ValidationResult(
            True,
            "correct_artifact",
            f"{summary}; the AI's query matches the reference.",
        )
