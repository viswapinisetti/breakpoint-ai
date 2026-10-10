"""Print the topic registry with content coverage per topic.

Reads the content files directly (no database), so it reports what is
authored, not what happens to be seeded:

    python -m scripts.topics_report            # every subject
    python -m scripts.topics_report aptitude   # one subject

Each topic shows its challenge count and truth-state mix (flawed / valid /
insufficient). Topics with no content are marked, which is the list the next
authoring round works from. A challenge naming an unregistered topic is
listed at the end; `scripts.validate_content` fails on the same condition.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

from app.config import settings
from app.subjects.topics import REGISTRY, is_registered

_STATES = ("flawed", "valid", "insufficient_information")


def _truth(entry: dict) -> str:
    if "truth_state" in entry:
        return entry["truth_state"]
    return "flawed" if entry.get("contains_failure") else "valid"


def main(argv: list[str]) -> int:
    only = argv[0] if argv else None
    if only and only not in {s.key for s in REGISTRY}:
        print(f"unknown subject {only!r}; registered: {', '.join(s.key for s in REGISTRY)}")
        return 2

    counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    unregistered: list[str] = []
    for path in sorted(settings.content_dir.rglob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            counts[(entry["subject"], entry["topic"])][_truth(entry)] += 1
            if not is_registered(entry["subject"], entry["topic"]):
                unregistered.append(
                    f"{entry['id']} ({path.name}): {entry['subject']} / {entry['topic']!r}"
                )

    total_topics = covered_topics = 0
    for subject in REGISTRY:
        if only and subject.key != only:
            continue
        subject_total = sum(
            sum(counts[(subject.key, t.name)].values()) for t in subject.topics
        )
        print(f"\n{subject.number:>2}. {subject.name}  ({subject.key})  {subject_total} challenge(s)")
        for topic in subject.topics:
            mix = counts[(subject.key, topic.name)]
            n = sum(mix.values())
            total_topics += 1
            covered_topics += n > 0
            detail = (
                " / ".join(str(mix[s]) for s in _STATES) if n else "no content yet"
            )
            print(f"    {topic.number:>2}. {topic.name:<48} {n:>3}   {detail}")

    print(
        f"\n{covered_topics} of {total_topics} topics have content "
        "(mix shown as flawed / valid / insufficient)."
    )
    if unregistered:
        print("\nChallenges filed under an unregistered topic:")
        for line in unregistered:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
