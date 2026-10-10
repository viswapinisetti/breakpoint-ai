"""Author challenge content in bulk: generate it through the API, or import
replies saved from ChatGPT.

Generate (needs an AI provider key in backend/.env):

    python -m scripts.bulk_author --dry-run                     # plan + cost, no calls
    python -m scripts.bulk_author --subject aptitude            # one subject
    python -m scripts.bulk_author --subject aptitude --topic "SI & CI"
    python -m scripts.bulk_author                               # every topic

Import (no key; you generated the replies in ChatGPT yourself):

    python -m scripts.bulk_author --import C:\\path\\to\\replies.txt

Both modes run the loop an author would otherwise run by hand, using the same
instructions (docs/content-authoring/CHATGPT_PROMPT.md) and the same checks
(`scripts.validate_content`):

    request a batch -> parse the JSON -> assign ids -> validate
      -> send the problems back for a fix (generate mode) -> repeat
      -> write passing challenges to content/<subject>/<topic-key>-NN.json

Re-running continues where it stopped: what is missing is recomputed from the
content files each time, so an interrupted run loses at most the batch in
flight.

Outputs besides the content files:

* content_review/<timestamp>.md - every challenge written, with the model's
  Reviewer notes and any warnings. Nothing here replaces the human review in
  docs/content-authoring/README.md; it tells the reviewer where to look.
* content_rejected/ - challenges that still failed after the fix rounds,
  each with its errors, for manual repair.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import threading
import time
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from pydantic import ValidationError

from app.agents.client import AgentError, drain_run_log, is_configured, provider_status, text_reply
from app.config import BASE_DIR, settings
from app.engine.contracts import Challenge
from app.governance import validate as validate_challenge
from app.subjects import topics as registry
from scripts.validate_content import _schema_errors, lint

PROMPT_FILE = BASE_DIR.parent / "docs" / "content-authoring" / "CHATGPT_PROMPT.md"
REVIEW_DIR = BASE_DIR / "content_review"
REJECTED_DIR = BASE_DIR / "content_rejected"

# PRD v0.2 section 3.2 truth mix, allocated across topics (see `_targets`).
# Exact fractions, so the carried remainders never drift on float rounding.
SHARE = {"valid": Fraction(26, 100), "insufficient_information": Fraction(6, 100)}
# Difficulty sequence per topic: mostly 2-4, with the occasional 1 and 5.
DIFFICULTIES = ["2", "3", "4", "3", "5", "2", "4", "3", "1", "4"]
STATES = ("flawed", "valid", "insufficient_information")

# Rough sizes for the cost estimate. A published challenge is ~5-6 KB of JSON.
TOKENS_PER_CHALLENGE = 1600
CHARS_PER_TOKEN = 3.6
REPAIR_RATE = 0.4  # share of batches expected to need one fix round

JSON_BLOCK = re.compile(r"```(?:json)?[ \t]*\r?\n(.*?)```", re.DOTALL)
_print_lock = threading.Lock()


def say(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def _show(path: Path) -> str:
    """A path relative to backend/ when it is inside it, absolute otherwise."""
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path)


# --- what already exists -------------------------------------------------------


def _normalise_question(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


class Inventory:
    """Ids, questions and truth-state counts across all content files.

    Shared by worker threads, so every read-modify-write goes through the
    lock: two topics generating at once must not be handed the same id or
    file name.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.ids: set[str] = set()
        self.questions: dict[str, str] = {}
        self.counts: dict[tuple[str, str], Counter] = {}
        self.subtopics: dict[tuple[str, str], list[str]] = {}
        self._reserved_files: set[Path] = set()
        for path in sorted(settings.content_dir.rglob("*.json")):
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    self._register(entry)

    def _register(self, entry: dict) -> None:
        key = (entry.get("subject", ""), entry.get("topic", ""))
        self.ids.add(str(entry.get("id", "")))
        if entry.get("question"):
            self.questions[_normalise_question(entry["question"])] = str(entry.get("id"))
        state = entry.get("truth_state") or (
            "flawed" if entry.get("contains_failure") else "valid"
        )
        self.counts.setdefault(key, Counter())[state] += 1
        if entry.get("subtopic"):
            self.subtopics.setdefault(key, []).append(entry["subtopic"])

    def add(self, entries: list[dict]) -> None:
        with self.lock:
            for entry in entries:
                self._register(entry)

    def reserve_ids(self, subject: str, topic: str, n: int) -> list[str]:
        """The next `n` free ids of the form <prefix>-<topic key>-NNN."""
        entry = registry.BY_KEY[subject]
        stem = f"{entry.id_prefix}-{registry.slugify(topic)}-"
        with self.lock:
            used = [
                int(m.group(1))
                for i in self.ids
                if (m := re.fullmatch(re.escape(stem) + r"(\d+)", i))
            ]
            start = max(used, default=0) + 1
            out = [f"{stem}{n_:03d}" for n_ in range(start, start + n)]
            self.ids.update(out)
            return out

    def reserve_file(self, subject: str, topic: str) -> Path:
        """content/<subject>/<topic key>-NN.json with the next free NN."""
        folder = settings.content_dir / subject
        stem = registry.slugify(topic)
        pattern = re.compile(re.escape(stem) + r"-(\d+)\.json")
        with self.lock:
            candidates = {p.name for p in folder.glob(f"{stem}-*.json")}
            candidates |= {p.name for p in self._reserved_files if p.parent == folder}
            taken = [int(m.group(1)) for name in candidates if (m := pattern.fullmatch(name))]
            path = folder / f"{stem}-{max(taken, default=0) + 1:02d}.json"
            self._reserved_files.add(path)
            return path


