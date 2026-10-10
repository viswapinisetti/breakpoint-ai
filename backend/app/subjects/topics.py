"""Topic registry: every subject and its student-facing topics, in order.

This is the one place that says which subjects exist, the order they appear
in, and which topics each one teaches. Everything else reads from it:

* `catalog.py` takes each subject's number, name and topic list from here, so
  a subject's behaviour (tools, evidence types, validator) and its curriculum
  cannot drift apart;
* `governance.validate` refuses a challenge whose `topic` is not registered
  for its subject, so content cannot quietly invent a topic the UI has no
  place for - it fails validation and cannot be published;
* `/api/subjects` serves subjects and topics in this order, which is the
  order the contents rail shows them in, including topics that have no
  published challenges yet.

A challenge names its topic exactly as written here (`"topic": "SI & CI"`).
Topic `key`s are slugs derived from the name, for URLs and DOM ids; they
change when a name changes, so nothing should persist them.

Order is meaning: topics are listed in the sequence a student meets them.
Adding, renaming or reordering a topic is a change to this file alone -
followed by re-filing any challenge that named an old topic, which
`python -m scripts.validate_content` will list.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

from app.subjects.base import ValidationResult


@dataclass(frozen=True)
class Topic:
    """One student-facing topic within a subject."""

    key: str
    number: int
    name: str


@dataclass(frozen=True)
class RegisteredSubject:
    """A subject, its position in the catalog, and its ordered topics."""

    key: str
    number: int
    name: str
    # Every challenge id in this subject starts with "<id_prefix>-", which
    # keeps ids unique across subjects without a central counter.
    id_prefix: str
    topics: tuple[Topic, ...]

    @property
    def topic_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.topics)

    def topic(self, name: str) -> Topic | None:
        return next((t for t in self.topics if t.name == name), None)


def slugify(name: str) -> str:
    """'Percentages, Profit/Loss & Discounts' -> 'percentages-profit-loss-discounts'."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def _subject(
    number: int, key: str, name: str, id_prefix: str, topics: list[str]
) -> RegisteredSubject:
    return RegisteredSubject(
        key=key,
        number=number,
        name=name,
        id_prefix=id_prefix,
        topics=tuple(
            Topic(key=slugify(t), number=i, name=t) for i, t in enumerate(topics, 1)
        ),
    )


