"""Universal failure taxonomy (PRD section 51).

These sixteen categories are subject-independent. Each subject adapter maps them
onto domain-specific variants via `SubjectAdapter.failure_taxonomy`; the engine
itself never learns what a "wrong join" or a "stale state" is.
"""

from __future__ import annotations

from enum import StrEnum


class FailureCategory(StrEnum):
    CALCULATION = "F01"
    LOGICAL = "F02"
    HIDDEN_ASSUMPTION = "F03"
    MISSING_EDGE_CASE = "F04"
    MISINTERPRETATION = "F05"
    INCOMPLETE_REASONING = "F06"
    RULE_MISAPPLICATION = "F07"
    WRONG_DEPENDENCY = "F08"
    UNSUPPORTED_CONCLUSION = "F09"
    PERFORMANCE = "F10"
    SECURITY = "F11"
    DATA = "F12"
    EVALUATION = "F13"
    HALLUCINATION = "F14"
    AMBIGUOUS_SOLUTION = "F15"
    WRONG_APPROACH = "F16"


LABELS: dict[FailureCategory, str] = {
    FailureCategory.CALCULATION: "Calculation Failure",
    FailureCategory.LOGICAL: "Logical Failure",
    FailureCategory.HIDDEN_ASSUMPTION: "Hidden Assumption",
    FailureCategory.MISSING_EDGE_CASE: "Missing Edge Case",
    FailureCategory.MISINTERPRETATION: "Misinterpretation",
    FailureCategory.INCOMPLETE_REASONING: "Incomplete Reasoning",
    FailureCategory.RULE_MISAPPLICATION: "Rule Misapplication",
    FailureCategory.WRONG_DEPENDENCY: "Wrong Dependency",
    FailureCategory.UNSUPPORTED_CONCLUSION: "Unsupported Conclusion",
    FailureCategory.PERFORMANCE: "Performance Failure",
    FailureCategory.SECURITY: "Security Failure",
    FailureCategory.DATA: "Data Failure",
    FailureCategory.EVALUATION: "Evaluation Failure",
    FailureCategory.HALLUCINATION: "Hallucination",
    FailureCategory.AMBIGUOUS_SOLUTION: "Ambiguous Solution",
    FailureCategory.WRONG_APPROACH: "Wrong Tool / Approach",
}


def label(category: str) -> str:
    """Human label for a category code, falling back to the raw code."""
    try:
        return LABELS[FailureCategory(category)]
    except ValueError:
        return category
