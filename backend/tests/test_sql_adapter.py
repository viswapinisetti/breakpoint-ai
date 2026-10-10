"""Unit tests for the Databases SQL validator.

The shipped content exercises the happy paths. What matters here are the cases
that must *fail*: a flawed challenge whose query does not actually differ from
the reference is unfair, and a valid one whose query does differ is mislabelled.
A validator that only ever passes is not a validator.
"""

from __future__ import annotations

import pytest

from app.engine.contracts import Challenge
from app.subjects.databases import SqlAdapter, strip_sql_comments

EMPLOYEES = {
    "columns": ["name", "dept", "salary"],
    "rows": [["Asha", "eng", 90], ["Ben", "eng", 80], ["Chen", "ops", 70]],
}


def build(
    *,
    truth: str = "flawed",
    query: str = "SELECT name FROM employees;",
    reference: str | None = None,
    tables: dict | None = None,
) -> Challenge:
    artifact = {"employees": dict(EMPLOYEES)} if tables is None else tables
    artifact["query"] = query
    payload = {"reference_query": reference} if reference else {}
    return Challenge.model_validate(
        {
            "id": "db-test-001",
            "subject": "databases",
            "topic": "SQL Fundamentals",
            "difficulty": "2",
            "challenge_mode": "trust_or_challenge",
            "question": "test",
            "artifact_type": "sql",
            "artifact": artifact,
            "ai_claim": "test claim",
            "ai_solution": [{"index": 1, "text": "test step"}],
            "ai_final_answer": "yes",
            "canonical_solution": "test",
            "canonical_answer": "test",
            "truth_state": truth,
            "validation_payload": payload,
        }
    )


def names(challenge: Challenge) -> dict[str, bool]:
    return {r.validator: r.passed for r in SqlAdapter().validate(challenge)}


# --- the checks that must fail -------------------------------------------


def test_flawed_challenge_whose_query_matches_the_reference_is_rejected() -> None:
    """The §75 principle: a claimed failure no data exposes is unfair."""
    result = names(
        build(
            truth="flawed",
            query="SELECT name FROM employees WHERE dept = 'eng';",
            reference="SELECT name FROM employees WHERE dept = 'eng';",
        )
    )
    assert result["failure_is_reproducible"] is False


def test_valid_challenge_whose_query_differs_is_rejected() -> None:
    result = names(
        build(
            truth="valid",
            query="SELECT name FROM employees;",
            reference="SELECT name FROM employees WHERE dept = 'eng';",
        )
    )
    assert result["correct_artifact"] is False


def test_query_that_does_not_run_against_its_own_schema_is_rejected() -> None:
    result = names(build(query="SELECT name FROM customers;"))
    assert result["sql_execution"] is False


def test_broken_reference_query_is_reported() -> None:
    result = names(build(reference="SELECT nope FROM employees;"))
    assert result["reference_query"] is False


# --- the checks that must pass -------------------------------------------


def test_flawed_challenge_with_a_real_divergence_passes() -> None:
    result = names(
        build(
            truth="flawed",
            query="SELECT name FROM employees;",
            reference="SELECT name FROM employees WHERE dept = 'eng';",
        )
    )
    assert result["failure_is_reproducible"] is True


def test_valid_challenge_matching_an_independent_reference_passes() -> None:
    result = names(
        build(
            truth="valid",
            query="SELECT name FROM employees WHERE salary >= 80;",
            reference="SELECT name FROM employees WHERE salary > 79;",
        )
    )
    assert result["correct_artifact"] is True


def test_row_order_alone_is_not_a_disagreement() -> None:
    """Without ORDER BY, SQL promises nothing about order, so differing order
    must not be reported as a divergence."""
    result = names(
        build(
            truth="valid",
            query="SELECT name FROM employees ORDER BY name ASC;",
            reference="SELECT name FROM employees ORDER BY name DESC;",
        )
    )
    assert result["correct_artifact"] is True


def test_ordered_comparison_can_be_opted_into() -> None:
    challenge = build(
        truth="flawed",
        query="SELECT name FROM employees ORDER BY name ASC;",
        reference="SELECT name FROM employees ORDER BY name DESC;",
    )
    challenge.validation_payload["sql_compare"] = "ordered"
    assert names(challenge)["failure_is_reproducible"] is True


# --- writes, skips and safety --------------------------------------------


def test_a_write_is_judged_on_the_state_it_leaves() -> None:
    """The update-anomaly pattern: both statements return no rows, so the only
    observable difference is the table contents afterwards."""
    result = names(
        build(
            truth="flawed",
            query="UPDATE employees SET dept = 'x' WHERE name = 'Asha';",
            reference="UPDATE employees SET dept = 'x' WHERE dept = 'eng';",
        )
    )
    assert result["failure_is_reproducible"] is True


def test_insufficient_information_is_skipped_by_design() -> None:
    """Executing these would supply the data they deliberately withhold."""
    result = names(build(truth="insufficient_information"))
    assert result == {"insufficient_information": True}


def test_comment_only_sql_is_not_counted_as_executed() -> None:
    result = names(build(query="-- A(emp_id, name)\n-- B(name, dept)\n"))
    assert "sql_execution" not in result
    assert result["no_executable_validation"] is True


def test_attach_is_denied() -> None:
    """Content SQL must not reach the filesystem, even by authoring mistake."""
    result = names(build(query="ATTACH DATABASE 'other.db' AS other;"))
    assert result["sql_execution"] is False


def test_a_displayed_result_table_is_not_seeded_as_input() -> None:
    """`result` is the output a challenge shows. Seeding it would let a query
    read the answer it is supposed to compute."""
    challenge = build(
        tables={
            "employees": dict(EMPLOYEES),
            "result": {"columns": ["name"], "rows": [["Asha"]]},
        },
        query="SELECT name FROM result;",
    )
    assert names(challenge)["sql_execution"] is False


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("-- only a comment", ""),
        ("/* block */", ""),
        ("-- lead\nSELECT 1;", "SELECT 1"),
        ("SELECT 1; -- trail", "SELECT 1"),
        ("", ""),
        ("  ;  ", ""),
    ],
)
def test_strip_sql_comments(sql: str, expected: str) -> None:
    assert strip_sql_comments(sql) == expected