# --- planning ------------------------------------------------------------------


@dataclass
class Batch:
    subject: str
    topic: str
    mix: Counter
    difficulties: list[str]
    covered: list[str]

    @property
    def count(self) -> int:
        return sum(self.mix.values())


def _targets(global_index: int, per_topic: int) -> dict[str, int]:
    """Per-topic truth-state targets that add up to the right global mix.

    A 5-challenge topic cannot hold 6% insufficient-information items, so
    the fractions are carried from topic to topic: topic i gets
    floor((i+1)*T*share) - floor(i*T*share) of each state. Across the whole
    registry the mix lands on the target, and it does not depend on which
    subjects a given run happens to cover.
    """
    out = {}
    for state, share in SHARE.items():
        out[state] = math.floor((global_index + 1) * per_topic * share) - math.floor(
            global_index * per_topic * share
        )
    out["flawed"] = per_topic - sum(out.values())
    return out


def plan(inventory: Inventory, *, subject: str | None, topic: str | None,
         per_topic: int, batch_size: int) -> list[Batch]:
    batches: list[Batch] = []
    index = -1
    for entry in registry.REGISTRY:
        for t in entry.topics:
            index += 1
            if subject and entry.key != subject:
                continue
            if topic and t.name != topic:
                continue
            have = inventory.counts.get((entry.key, t.name), Counter())
            remaining = max(0, per_topic - sum(have.values()))
            if not remaining:
                continue
            target = _targets(index, per_topic)
            need: Counter = Counter()
            for state in ("insufficient_information", "valid", "flawed"):
                n = min(remaining, max(0, target[state] - have[state]))
                need[state] = n
                remaining -= n
            need["flawed"] += remaining

            # Interleave states so each batch gets a mix, not all the
            # flawed items in one batch and the valid ones in another.
            sequence: list[str] = []
            left = Counter(need)
            while sum(left.values()):
                for s in STATES:
                    if left[s]:
                        sequence.append(s)
                        left[s] -= 1
            done = sum(have.values())
            for start in range(0, len(sequence), batch_size):
                chunk = sequence[start:start + batch_size]
                difficulties = [
                    DIFFICULTIES[(done + start + i) % len(DIFFICULTIES)]
                    for i in range(len(chunk))
                ]
                batches.append(Batch(entry.key, t.name, Counter(chunk), difficulties,
                                     list(inventory.subtopics.get((entry.key, t.name), []))))
    return batches


def request_text(batch: Batch, start_number: int) -> str:
    mix = ", ".join(f"{batch.mix[s]} {s}" for s in STATES if batch.mix[s])
    covered = (
        "Already covered in this topic - do not repeat these concepts or "
        f"scenarios: {'; '.join(batch.covered)}. Cover other sub-concepts of the topic."
        if batch.covered
        else "Nothing is published in this topic yet. Cover its core sub-concepts, one per challenge."
    )
    return (
        f"Subject: {batch.subject}\n"
        f"Topic: {batch.topic}\n"
        f"Count: {batch.count}\n"
        f"Mix: {mix}\n"
        f"Difficulties: {', '.join(batch.difficulties)}\n"
        f"Start ID number: {start_number:03d}\n"
        f"Notes: {covered} Use a different scenario, failure category and failing-step "
        "position for each challenge."
    )


