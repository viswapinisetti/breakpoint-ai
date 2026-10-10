"""End-to-end test of the student investigation loop.

Runs entirely offline: strong evidence is accepted by the deterministic
pre-check, so no model call is needed to exercise the full path.

    python -m scripts.e2e_test
"""

from __future__ import annotations

import sys
from uuid import uuid4

from scripts.testdb import use_temp_database

# Each suite asserts on absolute state, so it gets its own database. Must
# run before any `app` import: settings are read at import time.
use_temp_database()

from fastapi.testclient import TestClient

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


def _count(subject: str) -> int:
    """Expected published count, derived from content so adding a challenge
    does not break unrelated assertions."""
    import json

    return sum(
        len(json.loads(path.read_text(encoding="utf-8")))
        for path in (settings.content_dir / subject).rglob("*.json")
    )


APTITUDE_COUNT = _count("aptitude")

# A fresh identity per run. A judgment is recorded once and never revised by
# design, so a fixed student id makes the second run of this suite fail on
# 409s rather than on anything real - and the per-student counts asserted
# below are only meaningful against a clean slate.
_RUN = uuid4().hex[:8]
HDR = {"X-Student-Id": f"e2e-student-{_RUN}", "X-Student-Name": "E2E Student"}
failures: list[str] = []

# Every check in journey order, as (phase, label, passed, detail). The pytest
# wrapper in tests/test_e2e.py runs the journey once and turns each entry into
# a separately named test case, so a failure names the step rather than the
# whole suite. Running this script directly ignores it.
results: list[tuple[str, str, bool, str]] = []
_phase = "start"


def phase(name: str) -> None:
    """Mark the section that subsequent checks belong to."""
    global _phase
    _phase = name
    print(f"\n[{name}]")


def check(label: str, condition: bool, detail: str = "") -> None:
    results.append((_phase, label, bool(condition), str(detail)))
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label} {detail}")


