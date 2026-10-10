"""The 19 NxtWave subject families (PRD sections 9-27, 39, 100).

This file is pure data. It is the whole reason the MVP can ship all 19 subjects
against one engine: a subject is a row here plus, optionally, a validator.

What a subject *teaches* - its number, display name and ordered topics - lives
in the topic registry (`app/subjects/topics.py`). This file describes how a
subject *behaves*: its artifact types, failure taxonomy, evidence types and
tools. `_config` joins the two, so the curriculum has exactly one source.
"""

from __future__ import annotations

from app.engine.contracts import EvidenceType as E
from app.subjects import topics as registry
from app.subjects.base import SubjectConfig, Tool

# Tool sets reused across subjects (PRD section 39).
_APTITUDE_TOOLS = (
    Tool("scratchpad", "Scratchpad", "pencil"),
    Tool("calculator", "Calculator", "calculator"),
    Tool("highlighter", "Step Highlighter", "marker"),
    Tool("formulas", "Formula Reference", "book"),
    Tool("dataviewer", "Graph / Table Viewer", "table"),
)
_CODE_TOOLS = (
    Tool("editor", "Editor", "code"),
    Tool("terminal", "Terminal", "terminal"),
    Tool("tests", "Test Runner", "beaker"),
    Tool("debugger", "Debugger", "bug"),
)
_DB_TOOLS = (
    Tool("sql", "SQL Editor", "database"),
    Tool("schema", "Schema Viewer", "sitemap"),
    Tool("runner", "Query Executor", "play"),
)
_API_TOOLS = (
    Tool("request", "Request Builder", "send"),
    Tool("inspector", "Response Inspector", "search"),
)
_DEVOPS_TOOLS = (
    Tool("sandbox", "Terminal Sandbox", "terminal"),
    Tool("yaml", "YAML Editor", "file"),
    Tool("logs", "Logs", "list"),
)
_AI_TOOLS = (
    Tool("prompt", "Prompt Sandbox", "sparkles"),
    Tool("compare", "Model Comparison", "columns"),
    Tool("evaluator", "Response Evaluator", "check"),
)
_TEXT_TOOLS = (
    Tool("highlighter", "Passage Highlighter", "marker"),
    Tool("rules", "Grammar Reference", "book"),
    Tool("scratchpad", "Scratchpad", "pencil"),
)
_DATA_TOOLS = (
    Tool("dataviewer", "Data Viewer", "table"),
    Tool("chart", "Chart Inspector", "chart"),
    Tool("notebook", "Notebook", "code"),
)


def _config(
    key: str,
    *,
    tagline: str,
    tier: str,
    artifact_types: tuple[str, ...],
    failure_categories: tuple[str, ...],
    evidence_types: tuple[E, ...],
    tools: tuple[Tool, ...],
) -> SubjectConfig:
    """A subject's behaviour, joined to its registered number, name and topics."""
    entry = registry.subject(key)
    return SubjectConfig(
        key=key,
        number=entry.number,
        name=entry.name,
        tagline=tagline,
        tier=tier,
        topics=entry.topic_names,
        artifact_types=artifact_types,
        failure_categories=failure_categories,
        evidence_types=evidence_types,
        tools=tools,
    )