# --- replies and checking --------------------------------------------------------


class ReplyError(ValueError):
    """The reply contains no usable JSON array."""


def parse_blocks(text: str) -> list[tuple[list[dict], str]]:
    """Every JSON array in a reply, each with the notes that follow it."""
    matches = list(JSON_BLOCK.finditer(text))
    if not matches:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise ReplyError("no ```json block and no JSON array found in the reply")
        spans = [(start, end + 1, len(text))]
        bodies = [text[start:end + 1]]
    else:
        spans = [
            (m.start(1), m.end(1), matches[i + 1].start() if i + 1 < len(matches) else len(text))
            for i, m in enumerate(matches)
        ]
        bodies = [m.group(1) for m in matches]

    out: list[tuple[list[dict], str]] = []
    for (_, end, notes_end), body in zip(spans, bodies):
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ReplyError(
                f"the JSON block is invalid at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
            raise ReplyError("the JSON block must be an array of challenge objects")
        notes = text[end:notes_end].strip().lstrip("`").strip()
        out.append((data, notes))
    return out


@dataclass
class Checked:
    entry: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check(entries: list[dict], inventory: Inventory) -> list[Checked]:
    """validate_content's checks, plus duplicate questions and ids."""
    results: list[Checked] = []
    seen_questions: dict[str, str] = {}
    for entry in entries:
        result = Checked(entry)
        results.append(result)
        question = _normalise_question(str(entry.get("question", "")))
        clash = inventory.questions.get(question) or seen_questions.get(question)
        if question and clash:
            result.errors.append(
                f"duplicate question: the same question as {clash}. Write a new scenario."
            )
        seen_questions[question] = str(entry.get("id"))
        try:
            challenge = Challenge.model_validate(entry)
        except ValidationError as exc:
            result.errors += [f"schema - {e}" for e in _schema_errors(exc)]
            continue
        result.errors += [
            f"{r.validator}: {r.detail}" for r in validate_challenge(challenge) if not r.passed
        ]
        result.warnings += lint(challenge)
    return results


def repair_message(results: list[Checked] | None, problem: str = "") -> str:
    lines = ["The validator reported these problems. Fix all of them and return the "
             "complete corrected JSON array for this batch (every challenge, not only "
             "the changed ones), followed by Reviewer notes.", ""]
    if problem:
        lines.append(f"FAIL: {problem}")
    for r in results or []:
        rid = r.entry.get("id", "?")
        lines += [f"FAIL {rid}: {e}" for e in r.errors]
        lines += [f"warn {rid}: {w}" for w in r.warnings]
    return "\n".join(lines)


def _remap(notes: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        if old and old != new:
            notes = notes.replace(old, new)
    return notes


# --- writing -----------------------------------------------------------------------


class Report:
    """The review file for one run."""

    def __init__(self, heading: str) -> None:
        REVIEW_DIR.mkdir(exist_ok=True)
        self.path = REVIEW_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.md"
        self.lock = threading.Lock()
        self.sections: list[str] = [f"# {heading}", "",
                                    "Review every challenge below before publishing. "
                                    "Checklist: docs/content-authoring/README.md, section 3.", ""]
        self.saved = 0
        self.rejected = 0

    def add(self, subject: str, topic: str, path: Path | None, accepted: list[Checked],
            rejected: list[Checked], notes: str, rejected_path: Path | None) -> None:
        lines = [f"## {subject} / {topic}", ""]
        if path:
            lines += [f"Written to `{_show(path)}`", "",
                      "| id | truth state | difficulty | subtopic |", "|---|---|---|---|"]
            lines += [
                f"| {r.entry.get('id')} | {r.entry.get('truth_state')} | "
                f"{r.entry.get('difficulty')} | {r.entry.get('subtopic')} |"
                for r in accepted
            ]
            lines.append("")
        warned = [(r.entry.get("id"), w) for r in accepted for w in r.warnings]
        if warned:
            lines += ["**Warnings**", ""] + [f"- {i}: {w}" for i, w in warned] + [""]
        if notes:
            lines += ["**Reviewer notes from the model**", "", notes, ""]
        if rejected:
            lines += [f"**Rejected ({len(rejected)})** - saved with errors to "
                      f"`{_show(rejected_path) if rejected_path else '?'}`", ""]
            for r in rejected:
                lines += [f"- {r.entry.get('id')}: " + "; ".join(r.errors)]
            lines.append("")
        with self.lock:
            self.sections += lines
            self.saved += len(accepted)
            self.rejected += len(rejected)
            self.path.write_text("\n".join(self.sections), encoding="utf-8")


def write_results(inventory: Inventory, report: Report, subject: str, topic: str,
                  results: list[Checked], notes: str) -> tuple[int, int]:
    accepted = [r for r in results if not r.errors]
    rejected = [r for r in results if r.errors]
    path = rejected_path = None
    if accepted:
        path = inventory.reserve_file(subject, topic)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([r.entry for r in accepted], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        inventory.add([r.entry for r in accepted])
    if rejected:
        folder = REJECTED_DIR / (subject or "unknown")
        folder.mkdir(parents=True, exist_ok=True)
        stem = registry.slugify(topic) or "unknown-topic"
        rejected_path = folder / f"{stem}-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
        rejected_path.write_text(
            json.dumps([{"_errors": r.errors, **r.entry} for r in rejected],
                       indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    report.add(subject, topic, path, accepted, rejected, notes, rejected_path)
    return len(accepted), len(rejected)


# --- generate mode --------------------------------------------------------------------


@dataclass
class RunOptions:
    model: str | None
    max_tokens: int
    timeout: float
    repair_rounds: int


class BatchFailed(RuntimeError):
    """No usable JSON came back, even after the fix rounds."""


def run_batch(batch: Batch, inventory: Inventory, report: Report, prompt: str,
              opts: RunOptions, label: str) -> tuple[int, int]:
    ids = inventory.reserve_ids(batch.subject, batch.topic, batch.count)
    start_number = int(ids[0].rsplit("-", 1)[1])
    messages = [{"role": "user", "content": request_text(batch, start_number)}]
    results: list[Checked] = []
    notes = ""

    for round_ in range(opts.repair_rounds + 1):
        reply = text_reply(
            agent="bulk_author", role="generation", model=opts.model, system=prompt,
            messages=messages, max_tokens=opts.max_tokens, effort="high",
            timeout=opts.timeout,
        )
        try:
            entries, notes = parse_blocks(reply)[0]
        except ReplyError as exc:
            problem, results = str(exc), []
        else:
            problem = ""
            if len(entries) > len(ids):
                ids += inventory.reserve_ids(batch.subject, batch.topic, len(entries) - len(ids))
            mapping = {}
            for entry, new_id in zip(entries, ids):
                mapping[str(entry.get("id", ""))] = new_id
                # We asked for this subject and topic, so pin them rather
                # than trust the model's spelling.
                entry.update(id=new_id, subject=batch.subject, topic=batch.topic)
            notes = _remap(notes, mapping)
            results = check(entries, inventory)
            if not any(r.errors or r.warnings for r in results):
                break
        if round_ == opts.repair_rounds:
            break
        bad = sum(1 for r in results if r.errors) if results else "reply"
        say(f"  {label}: fixing ({bad} failing), round {round_ + 1}")
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": repair_message(results, problem)},
        ]

    if not results:
        # Keep the raw reply: it is the only record of what went wrong.
        folder = REJECTED_DIR / batch.subject
        folder.mkdir(parents=True, exist_ok=True)
        raw = folder / f"{registry.slugify(batch.topic)}-{datetime.now():%Y%m%d-%H%M%S-%f}.txt"
        raw.write_text(reply, encoding="utf-8")
        raise BatchFailed(f"{problem} (raw reply saved to {_show(raw)})")
    return write_results(inventory, report, batch.subject, batch.topic, results, notes)


def _pricing(model: str) -> tuple[float, float] | None:
    """$ per token (input, output) from OpenRouter's public model list."""
    try:
        url = f"{settings.openrouter_base_url.rstrip('/')}/models"
        with urllib.request.urlopen(url, timeout=20) as response:
            models = json.loads(response.read()).get("data", [])
    except Exception:  # noqa: BLE001 - the estimate is optional
        return None
    for m in models:
        if m.get("id") == model:
            p = m.get("pricing") or {}
            try:
                return float(p.get("prompt") or 0), float(p.get("completion") or 0)
            except (TypeError, ValueError):
                return None
    return None


def generate(args: argparse.Namespace) -> int:
    if args.subject and args.subject not in registry.BY_KEY:
        print(f"unknown subject {args.subject!r}; registered: {', '.join(registry.BY_KEY)}")
        return 2
    if args.topic:
        if not args.subject:
            print("--topic needs --subject")
            return 2
        check_topic = registry.validate_topic(args.subject, args.topic)
        if not check_topic.passed:
            print(check_topic.detail)
            return 2

    inventory = Inventory()
    batches = plan(inventory, subject=args.subject, topic=args.topic,
                   per_topic=args.per_topic, batch_size=args.batch_size)
    if args.max_batches:
        batches = batches[: args.max_batches]
    prompt = PROMPT_FILE.read_text(encoding="utf-8")

    topics = {(b.subject, b.topic) for b in batches}
    challenges = sum(b.count for b in batches)
    status = provider_status()
    model = args.model or (
        status["models"]["generation"] if status.get("configured")
        else settings.openrouter_generation_model
    )

    prompt_tokens = len(prompt) / CHARS_PER_TOKEN
    tokens_in = sum(
        prompt_tokens + 300 + REPAIR_RATE * (prompt_tokens + b.count * TOKENS_PER_CHALLENGE + 800)
        for b in batches
    )
    tokens_out = sum(b.count * TOKENS_PER_CHALLENGE * (1 + REPAIR_RATE) for b in batches)

    print(f"target: {args.per_topic} challenges per topic, batches of {args.batch_size}")
    print(f"plan:   {len(batches)} batch(es) across {len(topics)} topic(s) -> {challenges} new challenges")
    by_subject: Counter = Counter()
    for b in batches:
        by_subject[b.subject] += b.count
    for key, n in sorted(by_subject.items(), key=lambda kv: registry.BY_KEY[kv[0]].number):
        print(f"        {registry.BY_KEY[key].name:<22} {n:>4}")
    print(f"model:  {model}")
    print(f"tokens: ~{tokens_in / 1e6:.1f}M in, ~{tokens_out / 1e6:.1f}M out (rough; reasoning "
          "tokens and cache discounts vary by model)")
    price = _pricing(model)
    if price:
        cost = tokens_in * price[0] + tokens_out * price[1]
        print(f"cost:   ~${cost:,.0f} at OpenRouter's list price for {model} "
              f"(${price[0] * 1e6:.2f} in / ${price[1] * 1e6:.2f} out per million)")
    else:
        print("cost:   (no OpenRouter price found for this model - check your provider's pricing)")

    if not batches:
        print("\nnothing to do: every selected topic already has the target count")
        return 0
    if args.dry_run:
        print("\ndry run - no calls made. Remove --dry-run to generate.")
        return 0
    if not is_configured():
        print(
            "\nNo AI provider configured. Put your key in backend/.env "
            "(BREAKPOINT_OPENROUTER_API_KEY=... or ANTHROPIC_API_KEY=...), then check it with\n"
            "    python -m scripts.check_provider"
        )
        return 2

    report = Report(f"Bulk authoring run - {datetime.now():%Y-%m-%d %H:%M} - {model}")
    opts = RunOptions(args.model, args.max_tokens, args.timeout, args.repair_rounds)
    print(f"\nwriting review notes to {_show(report.path)}\n")

    saved = rejected = failed = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        # One topic's batches run in order (each sees what the previous one
        # covered); different topics run in parallel.
        by_topic: dict[tuple[str, str], list[Batch]] = {}
        for b in batches:
            by_topic.setdefault((b.subject, b.topic), []).append(b)

        def run_topic(key: tuple[str, str], topic_batches: list[Batch]) -> tuple[int, int, int]:
            s = r = f = 0
            for i, b in enumerate(topic_batches, 1):
                b.covered = list(inventory.subtopics.get(key, []))
                label = f"[{registry.BY_KEY[b.subject].name} / {b.topic}] batch {i}/{len(topic_batches)}"
                say(f"  {label}: requesting {b.count}")
                try:
                    ok, bad = run_batch(b, inventory, report, prompt, opts, label)
                except (AgentError, BatchFailed) as exc:
                    say(f"  {label}: FAILED - {exc}")
                    f += 1
                    continue
                s += ok
                r += bad
                say(f"  {label}: saved {ok}" + (f", rejected {bad}" if bad else ""))
            return s, r, f

        futures = [pool.submit(run_topic, k, v) for k, v in by_topic.items()]
        for future in as_completed(futures):
            s, r, f = future.result()
            saved, rejected, failed = saved + s, rejected + r, failed + f

    runs = drain_run_log()
    minutes = (time.perf_counter() - started) / 60
    print(f"\ndone in {minutes:.0f} min: {saved} saved, {rejected} rejected, {failed} batch(es) failed")
    if runs:
        tin = sum(r.input_tokens for r in runs)
        tout = sum(r.output_tokens for r in runs)
        line = f"usage: {len(runs)} calls, {tin:,} tokens in, {tout:,} out"
        if price:
            line += f", ~${tin * price[0] + tout * price[1]:,.2f}"
        print(line)
    print(f"review: {report.path}")
    if rejected:
        print(f"rejected challenges (with errors): {REJECTED_DIR}")
    print("\nNext: review the file above, run `python -m scripts.validate_content`, "
          "then restart the API to publish.")
    return 0 if not failed else 1


# --- import mode ------------------------------------------------------------------------


def import_replies(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"cannot read {path}: {exc}")
        return 2
    try:
        blocks = parse_blocks(text)
    except ReplyError as exc:
        print(f"{path.name}: {exc}")
        return 1

    inventory = Inventory()
    report = Report(f"Import of {path.name} - {datetime.now():%Y-%m-%d %H:%M}")
    groups: dict[tuple[str, str], tuple[list[dict], list[str]]] = {}
    for entries, notes in blocks:
        seen_keys = set()
        for entry in entries:
            key = (str(entry.get("subject", "")), str(entry.get("topic", "")))
            groups.setdefault(key, ([], []))[0].append(entry)
            seen_keys.add(key)
        for key in seen_keys:
            groups[key][1].append(notes)

    saved = rejected = 0
    for (subject, topic), (entries, notes_list) in groups.items():
        notes = "\n\n".join(n for n in notes_list if n)
        if registry.is_registered(subject, topic):
            ids = inventory.reserve_ids(subject, topic, len(entries))
            mapping = {}
            for entry, new_id in zip(entries, ids):
                mapping[str(entry.get("id", ""))] = new_id
                entry["id"] = new_id
            notes = _remap(notes, mapping)
        results = check(entries, inventory)
        ok, bad = write_results(inventory, report, subject, topic, results, notes)
        saved, rejected = saved + ok, rejected + bad
        name = registry.BY_KEY[subject].name if subject in registry.BY_KEY else subject
        print(f"  {name} / {topic}: saved {ok}" + (f", rejected {bad}" if bad else ""))

    print(f"\n{saved} saved, {rejected} rejected - review: {report.path}")
    if rejected:
        print(
            f"Rejected challenges are in {REJECTED_DIR} with their errors. Paste the "
            "errors into ChatGPT, ask for the corrected JSON, and import that reply."
        )
    return 0 if not rejected else 1


# --- main -----------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True, errors="replace")
    except AttributeError:  # pragma: no cover
        pass

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--import", dest="import_file", metavar="FILE",
                        help="file ChatGPT replies saved in FILE instead of generating")
    parser.add_argument("--subject", help="only this subject (key, e.g. aptitude)")
    parser.add_argument("--topic", help="only this topic (exact name; needs --subject)")
    parser.add_argument("--per-topic", type=int, default=5,
                        help="target number of challenges per topic (default 5)")
    parser.add_argument("--batch-size", type=int, default=5,
                        help="challenges per request (default 5, max 8)")
    parser.add_argument("--max-batches", type=int, default=0,
                        help="stop after this many batches (spending cap)")
    parser.add_argument("--workers", type=int, default=3,
                        help="topics generated in parallel (default 3)")
    parser.add_argument("--repair-rounds", type=int, default=2,
                        help="fix rounds per batch after validation (default 2)")
    parser.add_argument("--model", help="model id override, e.g. from "
                        "`python -m scripts.check_provider --list`")
    parser.add_argument("--max-tokens", type=int, default=20000)
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="seconds per model call (default 600)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the plan and estimated cost without calling the model")
    args = parser.parse_args(argv)

    if args.import_file:
        return import_replies(Path(args.import_file))
    if not 1 <= args.batch_size <= 8:
        print("--batch-size must be 1-8: larger batches lose quality")
        return 2
    return generate(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