def main() -> int:
    with TestClient(app) as client:
        phase("health")
        health = client.get("/api/health").json()
        check("health ok", health["status"] == "ok")
        print(f"       ai_configured={health['ai_configured']}")

        phase("catalog")
        subjects = client.get("/api/subjects", headers=HDR).json()
        check("19 subjects exposed", len(subjects) == 19, f"got {len(subjects)}")
        apt = next(s for s in subjects if s["key"] == "aptitude")
        check("aptitude is Tier A", apt["tier"] == "A")
        check("aptitude has challenges", apt["challenge_count"] == APTITUDE_COUNT,
              f"got {apt['challenge_count']}, expected {APTITUDE_COUNT}")
        check("aptitude has deterministic validator",
              apt["has_deterministic_validator"])
        # AC-01 coverage gate: every subject must have a playable pack, not
        # merely a card. Aptitude is the deep subject; the rest need 3 each.
        thin = [
            s["name"]
            for s in subjects
            if s["key"] != "aptitude" and s["challenge_count"] < 3
        ]
        check("every subject has a playable pack (>=3)", not thin, f"thin: {thin}")
        check(
            "a Tier B subject serves real challenges",
            next(s for s in subjects if s["key"] == "mlops")["challenge_count"] >= 3,
        )

        phase("topic registry")
        from app.subjects.topics import REGISTRY  # noqa: E402

        check(
            "subjects served in registry order",
            [s["key"] for s in subjects] == [r.key for r in REGISTRY],
            str([s["key"] for s in subjects]),
        )
        mismatched = [
            s["key"]
            for s, r in zip(subjects, REGISTRY)
            if [t["name"] for t in s["topics"]] != list(r.topic_names)
        ]
        check(
            "every subject lists all its registered topics, in order",
            not mismatched,
            f"differs: {mismatched}",
        )
        check(
            "topics are numbered from 1 in order",
            all(
                [t["number"] for t in s["topics"]] == list(range(1, len(s["topics"]) + 1))
                for s in subjects
            ),
        )
        check(
            "topic counts add up to the subject count",
            all(
                sum(t["challenge_count"] for t in s["topics"]) == s["challenge_count"]
                for s in subjects
            ),
            str([(s["key"], s["challenge_count"]) for s in subjects]),
        )
        # Per-topic counts must match the content files exactly - including
        # zero for any topic nothing has been written for yet.
        import json as _json
        from collections import Counter as _Counter

        on_disk = _Counter(
            (e["subject"], e["topic"])
            for path in settings.content_dir.rglob("*.json")
            for e in _json.loads(path.read_text(encoding="utf-8"))
        )
        served = {(s["key"], t["name"]): t["challenge_count"] for s in subjects for t in s["topics"]}
        mismatched_counts = {k: (v, on_disk.get(k, 0)) for k, v in served.items() if v != on_disk.get(k, 0)}
        check(
            "every topic's count matches the content files (empty topics show 0)",
            not mismatched_counts,
            str(list(mismatched_counts.items())[:5]),
        )
        check(
            "single-subject endpoint matches the list",
            client.get("/api/subjects/aptitude", headers=HDR).json()["topics"]
            == apt["topics"],
        )

        phase("leak check - the most important test")
        started = client.post(
            "/api/challenges/apt-pct-001/start", headers=HDR
        ).json()
        body = started["challenge"]
        leaked = [
            k for k in (
                # v0.2 adjudication key - none of this may reach the browser
                # before the student commits to a judgment (AC-08).
                "truth_state", "contains_failure", "failure",
                "missing_information", "resolving_scenarios",
                "canonical_solution", "canonical_answer", "repair", "debrief",
                "valid_evidence", "counterexamples", "hints",
                "validation_payload", "answer_coincidentally_correct",
            ) if k in body
        ]
        check("no solution data in student view", not leaked, f"leaked {leaked}")
        check("steps present", len(body["ai_solution"]) == 4)
        check("confidence shown", body["simulated_confidence"] == 96)
        check("first start is a new attempt", started["resumed"] is False)

        again = client.post("/api/challenges/apt-pct-001/start", headers=HDR).json()
        check("canonical answer absent from payload", "960" not in str(again))
        check("re-opening resumes rather than duplicating", again["resumed"] is True)
        check("same attempt id on resume",
              again["attempt_id"] == started["attempt_id"])

        attempt_id = started["attempt_id"]

        phase("hints")
        h1 = client.post(f"/api/attempts/{attempt_id}/hint", headers=HDR).json()
        check("hint 1 is attention-level", h1["kind"] == "attention")
        check("hint 1 does not name the step", "step 3" not in h1["text"].lower())
        check("hints remaining tracked", h1["hints_remaining"] == 4)

        phase("judge")
        judged = client.post(
            f"/api/attempts/{attempt_id}/judge",
            headers=HDR,
            json={"judgment": "challenge", "located_step": 3, "confidence": 80},
        ).json()
        check("judged correctly", judged["correct"] is True)
        check("confidence echoed back", judged["confidence"] == 80, judged["confidence"])
        check("the AI's badge is reported alongside it",
              judged["ai_confidence"] == 96, judged["ai_confidence"])
        check("confident and right is named as calibration",
              "80%" in judged["calibration_note"]
              and "calibration" in judged["calibration_note"],
              judged["calibration_note"])
        check("truth state revealed only after judging",
              judged["truth_state"] == "flawed", judged["truth_state"])
        check("outcome task is repair for a flawed artifact",
              judged["outcome_task"] == "repair", judged["outcome_task"])
        check("first failure localised", judged["located_first_failure"] is True)
        check("evidence required", judged["requires_evidence"] is True)

        rejudge = client.post(
            f"/api/attempts/{attempt_id}/judge",
            headers=HDR,
            json={"judgment": "approve"},
        )
        check("re-judging blocked", rejudge.status_code == 409)

        phase("evidence - typed cards, PRD v0.2 6.4 / 9.1")
        key = "e2e-key-000001"
        ev = client.post(
            f"/api/attempts/{attempt_id}/evidence",
            headers=HDR,
            json={
                "idempotency_key": key,
                "cards": [
                    {
                        "type": "calculation",
                        "expression": "800 * 20 / 100",
                        "value": "160",
                        "unit": "Rs",
                        "references_step": 3,
                        "why_supports": "The increase applies to the reduced price "
                                        "of Rs 800, giving 960 rather than 1000.",
                    }
                ],
            },
        )
        check("typed submission accepted", ev.status_code == 200, ev.text[:200])
        if ev.status_code == 200:
            d = ev.json()
            check("revision 1 recorded", d["revision"] == 1, str(d["revision"]))
            check("arithmetic checked deterministically", d["checks_passed"] is True)
            check(
                "checks reported separately from acceptance",
                "checks_passed" in d and "accepted" in d,
            )
            check(
                "v0.2 evaluation status",
                d["status"] in ("supported", "needs_revision", "review_pending"),
                d["status"],
            )

        print("\n  idempotency (PRD v0.2 13.3)")
        replay = client.post(
            f"/api/attempts/{attempt_id}/evidence",
            headers=HDR,
            json={
                "idempotency_key": key,
                "cards": [
                    {
                        "type": "rule",
                        "rule": "an entirely different card",
                        "why_supports": "different",
                    }
                ],
            },
        )
        check(
            "retry with the same key replays rather than duplicating",
            replay.status_code == 200 and replay.json()["replayed"] is True,
            replay.text[:150],
        )
        check("replay keeps revision 1", replay.json()["revision"] == 1)

        print("\n  deterministic failure is final (PRD v0.2 9.2)")
        bad_math = client.post(
            f"/api/attempts/{attempt_id}/evidence",
            headers=HDR,
            json={
                "idempotency_key": "e2e-key-000002",
                "cards": [
                    {
                        "type": "calculation",
                        "expression": "800 * 20 / 100",
                        "value": "200",
                        "references_step": 3,
                        "why_supports": "a fluent but arithmetically wrong argument",
                    }
                ],
            },
        )
        check("wrong arithmetic still returns 200", bad_math.status_code == 200)
        if bad_math.status_code == 200:
            b = bad_math.json()
            check("status needs_revision", b["status"] == "needs_revision", b["status"])
            check(
                "machine-readable reason code",
                b["reason_code"] == "value_mismatch",
                b["reason_code"],
            )
            check("not accepted despite fluent prose", b["accepted"] is False)

        print("\n  structural validation (PRD v0.2 9.1 stage 1)")
        for label, payload, want in (
            (
                "missing required field",
                {
                    "idempotency_key": "e2e-key-000003",
                    "cards": [
                        {"type": "calculation", "value": "160", "why_supports": "x"}
                    ],
                },
                422,
            ),
            ("empty submission", {"idempotency_key": "e2e-key-000004", "cards": []}, 422),
            (
                "more than five cards",
                {
                    "idempotency_key": "e2e-key-000005",
                    "cards": [{"type": "rule", "rule": "r", "why_supports": "w"}] * 6,
                },
                422,
            ),
            (
                "reference to a nonexistent step",
                {
                    "idempotency_key": "e2e-key-000006",
                    "cards": [
                        {
                            "type": "rule",
                            "rule": "r",
                            "references_step": 99,
                            "why_supports": "w",
                        }
                    ],
                },
                422,
            ),
        ):
            r = client.post(
                f"/api/attempts/{attempt_id}/evidence", headers=HDR, json=payload
            )
            check(f"{label} rejected", r.status_code == want, str(r.status_code))

        print("\n  contradictory cards get clarification (PRD v0.2 9.2)")
        conflict = client.post(
            f"/api/attempts/{attempt_id}/evidence",
            headers=HDR,
            json={
                "idempotency_key": "e2e-key-000007",
                "cards": [
                    {
                        "type": "calculation",
                        "expression": "800*20/100",
                        "value": "160",
                        "references_step": 3,
                        "why_supports": "a",
                    },
                    {
                        "type": "calculation",
                        "expression": "1000*20/100",
                        "value": "200",
                        "references_step": 3,
                        "why_supports": "b",
                    },
                ],
            },
        )
        check("conflicting cards handled", conflict.status_code == 200)
        if conflict.status_code == 200:
            check(
                "conflict reason code",
                conflict.json()["reason_code"] == "cards_conflict",
                conflict.json()["reason_code"],
            )

        phase("transfer check + appeal - PRD v0.2 5.2, 9.4")
        tr = client.post(
            f"/api/attempts/{attempt_id}/transfer",
            headers=HDR,
            json={"answer": "1980"},
        )
        check("transfer check accepted", tr.status_code == 200, tr.text[:150])
        if tr.status_code == 200:
            check("correct transfer answer recognised", tr.json()["correct"] is True)
        tr_wrong = client.post(
            f"/api/attempts/{attempt_id}/transfer",
            headers=HDR,
            json={"answer": "2000"},
        )
        check("wrong transfer answer marked wrong",
              tr_wrong.status_code == 200 and tr_wrong.json()["correct"] is False)

        ap = client.post(
            f"/api/attempts/{attempt_id}/appeal",
            headers=HDR,
            json={"reason": "My alternative method reaches 960 and was not credited."},
        )
        check("appeal opened", ap.status_code == 202, ap.text[:150])

        phase("repair + autopsy")
        auto = client.post(f"/api/attempts/{attempt_id}/complete", headers=HDR)
        check("completion ok", auto.status_code == 200, auto.text[:160])
        if auto.status_code == 200:
            a = auto.json()
            check("failure category surfaced", a["failure_category"] == "F03")
            check("autopsy carries truth state", a["truth_state"] == "flawed")
            check("failure labelled", a["failure_label"] == "Hidden Assumption")
            statuses = [s["status"] for s in a["replay"]]
            check("replay marks first failure at step 3",
                  statuses == ["valid", "valid", "first_failure", "derived"],
                  str(statuses))
            check("canonical answer revealed after completion",
                  a["canonical_answer"] == "960")
            check("counterfactual present", "960" in a["counterfactual"])
            check("score out of 100", 0 <= a["score"]["total"] <= 100, str(a["score"]))
            check("score uses v0.2 dimensions",
                  set(a["score"]) >= {"initial_judgment", "evidence", "reasoning",
                                      "outcome_task", "total", "assisted"},
                  str(sorted(a["score"])))
            print(f"       score {a['score']['total']} {a['score']}")

        phase("false-failure challenge - approving correct work")
        s2 = client.post("/api/challenges/apt-mark-009/start", headers=HDR).json()
        j2 = client.post(
            f"/api/attempts/{s2['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "approve", "confidence": 95},
        ).json()
        check("approving a valid artifact scores as correct", j2["correct"] is True)
        check("valid truth state reported", j2["truth_state"] == "valid")
        check("outcome task is justify for a valid artifact",
              j2["outcome_task"] == "justify", j2["outcome_task"])

        phase("false alarm is penalised")
        s3 = client.post("/api/challenges/apt-avg-010/start", headers=HDR).json()
        j3 = client.post(
            f"/api/attempts/{s3['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "challenge", "located_step": 2, "confidence": 95},
        ).json()
        check("challenging correct work is wrong", j3["correct"] is False)
        check("confident and wrong is named, without inventing an AI number",
              "95%" in j3["calibration_note"] and "91" not in j3["calibration_note"],
              j3["calibration_note"])

        phase("insufficient information - the third truth state")
        s5 = client.post("/api/challenges/apt-spd-011/start", headers=HDR).json()
        body5 = s5["challenge"]
        check(
            "missing info hidden before judging",
            "missing_information" not in body5
            and "resolving_scenarios" not in body5,
        )
        j5 = client.post(
            f"/api/attempts/{s5['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "insufficient_information", "confidence": 50},
        ).json()
        check("identifying insufficient information is correct", j5["correct"] is True)
        check("right while hedging is named as hedging",
              "hedged" in j5["calibration_note"], j5["calibration_note"])
        check(
            "outcome task is clarify",
            j5["outcome_task"] == "clarify",
            j5["outcome_task"],
        )
        a5 = client.post(
            f"/api/attempts/{s5['attempt_id']}/complete", headers=HDR
        ).json()
        check("autopsy names the missing fact", bool(a5["missing_information"]))
        check(
            "autopsy shows competing readings",
            len(a5["resolving_scenarios"]) >= 2,
            str(len(a5["resolving_scenarios"])),
        )

        s6 = client.post("/api/challenges/apt-di-004/start", headers=HDR).json()
        j6 = client.post(
            f"/api/attempts/{s6['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "insufficient_information", "confidence": 50},
        ).json()
        check(
            "claiming insufficient info on a determinate artifact is wrong",
            j6["correct"] is False,
        )
        check("wrong while unsure credits the doubt",
              "doubt" in j6["calibration_note"], j6["calibration_note"])

        bad_judgment = client.post(
            f"/api/attempts/{s6['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "maybe"},
        )
        check(
            "unknown judgment rejected",
            bad_judgment.status_code in (409, 422),
            str(bad_judgment.status_code),
        )

        phase("stats")
        st = client.get("/api/stats", headers=HDR).json()
        check("5 investigations recorded", st["claims_investigated"] == 5,
              str(st["claims_investigated"]))
        check("1 failure found", st["failures_found"] == 1)
        check("1 correct approval", st["correct_approvals"] == 1)
        check("1 false alarm recorded", st["false_alarms"] == 1)
        check("rates withheld below the minimum sample",
              st["first_judgment_accuracy"] is None
              and st["resolved_mixed_mode"] < st["min_sample"],
              f"resolved={st['resolved_mixed_mode']} min={st['min_sample']}")
        check("three-way matrix returned", len(st["judgment_matrix"]) == 3)
        check("insufficient info counted", st["correct_insufficient"] == 1,
              str(st["correct_insufficient"]))
        check("streak started", st["streak_days"] == 1)
        check("FIRST BREAK unlocked", any("FIRST BREAK" in a for a in st["achievements"]))
        check("no confidence-based achievement (PRD v0.2 7.2)",
              not any("CONFIDENCE" in a for a in st["achievements"]))
        check("failure categories tracked",
              st["failure_categories"].get("Hidden Assumption") == 1)
        print(f"       investigation score {st['investigation_score']}")
        print(f"       skills {st['verification_skills']}")

        phase("history")
        hist = client.get("/api/history", headers=HDR).json()
        check("history has 5 entries", len(hist) == 5, str(len(hist)))

        phase("dashboard endpoints")
        # Every request the dashboard makes on load. These were previously
        # untested, and /challenges/continue was raising AttributeError on
        # every call - invisible here, and fatal in the browser, because the
        # dashboard fetched all five together and one rejection discarded the
        # other four results.
        for path, label in (
            ("/api/challenges/daily", "today's challenge"),
            ("/api/challenges/continue", "resume list"),
            ("/api/subjects", "subject catalog"),
            ("/api/challenges", "challenge catalog"),
            ("/api/stats", "stats"),
            ("/api/history", "history"),
        ):
            response = client.get(path, headers=HDR)
            check(
                f"{label} responds",
                response.status_code == 200,
                f"{path} -> {response.status_code}",
            )

        resume = client.get("/api/challenges/continue", headers=HDR).json()
        check(
            "resume list excludes completed investigations",
            all(not c["completed"] for c in resume),
            str([c["id"] for c in resume if c["completed"]]),
        )

        phase("guards")
        s4 = client.post("/api/challenges/apt-tw-002/start", headers=HDR).json()
        # A well-formed submission, so this exercises the judgment guard rather
        # than tripping schema validation first.
        no_judge = client.post(
            f"/api/attempts/{s4['attempt_id']}/evidence",
            headers=HDR,
            json={
                "idempotency_key": "e2e-guard-0001",
                "cards": [
                    {
                        "type": "calculation",
                        "expression": "1+1",
                        "value": "2",
                        "why_supports": "premature",
                    }
                ],
            },
        )
        check(
            "evidence blocked before judgment",
            no_judge.status_code == 409,
            str(no_judge.status_code),
        )
        other = client.post(
            f"/api/attempts/{attempt_id}/judge",
            headers={"X-Student-Id": "someone-else"},
            json={"judgment": "approve"},
        )
        check("cannot touch another student's attempt", other.status_code == 404)
        missing = client.post("/api/challenges/does-not-exist/start", headers=HDR)
        check("unknown challenge 404s", missing.status_code == 404)

        phase("calibration")
        # Approve a flawed artifact whose badge reads 94, while 95% sure: the
        # exact failure this product exists to train.
        believed = client.post(
            f"/api/attempts/{s4['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "approve", "confidence": 95},
        ).json()
        check("believing a loud, wrong AI is wrong", believed["correct"] is False)
        check(
            "the note quotes both confidences",
            "95%" in believed["calibration_note"]
            and "94%" in believed["calibration_note"],
            believed["calibration_note"],
        )

        out_of_range = client.post(
            f"/api/attempts/{s2['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "approve", "confidence": 150},
        )
        check("a confidence outside 0-100 is refused",
              out_of_range.status_code == 422, str(out_of_range.status_code))

        # A judgment sent without a confidence: recorded, but never read as 50.
        s7 = client.post("/api/challenges/apt-log-003/start", headers=HDR).json()
        j7 = client.post(
            f"/api/attempts/{s7['attempt_id']}/judge",
            headers=HDR,
            json={"judgment": "challenge"},
        ).json()
        check("judging without a confidence still works", j7["correct"] is True)
        check("and says nothing about calibration",
              j7["calibration_note"] == "" and j7["confidence"] is None, j7)

        cal = client.get("/api/stats", headers=HDR).json()["calibration"]
        check("six rated judgments, the unrated one skipped",
              cal["judged"] == 6, cal["judged"])
        check("two confident errors", cal["over_trust"] == 2, cal["over_trust"])
        check("one hedged success", cal["under_trust"] == 1, cal["under_trust"])
        check("one of them believed a loud AI",
              cal["believed_confident_ai"] == 1, cal["believed_confident_ai"])
        check("rates withheld below the minimum sample",
              cal["brier"] is None and cal["gap"] is None
              and cal["judged"] < cal["min_sample"], cal)
        bands = {b["label"]: b["count"] for b in cal["bands"]}
        check("bands account for every rated judgment",
              sum(bands.values()) == cal["judged"], bands)
        check("the 95s land in Certain, the 50s in Guessing",
              bands["Certain"] == 3 and bands["Guessing"] == 2
              and bands["Fairly sure"] == 1, bands)
        check("this week's over-trust is counted",
              cal["recent_over_trust"] == 2 and cal["recent_days"] == 7, cal)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all end-to-end checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