REGISTRY: tuple[RegisteredSubject, ...] = (
    _subject(1, "aptitude", "Aptitude", "apt", [
        "Numbers, LCM & HCF",
        "Percentages, Profit/Loss & Discounts",
        "Ratio, Proportion & Mixtures",
        "SI & CI",
        "Averages, Ages & Partnerships",
        "Time, Speed & Distance",
        "Time & Work",
        "Permutations, Combinations & Probability",
        "Data Interpretation",
        "Logical Reasoning",
        "Arrangements & Puzzles",
        "Data Sufficiency & Visual Reasoning",
    ]),
    _subject(2, "programming", "Programming", "prg", [
        "Programming Fundamentals",
        "Conditions & Loops",
        "Functions",
        "Strings & Collections",
        "Object-Oriented Programming",
        "Exception & File Handling",
        "Modules & Packages",
        "Debugging & Testing",
        "Git & Version Control",
        "APIs & JSON",
        "Database Connectivity",
        "Programming Projects",
    ]),
    _subject(3, "computer-science", "Computer Science", "cs", [
        "Computer Fundamentals & Architecture",
        "Operating Systems",
        "Memory, Processes & Threads",
        "Computer Networks",
        "Internet, HTTP & DNS",
        "Data Structures & Algorithms Fundamentals",
        "Database Fundamentals",
        "Software Engineering",
        "Security Fundamentals",
        "Distributed & Cloud Computing Fundamentals",
    ]),
    _subject(4, "dsa", "DSA", "dsa", [
        "Complexity Analysis",
        "Arrays & Strings",
        "Hashing",
        "Linked Lists",
        "Stacks & Queues",
        "Searching & Sorting",
        "Two Pointers & Sliding Window",
        "Recursion & Backtracking",
        "Trees & BST",
        "Heaps & Priority Queues",
        "Graphs",
        "Greedy & Dynamic Programming",
    ]),
    _subject(5, "databases", "Databases", "db", [
        "Database & Relational Fundamentals",
        "Data Modeling & ER Diagrams",
        "SQL Fundamentals",
        "Joins, Aggregations & Subqueries",
        "Advanced SQL & Window Functions",
        "Normalization & Schema Design",
        "Indexing & Query Optimization",
        "Transactions & ACID",
        "NoSQL & MongoDB",
        "Redis, Vector Databases & Modern Data Stores",
    ]),
    _subject(6, "frontend", "Frontend", "fe", [
        "HTML & Semantic Web",
        "CSS & Responsive Design",
        "Flexbox & Grid",
        "JavaScript Fundamentals",
        "DOM & Browser Events",
        "Async JavaScript & APIs",
        "TypeScript",
        "React",
        "Routing & State Management",
        "Forms & Authentication",
        "Testing, Accessibility & Performance",
        "Frontend Project & Deployment",
    ]),
    _subject(7, "backend", "Backend", "be", [
        "Backend & HTTP Fundamentals",
        "Backend Framework Development",
        "REST API Development",
        "Database Integration & ORM",
        "Authentication & Authorization",
        "Validation & Error Handling",
        "Caching & Redis",
        "File Storage & Background Jobs",
        "WebSockets & Real-Time Applications",
        "Testing & Backend Security",
        "Docker & Deployment",
        "Scalability & System Design Fundamentals",
    ]),
    _subject(8, "api-integration", "API Integration", "api", [
        "HTTP & API Fundamentals",
        "REST APIs",
        "Requests, Responses & JSON",
        "API Authentication",
        "Postman & API Testing",
        "OpenAPI / Swagger",
        "Webhooks",
        "Third-Party API Integration",
        "GraphQL Fundamentals",
        "API Security, Rate Limits & Error Handling",
        "AI APIs & Tool Calling",
    ]),
    _subject(9, "data-analytics", "Data Analytics", "da", [
        "Data Analytics Fundamentals",
        "Excel / Google Sheets",
        "SQL for Analytics",
        "Data Cleaning & Preparation",
        "Exploratory Data Analysis",
        "Statistics for Analytics",
        "Power BI",
        "Tableau / Visualization Principles",
        "Dashboard Design",
        "Business Metrics & KPIs",
        "Data Storytelling",
        "Analytics Project",
    ]),
    _subject(10, "data-science", "Data Science", "ds", [
        "Python for Data Science",
        "NumPy & Pandas",
        "SQL for Data Science",
        "Data Collection & Cleaning",
        "Exploratory Data Analysis",
        "Statistics & Probability",
        "Feature Engineering",
        "Machine Learning Fundamentals",
        "Model Evaluation",
        "Time Series & NLP Fundamentals",
        "Data Visualization & Communication",
        "End-to-End Data Science Project",
    ]),
    _subject(11, "mathematics", "Mathematics", "mat", [
        "Algebra & Functions",
        "Sets & Mathematical Logic",
        "Probability",
        "Statistics",
        "Combinatorics",
        "Vectors & Matrices",
        "Linear Algebra",
        "Calculus Fundamentals",
        "Optimization & Gradients",
        "Mathematics for Machine Learning",
    ]),
    _subject(12, "machine-learning", "Machine Learning", "ml", [
        "ML Fundamentals & Problem Framing",
        "Data Preprocessing & Feature Engineering",
        "Linear & Logistic Regression",
        "Decision Trees & Random Forests",
        "Gradient Boosting",
        "KNN, Naive Bayes & SVM",
        "Clustering",
        "Dimensionality Reduction",
        "Model Evaluation & Cross-Validation",
        "Hyperparameter Tuning",
        "Explainability & Responsible ML",
        "ML Project",
    ]),
    _subject(13, "deep-learning", "Deep Learning", "dl", [
        "Neural Network Fundamentals",
        "Forward & Backpropagation",
        "Optimization & Regularization",
        "CNN & Computer Vision",
        "RNN, LSTM & Sequence Models",
        "Attention & Transformers",
        "Embeddings & Transfer Learning",
        "Generative Models",
        "LLM Fundamentals & Fine-Tuning",
        "Deep Learning Project",
    ]),
    _subject(14, "ai", "AI", "ai", [
        "AI Fundamentals & Intelligent Agents",
        "Search & Problem Solving",
        "Knowledge & Reasoning",
        "Machine Learning for AI",
        "NLP",
        "Computer Vision",
        "Generative AI & Foundation Models",
        "Large Language Models",
        "RAG & Vector Search",
        "AI Agents & Tool Use",
        "Multimodal AI",
        "Responsible AI & Evaluation",
    ]),
    _subject(15, "prompt-engineering", "Prompt Engineering", "pe", [
        "LLM & Prompt Fundamentals",
        "Writing Clear Instructions & Context",
        "Zero-Shot & Few-Shot Prompting",
        "Structured Output & JSON",
        "Prompt Templates & Chaining",
        "Prompting for Coding, Data & Research",
        "RAG Prompting",
        "Tool / Function Calling",
        "Agent Prompting",
        "Prompt Security & Injection",
        "Prompt Evaluation & Optimization",
    ]),
    _subject(16, "devops", "DevOps", "dev", [
        "Linux & Shell Fundamentals",
        "Networking Fundamentals",
        "Git & GitHub",
        "Cloud Fundamentals",
        "Docker",
        "CI/CD",
        "Infrastructure as Code & Terraform",
        "Kubernetes Fundamentals",
        "Configuration & Secrets Management",
        "Monitoring, Logging & Observability",
        "DevSecOps",
        "Deployment & Production Project",
    ]),
    _subject(17, "mlops", "MLOps", "mlo", [
        "ML Lifecycle & Reproducibility",
        "Experiment Tracking",
        "Data & Model Versioning",
        "ML Pipelines",
        "Model Registry",
        "Model Serving & APIs",
        "CI/CD/CT for ML",
        "Model Monitoring & Drift",
        "Cloud MLOps",
        "LLMOps, RAG & Agent Monitoring",
    ]),
    _subject(18, "no-code-automation", "No-Code Automation", "nc", [
        "Automation & Workflow Fundamentals",
        "Triggers, Actions & Data Mapping",
        "Conditions, Branching & Loops",
        "Zapier / Make / n8n",
        "Forms, Sheets & Email Automation",
        "Webhooks & API Integration",
        "Business & CRM Automation",
        "AI-Powered Workflows",
        "AI Agents & Tool Automation",
        "Error Handling & Production Automation",
    ]),
    _subject(19, "english", "English", "eng", [
        "Essential Grammar",
        "Vocabulary & Professional English",
        "Reading Comprehension",
        "Spoken English & Fluency",
        "Listening & Pronunciation",
        "Professional Email & Chat Communication",
        "Presentation & Public Speaking",
        "Group Discussion",
        "Résumé, LinkedIn & Professional Writing",
        "HR & Technical Interview Communication",
    ]),
)

