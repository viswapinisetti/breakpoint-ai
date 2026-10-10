"""Challenge Studio and governance tests.

Focuses on the rules that protect students: an invalid challenge must never
reach PUBLISHED, an edit that breaks a solver must un-publish, and staff-only
data must stay behind the staff dependency.

    python -m scripts.admin_test
"""

from __future__ import annotations

import copy
import sys

from scripts.testdb import use_temp_database

# Each suite asserts on absolute state, so it gets its own database. Must
# run before any `app` import: settings are read at import time.
use_temp_database()

from fastapi.testclient import TestClient

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

# Derive expectations from the content on disk rather than hardcoding counts,
# so adding a challenge does not break unrelated assertions.
def _published_on_disk() -> int:
    import json

    return sum(
        len(json.loads(path.read_text(encoding="utf-8")))
        for path in settings.content_dir.rglob("*.json")
    )


EXPECTED_PUBLISHED = _published_on_disk()
APTITUDE_COUNT = sum(
    1
    for path in (settings.content_dir / "aptitude").rglob("*.json")
    for _ in __import__("json").loads(path.read_text(encoding="utf-8"))
)

STAFF = {"X-Staff-Name": "Reviewer One"}
STUDENT = {"X-Student-Id": "admin-test-student"}
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label} {detail}")