_CONFIGS: tuple[SubjectConfig, ...] = (
    _config(
        "aptitude",
        tagline="The reference implementation. Prove the arithmetic.",
        tier="A",
        artifact_types=(
            "numeric_solution",
            "logical_argument",
            "data_table",
            "series",
            "passage_analysis",
        ),
        failure_categories=("F01", "F02", "F03", "F05", "F06", "F07", "F09", "F15"),
        evidence_types=(
            E.COUNTEREXAMPLE,
            E.CALCULATION,
            E.CONTRADICTION,
            E.RULE,
            E.DATA_POINT,
            E.REWRITE,
        ),
        tools=_APTITUDE_TOOLS,
    ),
    _config(
        "programming",
        tagline="It runs. That is not the same as correct.",
        tier="A",
        artifact_types=("code", "function", "class_design"),
        # F09: "the suite is green, so it is correct" - the failure every
        # Break-the-Tests challenge exercises.
        failure_categories=("F04", "F02", "F01", "F16", "F06", "F09"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.TRACE, E.REWRITE),
        tools=_CODE_TOOLS,
    ),
    _config(
        "computer-science",
        tagline="Confident claims about systems that do not behave that way.",
        tier="B",
        artifact_types=("explanation", "architecture", "trace"),
        failure_categories=("F03", "F02", "F07", "F09", "F11"),
        evidence_types=(E.COUNTEREXAMPLE, E.RULE, E.TRACE, E.CONTRADICTION),
        tools=_CODE_TOOLS,
    ),
    _config(
        "dsa",
        tagline="The edge case the solution never considered.",
        tier="A",
        artifact_types=("code", "algorithm", "complexity_analysis", "recurrence"),
        failure_categories=("F04", "F02", "F10", "F03", "F16", "F09"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.TRACE, E.CALCULATION),
        tools=_CODE_TOOLS,
    ),
    _config(
        "databases",
        tagline="The query returns rows. The wrong ones.",
        tier="B",
        artifact_types=("sql", "schema", "query_plan"),
        failure_categories=("F12", "F02", "F10", "F07", "F03"),
        evidence_types=(E.COUNTEREXAMPLE, E.DATA_POINT, E.REWRITE, E.TRACE),
        tools=_DB_TOOLS,
    ),
    _config(
        "frontend",
        tagline="Looks right in one viewport, for one user.",
        tier="B",
        artifact_types=("code", "markup", "stylesheet", "component"),
        failure_categories=("F04", "F07", "F02", "F16", "F06"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.RULE, E.REWRITE),
        tools=_CODE_TOOLS,
    ),
    _config(
        "backend",
        tagline="The contract holds until someone sends the wrong payload.",
        tier="B",
        artifact_types=("code", "api_contract", "middleware_chain"),
        failure_categories=("F11", "F04", "F08", "F02", "F06"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.TRACE, E.RULE),
        tools=_API_TOOLS,
    ),
    _config(
        "api-integration",
        tagline="200 OK is not proof that it worked.",
        tier="B",
        artifact_types=("api_request", "api_response", "webhook", "integration_code"),
        failure_categories=("F07", "F11", "F04", "F08", "F06"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.DATA_POINT, E.TRACE),
        tools=_API_TOOLS,
    ),
    _config(
        "data-analytics",
        tagline="A chart that tells a story the data does not support.",
        # NumericAdapter in engine/registry.py checks the arithmetic on numeric
        # artifacts here, so this is Tier A - textual ones fall back to reasoning.
        tier="A",
        artifact_types=("chart", "dashboard", "data_table", "kpi_definition"),
        failure_categories=("F12", "F05", "F16", "F09", "F01"),
        evidence_types=(E.DATA_POINT, E.CALCULATION, E.COUNTEREXAMPLE, E.RULE),
        tools=_DATA_TOOLS,
    ),
    _config(
        "data-science",
        tagline="The number is real. The conclusion is not.",
        tier="B",
        artifact_types=("notebook", "experiment_design", "statistical_claim", "code"),
        failure_categories=("F12", "F13", "F09", "F03", "F16"),
        evidence_types=(E.DATA_POINT, E.CALCULATION, E.COUNTEREXAMPLE, E.TEST_CASE),
        tools=_DATA_TOOLS,
    ),
    _config(
        "mathematics",
        tagline="One invalid transformation, buried in a valid proof.",
        # NumericAdapter in engine/registry.py checks the arithmetic on numeric
        # artifacts here, so this is Tier A - proofs fall back to reasoning.
        tier="A",
        artifact_types=("proof", "derivation", "numeric_solution"),
        failure_categories=("F01", "F02", "F07", "F03", "F06"),
        evidence_types=(E.COUNTEREXAMPLE, E.CALCULATION, E.CONTRADICTION, E.RULE),
        tools=_APTITUDE_TOOLS,
    ),
    _config(
        "machine-learning",
        tagline="99% accuracy on a 99:1 dataset.",
        tier="B",
        artifact_types=("model_evaluation", "training_code", "metric_report"),
        failure_categories=("F13", "F12", "F03", "F16", "F09"),
        evidence_types=(E.DATA_POINT, E.CALCULATION, E.COUNTEREXAMPLE, E.TEST_CASE),
        tools=_DATA_TOOLS,
    ),
    _config(
        "deep-learning",
        tagline="The shapes line up. The semantics do not.",
        tier="B",
        artifact_types=("architecture", "training_code", "model_evaluation"),
        failure_categories=("F01", "F13", "F12", "F03", "F16"),
        evidence_types=(E.TRACE, E.CALCULATION, E.COUNTEREXAMPLE, E.TEST_CASE),
        tools=_DATA_TOOLS,
    ),
    _config(
        "ai",
        tagline="Fluent, sourced, and wrong.",
        tier="B",
        artifact_types=("explanation", "architecture", "evaluation", "retrieval_trace"),
        failure_categories=("F14", "F09", "F13", "F03", "F16"),
        evidence_types=(E.COUNTEREXAMPLE, E.CONTRADICTION, E.DATA_POINT, E.RULE),
        tools=_AI_TOOLS,
    ),
    _config(
        "prompt-engineering",
        tagline="A prompt that holds until someone tries to break it.",
        tier="B",
        artifact_types=("prompt", "guardrail", "evaluation"),
        failure_categories=("F11", "F06", "F13", "F15", "F16"),
        evidence_types=(E.COUNTEREXAMPLE, E.TEST_CASE, E.REWRITE, E.TRACE),
        tools=_AI_TOOLS,
    ),
    _config(
        "devops",
        tagline="It deploys. That is the problem.",
        tier="B",
        artifact_types=("dockerfile", "k8s_manifest", "pipeline", "shell_command"),
        failure_categories=("F11", "F03", "F04", "F08", "F10"),
        evidence_types=(E.COUNTEREXAMPLE, E.TRACE, E.RULE, E.REWRITE),
        tools=_DEVOPS_TOOLS,
    ),
    _config(
        "mlops",
        tagline="The pipeline is green and the model is stale.",
        tier="B",
        artifact_types=("pipeline", "monitoring_config", "deployment_manifest"),
        failure_categories=("F12", "F13", "F08", "F11", "F10"),
        evidence_types=(E.TRACE, E.DATA_POINT, E.COUNTEREXAMPLE, E.RULE),
        tools=_DEVOPS_TOOLS,
    ),
    _config(
        "no-code-automation",
        tagline="The workflow fires. Twice. Forever.",
        tier="B",
        artifact_types=("workflow", "trigger_config", "automation_run"),
        failure_categories=("F02", "F04", "F11", "F14", "F08"),
        evidence_types=(E.TRACE, E.COUNTEREXAMPLE, E.TEST_CASE, E.RULE),
        tools=_DEVOPS_TOOLS,
    ),
    _config(
        "english",
        tagline="Claims that read well but break a rule.",
        tier="B",
        artifact_types=("sentence", "paragraph", "passage_analysis"),
        failure_categories=("F07", "F05", "F09", "F06"),
        evidence_types=(E.RULE, E.REWRITE, E.CONTRADICTION, E.COUNTEREXAMPLE),
        tools=_TEXT_TOOLS,
    ),
)

# Served in registry order, which is the order students see.
SUBJECTS: tuple[SubjectConfig, ...] = tuple(sorted(_CONFIGS, key=lambda c: c.number))

BY_KEY: dict[str, SubjectConfig] = {s.key: s for s in SUBJECTS}

# A subject with behaviour but no curriculum, or a curriculum with no
# behaviour, is a wiring mistake - fail at import, not in front of a student.
if set(BY_KEY) != set(registry.BY_KEY) or len(BY_KEY) != len(_CONFIGS):
    raise RuntimeError(
        "catalog and topic registry disagree: "
        f"only in catalog {sorted(set(BY_KEY) - set(registry.BY_KEY))}, "
        f"only in registry {sorted(set(registry.BY_KEY) - set(BY_KEY))}"
    )


def get(key: str) -> SubjectConfig | None:
    return BY_KEY.get(key)
