"""Appeals and review-queue tests (PRD v0.2 sections 9.4, 11.2).

The property under test is that a learner who disputes an evaluation is not
stuck: the appeal reaches a reviewer with the exact submission attached, the
reviewer can act, and the outcome flows back into the learner's record.

    python -m scripts.review_test
"""

from __future__ import annotations

import sys

from scripts.testdb import use_temp_database

# Each suite asserts on absolute state, so it gets its own database. Must
# run before any `app` import: settings are read at import time.
use_temp_database()

from fastapi.testclient import TestClient

from app.main import app  # noqa: E402

STUDENT = {"X-Student-Id": "review-student"}
STAFF = {"X-Staff-Name": "Reviewer Two"}
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label} {detail}")


def _investigate(client: TestClient, challenge_id: str, judgment: str) -> int:
    """Open an attempt and record a judgment, returning the attempt id."""
    start = client.post(
        f"/api/challenges/{challenge_id}/start", headers=STUDENT
    ).json()
    client.post(
        f"/api/attempts/{start['attempt_id']}/judge",
        headers=STUDENT,
        json={"judgment": judgment},
    )
    return start["attempt_id"]


def main() -> int:
    with TestClient(app) as client:
        print("\n[queue starts empty]")
        counts = client.get("/api/admin/counts", headers=STAFF).json()
        check("no reviews outstanding", counts["reviews"] == 0, str(counts["reviews"]))

        print("\n[a learner appeals an evaluation]")
        attempt = _investigate(client, "apt-pct-001", "challenge")
        ev = client.post(
            f"/api/attempts/{attempt}/evidence",
            headers=STUDENT,
            json={
                "idempotency_key": "review-key-0001",
                "cards": [
                    {
                        "type": "calculation",
                        "expression": "1000 * 0.8 * 1.2",
                        "value": "960",
                        "references_step": 3,
                        "why_supports": "The two factors compose multiplicatively, "
                                        "so the answer is 960.",
                    }
                ],
            },
        )
        check("evidence submitted", ev.status_code == 200, ev.text[:150])
        check(
            "arithmetic verified deterministically",
            ev.status_code == 200 and ev.json()["checks_passed"] is True,
        )
        # Without an AI provider the evaluator cannot judge relevance, so the
        # submission parks for review rather than being marked wrong.
        if ev.status_code == 200:
            check(
                "unavailable evaluator parks for review, not a wrong mark",
                ev.json()["status"] == "review_pending",
                ev.json()["status"],
            )

        appeal = client.post(
            f"/api/attempts/{attempt}/appeal",
            headers=STUDENT,
            json={
                "reason": "My method uses the combined factor 0.8 x 1.2 and reaches "
                          "960. It was not credited."
            },
        )
        check("appeal accepted", appeal.status_code == 202, appeal.text[:150])

        print("\n[a pending appeal does not block the learner]")
        other = _investigate(client, "apt-avg-010", "approve")
        check("can start another investigation", other > 0)
        stats = client.get("/api/stats", headers=STUDENT).json()
        check(
            "pending review is not counted as a wrong judgment",
            stats["missed_failures"] == 0,
            str(stats["missed_failures"]),
        )

        print("\n[the reviewer sees it, with the exact submission]")
        counts = client.get("/api/admin/counts", headers=STAFF).json()
        check("queue depth reported", counts["reviews"] >= 1, str(counts["reviews"]))
        queue = client.get("/api/admin/reviews", headers=STAFF).json()
        check("queue is populated", len(queue) >= 1, str(len(queue)))
        appeal_items = [q for q in queue if q["kind"] == "appeal"]
        check("the appeal is in the queue", len(appeal_items) == 1)
        if appeal_items:
            item = appeal_items[0]
            check("carries the challenge", item["challenge_id"] == "apt-pct-001")
            check("carries the learner's judgment", item["learner_judgment"] == "challenge")
            check("carries the exact cards", len(item["cards"]) == 1, str(item["cards"]))
            if item["cards"]:
                card = item["cards"][0]
                check("card kept its type", card["type"] == "calculation")
                check(
                    "card kept its expression",
                    card["payload"].get("expression") == "1000 * 0.8 * 1.2",
                    str(card["payload"]),
                )

        print("\n[reviewer accepts the alternative method]")
        resolved = client.post(
            f"/api/admin/reviews/appeal/{appeal_items[0]['id']}/resolve",
            headers=STAFF,
            json={
                "outcome": "accept",
                "note": "0.8 x 1.2 is a valid equivalent method.",
                "strength": 9.0,
                "reasoning_quality": 9.0,
            },
        )
        check("resolution accepted", resolved.status_code == 200, resolved.text[:150])

        print("\n[the correction reaches the learner's score]")
        auto = client.post(f"/api/attempts/{attempt}/complete", headers=STUDENT)
        check("attempt completes", auto.status_code == 200, auto.text[:150])
        if auto.status_code == 200:
            score = auto.json()["score"]
            check(
                "credited evidence now scores",
                score["evidence"] == 35,
                str(score),
            )
            check("reasoning credited", score["reasoning"] == 25, str(score))

        print("\n[queue drains]")
        counts = client.get("/api/admin/counts", headers=STAFF).json()
        queue = client.get("/api/admin/reviews", headers=STAFF).json()
        check(
            "resolved appeal leaves the queue",
            not any(q["kind"] == "appeal" for q in queue),
            str([q["kind"] for q in queue]),
        )

        print("\n[quarantine withdraws rather than penalises]")
        a2 = _investigate(client, "apt-tw-002", "approve")
        client.post(
            f"/api/attempts/{a2}/appeal",
            headers=STUDENT,
            json={"reason": "This question seems ambiguous about who works when."},
        )
        q = client.get("/api/admin/reviews", headers=STAFF).json()
        target = next(x for x in q if x["kind"] == "appeal")
        r = client.post(
            f"/api/admin/reviews/appeal/{target['id']}/resolve",
            headers=STAFF,
            json={"outcome": "quarantine", "note": "wording defect confirmed"},
        )
        check("quarantine resolution ok", r.status_code == 200, r.text[:150])
        visible = client.get(
            "/api/challenges?subject=aptitude", headers=STUDENT
        ).json()
        check(
            "quarantined challenge leaves the student catalog",
            all(c["id"] != "apt-tw-002" for c in visible),
        )

        print("\n[guards]")
        bad = client.post(
            "/api/admin/reviews/appeal/99999/resolve",
            headers=STAFF,
            json={"outcome": "uphold"},
        )
        check("unknown appeal 404s", bad.status_code == 404)
        bad2 = client.post(
            "/api/admin/reviews/appeal/1/resolve",
            headers=STAFF,
            json={"outcome": "nonsense"},
        )
        check("unknown outcome rejected", bad2.status_code == 422)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all appeal and review checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