def main() -> int:
    with TestClient(app) as client:
        print("\n[queue + counts]")
        counts = client.get("/api/admin/counts", headers=STAFF).json()
        check(
            f"{EXPECTED_PUBLISHED} published",
            counts["published"] == EXPECTED_PUBLISHED,
            str(counts),
        )
        check("nothing awaiting review", counts["in_review"] == 0)

        print("\n[templates - PRD 58]")
        templates = client.get("/api/admin/templates", headers=STAFF).json()
        check("4 default templates", len(templates) == 4, str(len(templates)))
        check(
            "cross-subject template present",
            any(t["key"] == "correct-answer-invalid-reasoning" for t in templates),
        )
        created = client.post(
            "/api/admin/templates",
            headers=STAFF,
            json={
                "key": "custom-di-misread",
                "name": "Table misread",
                "description": "Reads the wrong row.",
                "desired_failure": "data failure",
                "difficulty": "2",
                "make_correct": False,
                "applicable_subjects": ["aptitude", "data-analytics"],
            },
        )
        check("template created", created.status_code == 201, created.text[:120])

        print("\n[detail view exposes the solution to staff only]")
        detail = client.get(
            "/api/admin/challenges/apt-pct-001", headers=STAFF
        ).json()
        check("body has canonical answer", detail["body"]["canonical_answer"] == "960")
        check("body carries the truth state",
              detail["body"]["truth_state"] == "flawed")
        check("body has solver", "solver" in detail["body"]["validation_payload"])
        check(
            "student_view still hides it",
            "canonical_answer" not in detail["student_view"]
            and "truth_state" not in detail["student_view"],
        )
        check(
            "validators recorded",
            len(detail["validations"]) == 4,
            str(len(detail["validations"])),
        )
        check(
            "topic registry check recorded and passing",
            any(
                v["validator"] == "topic_registered" and v["passed"]
                for v in detail["validations"]
            ),
            str(detail["validations"]),
        )
        check(
            "published allows only flag/retire",
            sorted(detail["allowed_transitions"]) == ["flagged", "retired"],
            str(detail["allowed_transitions"]),
        )

        print("\n[lifecycle - PRD 108]")
        bad = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "approved"},
        )
        check("illegal transition refused", bad.status_code == 409, bad.text[:120])

        flag = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "flagged", "note": "student dispute"},
        )
        check("published -> flagged allowed", flag.status_code == 200, flag.text[:120])
        check("reviewer recorded", flag.json()["reviewed_by"] == "Reviewer One")

        gone = client.get("/api/challenges?subject=aptitude", headers=STUDENT).json()
        check(
            "flagged challenge leaves the student catalog",
            all(c["id"] != "apt-pct-001" for c in gone),
            f"{len(gone)} visible",
        )

        back = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "published", "note": "dispute resolved"},
        )
        check("re-publish allowed", back.status_code == 200, back.text[:120])
        visible = client.get("/api/challenges?subject=aptitude", headers=STUDENT).json()
        check("student catalog restored", len(visible) == APTITUDE_COUNT, str(len(visible)))

        print("\n[version history]")
        detail = client.get("/api/admin/challenges/apt-pct-001", headers=STAFF).json()
        check(
            "transitions snapshotted",
            len(detail["versions"]) >= 2,
            str(len(detail["versions"])),
        )
        check(
            "snapshot carries the note",
            any(v["note"] == "student dispute" for v in detail["versions"]),
        )
        seqs = [v["seq"] for v in detail["versions"]]
        check("audit seq is unique and ordered", seqs == sorted(set(seqs), reverse=True), str(seqs))

        print("\n[edit re-validates - the rule that matters]")
        broken = copy.deepcopy(detail["body"])
        broken["validation_payload"]["solver"] = "answer = 12345"
        resp = client.patch(
            "/api/admin/challenges/apt-pct-001",
            headers=STAFF,
            json={"body": broken, "note": "deliberately broken solver"},
        )
        check("edit accepted for storage", resp.status_code == 200, resp.text[:160])
        if resp.status_code == 200:
            d = resp.json()
            check(
                "broken solver un-publishes",
                d["row"]["status"] == "auto_validated",
                d["row"]["status"],
            )
            check("failed validator reported", d["row"]["failed_validators"] >= 1)
            check("version incremented", d["row"]["version"] == 2, str(d["row"]["version"]))

        after = client.get("/api/challenges?subject=aptitude", headers=STUDENT).json()
        check(
            "students no longer see the broken challenge",
            all(c["id"] != "apt-pct-001" for c in after),
            f"{len(after)} visible",
        )

        blocked = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "approved"},
        )
        check("can move to approved", blocked.status_code == 200, blocked.text[:120])
        publish = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "published"},
        )
        check(
            "publishing an invalid challenge is refused",
            publish.status_code == 409,
            publish.text[:200],
        )

        print("\n[topic registry - an unregistered topic cannot be published]")
        unfiled = copy.deepcopy(broken)
        unfiled["validation_payload"]["solver"] = "answer = 1000 * 0.80 * 1.20"
        unfiled["topic"] = "Quantitative Reasoning"  # retired pre-registry topic
        r = client.patch(
            "/api/admin/challenges/apt-pct-001",
            headers=STAFF,
            json={"body": unfiled, "note": "filed under a retired topic"},
        )
        check("edit stored", r.status_code == 200, r.text[:160])
        if r.status_code == 200:
            failing = [v for v in r.json()["validations"] if not v["passed"]]
            check(
                "only the topic check fails",
                [v["validator"] for v in failing] == ["topic_registered"],
                str(failing),
            )
            check(
                "failure names a registered alternative",
                "Registered topics:" in failing[0]["detail"] if failing else False,
            )
        refused = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "published"},
        )
        check(
            "publishing under an unregistered topic is refused",
            refused.status_code == 409 and "topic_registered" in refused.text,
            refused.text[:200],
        )

        print("\n[repair the edit]")
        fixed = copy.deepcopy(broken)
        fixed["validation_payload"]["solver"] = "answer = 1000 * 0.80 * 1.20"
        r = client.patch(
            "/api/admin/challenges/apt-pct-001",
            headers=STAFF,
            json={"body": fixed, "note": "restored solver"},
        )
        check("fix accepted", r.status_code == 200, r.text[:160])
        check("no failing validators", r.json()["row"]["failed_validators"] == 0)
        pub = client.post(
            "/api/admin/challenges/apt-pct-001/transition",
            headers=STAFF,
            json={"status": "published", "note": "restored"},
        )
        check("now publishable", pub.status_code == 200, pub.text[:160])
        final = client.get("/api/challenges?subject=aptitude", headers=STUDENT).json()
        check("student catalog whole again", len(final) == APTITUDE_COUNT, str(len(final)))

        print("\n[generation guard]")
        # Whether generation is available depends on the environment, and this
        # suite must not fire a real (billable) generation job. Validation
        # guards are asserted either way; the credential guard only when there
        # is genuinely no provider.
        configured = counts["ai_configured"]
        if configured:
            print("    skip  provider configured - not firing a billable job")
        else:
            gen = client.post(
                "/api/admin/generate",
                headers=STAFF,
                json={
                    "subject": "aptitude",
                    "topic": "Ratio, Proportion & Mixtures",
                    "concept": "Ratios",
                    "count": 2,
                },
            )
            check(
                "generation refused without credential",
                gen.status_code == 503,
                f"got {gen.status_code}",
            )
        oversize = client.post(
            "/api/admin/generate",
            headers=STAFF,
            json={
                "subject": "aptitude",
                "topic": "T",
                "concept": "C",
                "count": 99,
            },
        )
        check("oversized batch rejected", oversize.status_code == 422)
        unknown = client.post(
            "/api/admin/generate",
            headers=STAFF,
            json={"subject": "nope", "topic": "T", "concept": "C", "count": 1},
        )
        check("unknown subject rejected", unknown.status_code == 404,
              str(unknown.status_code))
        # Checked before the provider, so this holds with or without a key
        # and never spends anything.
        bad_topic = client.post(
            "/api/admin/generate",
            headers=STAFF,
            json={
                "subject": "aptitude",
                "topic": "Quantitative Reasoning",
                "concept": "C",
                "count": 1,
            },
        )
        check("unregistered topic rejected before any model call",
              bad_topic.status_code == 422, str(bad_topic.status_code))
        check("rejection suggests the registered topics",
              "Registered topics:" in bad_topic.text, bad_topic.text[:160])

        print("\n[reports feed triage - PRD 109]")
        client.post(
            "/api/challenges/apt-tw-002/report",
            headers=STUDENT,
            json={"reason": "unclear wording", "detail": "Ambiguous about who works."},
        )
        reports = client.get("/api/admin/reports", headers=STAFF).json()
        check("report visible to staff", len(reports) == 1, str(len(reports)))
        check("report carries challenge context", reports[0]["challenge_id"] == "apt-tw-002")
        # Filtered rather than scanned: a date-ordered page of the whole
        # catalog would not contain this row once the catalog exceeds the
        # default page size, and that is a property of the listing, not of
        # the report.
        row = client.get(
            "/api/admin/queue?status=published&reported_only=true", headers=STAFF
        ).json()
        check("reported challenges are reachable by filter", len(row) == 1,
              str(len(row)))
        reported = next(r for r in row if r["challenge_id"] == "apt-tw-002")
        check("report count surfaces on the row", reported["reports"] == 1)

        print("\n[analytics]")
        an = client.get("/api/admin/analytics", headers=STAFF).json()
        check(
            "published counted",
            an["published"] == EXPECTED_PUBLISHED,
            str(an["published"]),
        )
        check("subject coverage reported", an["total_subjects"] == 19)
        check(
            "failure distribution built",
            len(an["failure_distribution"]) >= 2,
            str(an["failure_distribution"]),
        )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all Challenge Studio checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