BY_KEY: dict[str, RegisteredSubject] = {s.key: s for s in REGISTRY}


def _check_registry() -> None:
    """Fail at import rather than render a broken curriculum.

    A duplicate topic name would make two rail entries indistinguishable and
    let content file under either; a gap in the numbering would mean the
    order shown is not the order written.
    """
    problems: list[str] = []
    if len(BY_KEY) != len(REGISTRY):
        problems.append("duplicate subject key")
    prefixes = [s.id_prefix for s in REGISTRY]
    if len(set(prefixes)) != len(prefixes) or not all(re.fullmatch(r"[a-z]+", p) for p in prefixes):
        problems.append("id prefixes must be unique lowercase words")
    numbers = [s.number for s in REGISTRY]
    if numbers != list(range(1, len(REGISTRY) + 1)):
        problems.append(f"subject numbers must run 1..{len(REGISTRY)} in order, got {numbers}")
    for s in REGISTRY:
        if not s.topics:
            problems.append(f"{s.key}: no topics")
        names = [t.name for t in s.topics]
        keys = [t.key for t in s.topics]
        if len(set(names)) != len(names):
            problems.append(f"{s.key}: duplicate topic name")
        if len(set(keys)) != len(keys) or not all(keys):
            problems.append(f"{s.key}: topic names collide or are empty once slugified")
    if problems:
        raise RuntimeError("invalid topic registry: " + "; ".join(problems))


_check_registry()


def subject(key: str) -> RegisteredSubject:
    """The registered subject, or KeyError if it is not registered."""
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(f"subject {key!r} is not in the topic registry") from None


def topics_for(subject_key: str) -> tuple[Topic, ...]:
    return subject(subject_key).topics


def is_registered(subject_key: str, topic_name: str) -> bool:
    entry = BY_KEY.get(subject_key)
    return entry is not None and entry.topic(topic_name) is not None


def validate_topic(subject_key: str, topic_name: str) -> ValidationResult:
    """The registry check every challenge passes through (see governance)."""
    entry = BY_KEY.get(subject_key)
    if entry is None:
        return ValidationResult(
            False,
            "topic_registered",
            f"Subject {subject_key!r} is not in the topic registry.",
        )
    topic = entry.topic(topic_name)
    if topic is not None:
        return ValidationResult(
            True,
            "topic_registered",
            f"Topic {topic.number} of {len(entry.topics)} in {entry.name}: {topic.name}.",
        )
    close = difflib.get_close_matches(topic_name, entry.topic_names, n=1, cutoff=0.5)
    hint = f" Did you mean {close[0]!r}?" if close else ""
    return ValidationResult(
        False,
        "topic_registered",
        f"Topic {topic_name!r} is not registered for {entry.name}.{hint} "
        f"Registered topics: {', '.join(entry.topic_names)}.",
    )
