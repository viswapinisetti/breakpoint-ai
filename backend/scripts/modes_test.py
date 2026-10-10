"""End-to-end test of the P1 challenge modes: F (Break the Tests) and G
(Which AI Is Wrong).

Runs entirely offline. Mode F is decided by executing two implementations, and
Mode G's judgment is decided by the authored verdict, so neither path needs a
model call.

    python -m scripts.modes_test
"""

from __future__ import annotations

import sys
from unittest.mock import patch
from uuid import uuid4

from scripts.testdb import use_temp_database

# Each suite asserts on absolute state, so it gets its own database. Must
# run before any `app` import: settings are read at import time.
use_temp_database()

from fastapi.testclient import TestClient

from app.agents import runtime  # noqa: E402
from app.engine.contracts import EvidenceAssessment  # noqa: E402
from app.main import app  # noqa: E402

# A fresh identity per run. Attempts are one-shot on judgment by design, so a
# fixed student id would make the second run of this suite fail on 409s rather
# than on anything real.
_RUN = uuid4().hex[:8]
HDR = {"X-Student-Id": f"modes-student-{_RUN}", "X-Student-Name": "Modes Student"}
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label} {detail}")


def main() -> int:  # noqa: PLR0915 - a linear script reads better than helpers here
    with TestClient(app) as client:
        # ==============================================================
        # Mode G - Which AI Is Wrong
        # ==============================================================
        print("\n[mode G: both solutions shown, verdict hidden]")
        started = client.post("/api/challenges/apt-wg-001/start", headers=HDR).json()
        body = started["challenge"]
        check("two competing solutions exposed", len(body.get("competing", [])) == 2,
              f"got {len(body.get('competing', []))}")
        labels = [c["label"] for c in body["competing"]]
        check("labelled A and B", labels == ["A", "B"], str(labels))
        check("both solutions carry full reasoning",
              all(len(c["ai_solution"]) >= 4 for c in body["competing"]))
        check("both carry their own confidence",
              {c["simulated_confidence"] for c in body["competing"]} == {95, 71})

        leaked = [
            k for k in ("comparison", "comparison_verdict", "truth_state", "failure",
                        "canonical_answer", "canonical_solution", "hints",
                        "validation_payload", "debrief", "repair")
            if k in body
        ]
        check("verdict and adjudication key hidden", not leaked, f"leaked {leaked}")
        blob = str(body)
        check("divergence step not disclosed", "divergence" not in blob)
        check("no rival's solver in the payload", "solver_a" not in blob)

        print("\n[mode G: only comparison verdicts are accepted]")
        attempt_id = started["attempt_id"]
        rejected = client.post(
            f"/api/attempts/{attempt_id}/judge", headers=HDR,
            json={"judgment": "challenge"},
        )
        check("trust-or-challenge verdict rejected", rejected.status_code == 422,
              str(rejected.status_code))
        detail = rejected.json()["detail"]
        check("error names the permitted verdicts", "a_correct" in detail, detail)
        check("student view advertises the permitted verdicts",
              set(body["allowed_judgments"]) == {
                  "a_correct", "b_correct", "both_correct",
                  "neither_correct", "underdetermined",
              })

        print("\n[mode G: judging the rivals]")
        judged = client.post(
            f"/api/attempts/{attempt_id}/judge", headers=HDR,
            json={"judgment": "b_correct", "located_step": 3},
        ).json()
        check("b_correct is the right verdict", judged["correct"] is True)
        check("divergence step counts as localisation",
              judged["located_first_failure"] is True)
        check("outcome task is repair", judged["outcome_task"] == "repair",
              judged["outcome_task"])

        print("\n[mode G: evidence references the rival solutions' steps]")
        # Mode G has no top-level ai_solution. Bounding step references by it
        # rejected every card as pointing at a step that "does not exist".
        def card(step: int, expression: str, value: str) -> dict:
            return {
                "type": "calculation",
                "references_step": step,
                "expression": expression,
                "value": value,
                "why_supports": "The legs take 3 h and 2 h, 5 h in all, so the "
                "average is total distance over total time.",
            }

        beyond = client.post(
            f"/api/attempts/{attempt_id}/evidence", headers=HDR,
            json={"cards": [card(6, "240/5", "48")], "idempotency_key": uuid4().hex},
        )
        check("a step past both solutions is refused", beyond.status_code == 422,
              str(beyond.status_code))
        check("bound is the longer solution (B has 5 steps, A has 4)",
              "has 5 steps" in str(beyond.json()), str(beyond.json()))

        # Step 5 exists only in B. Capture what the evaluator is shown, with
        # the model call stubbed so the suite stays offline.
        seen: dict[str, str] = {}

        def fake_structured(*, prompt: str, **_: object) -> EvidenceAssessment:
            seen["evaluator"] = prompt
            return EvidenceAssessment(
                disproves_claim=False, correctness=6, specificity=5, relevance=5,
                completeness=4, reproducibility=6, reasoning_quality=5,
                feedback="Say which solution step 5 belongs to.",
            )

        with patch.object(runtime, "structured", fake_structured):
            only_b = client.post(
                f"/api/attempts/{attempt_id}/evidence", headers=HDR,
                json={"cards": [card(5, "240/5", "48")], "idempotency_key": uuid4().hex},
            )
        check("a step only B has is accepted structurally", only_b.status_code == 200,
              f"{only_b.status_code} {only_b.text[:200]}")
        prompt = seen.get("evaluator", "")
        check("evaluator sees solution A", "SOLUTION A (AI Alpha)" in prompt)
        check("evaluator sees solution B's steps", "240 / 5 = 48" in prompt)
        check("evaluator is given the comparison verdict",
              "COMPARISON VERDICT: B is correct and A is not" in prompt)
        check("no empty single-solution block", "AI REASONING" not in prompt)

        called: list[str] = []
        with patch.object(runtime, "structured",
                          lambda **_: called.append("model") or None):
            proof = client.post(
                f"/api/attempts/{attempt_id}/evidence", headers=HDR,
                json={"cards": [card(3, "240/5", "48")], "idempotency_key": uuid4().hex},
            ).json()
        check("canonical evidence at the divergence step is accepted",
              proof.get("accepted") is True, str(proof))
        check("accepted deterministically, without a model call", not called)

        print("\n[mode G: the debate speaks for both rivals]")
        with patch.object(
            runtime, "text_reply",
            lambda *, system, **_: seen.update(debate=system) or "A: I hold my position.",
        ):
            turn = client.post(
                f"/api/attempts/{attempt_id}/debate", headers=HDR,
                json={"message": "A, how long does each leg take?"},
            )
        check("debate turn succeeds", turn.status_code == 200, str(turn.status_code))
        system = seen.get("debate", "")
        check("debate is given both solutions",
              "SOLUTION A" in system and "SOLUTION B" in system)
        check("debate knows which rival is wrong",
              "B is correct and A is not" in system)

        print("\n[mode G: autopsy replays both solutions]")
        client.post(
            f"/api/attempts/{attempt_id}/repair", headers=HDR,
            json={"repair": "Average speed is total distance over total time: 240/5 = 48."},
        )
        autopsy = client.post(f"/api/attempts/{attempt_id}/complete", headers=HDR).json()
        check("verdict disclosed after completion",
              autopsy["comparison_verdict"] == "b_correct")
        check("divergence step disclosed", autopsy["divergence_step"] == 3)
        check("comparison explanation present",
              "average" in autopsy["comparison_explanation"].lower())
        solutions = {step["solution"] for step in autopsy["replay"]}
        check("replay covers both solutions", solutions == {"A", "B"}, str(solutions))
        marked = [s for s in autopsy["replay"] if s["status"] == "divergence"]
        check("divergence marked in both solutions", len(marked) == 2,
              f"got {len(marked)}")
        check("counterfactual explains the divergence",
              "step 3" in autopsy["counterfactual"], autopsy["counterfactual"])

        print("\n[mode G: an underdetermined comparison]")
        s2 = client.post("/api/challenges/apt-wg-002/start", headers=HDR).json()
        a2 = s2["attempt_id"]
        wrong = client.post(
            f"/api/attempts/{a2}/judge", headers=HDR,
            json={"judgment": "a_correct"},
        ).json()
        check("picking a winner is wrong when neither can be right",
              wrong["correct"] is False)
        s3 = client.post("/api/challenges/apt-wg-002/start", headers=HDR).json()
        check("re-opening resumes the same attempt", s3["attempt_id"] == a2)

        s4 = client.post("/api/challenges/apt-wg-003/start", headers=HDR).json()
        a4 = s4["attempt_id"]
        both_wrong = client.post(
            f"/api/attempts/{a4}/judge", headers=HDR,
            json={"judgment": "neither_correct"},
        ).json()
        check("neither_correct accepted where both rivals fail",
              both_wrong["correct"] is True)

        # ==============================================================
        # Mode F - Break the Tests
        # ==============================================================
        print("\n[mode F: the suite and the gap are shown, the answer is not]")
        fs = client.post("/api/challenges/prg-bt-001/start", headers=HDR).json()
        fbody = fs["challenge"]
        gap = fbody["test_gap"]
        check("test gap exposed", gap is not None and gap["entry_point"] == "median")
        check("shipped tests shown", len(gap["existing_tests"]) == 4)
        check("arity declared", gap["arity"] == 1)
        check("shipped code shown", "ordered[len(ordered) // 2]" in fbody["artifact"]["code"])
        check("no reference implementation in the payload",
              "reference_code" not in str(fbody) and "n % 2" not in str(fbody))

        fa = fs["attempt_id"]

        print("\n[mode F: a judgment is required first]")
        early = client.post(
            f"/api/attempts/{fa}/test", headers=HDR, json={"test_input": "[1, 2]"}
        )
        check("test blocked before judging", early.status_code == 409,
              str(early.status_code))

        client.post(
            f"/api/attempts/{fa}/judge", headers=HDR,
            json={"judgment": "challenge", "located_step": 3},
        )
        judged_f = client.post(
            f"/api/attempts/{fa}/judge", headers=HDR, json={"judgment": "challenge"}
        )
        check("judgment is one-shot", judged_f.status_code == 409)

        print("\n[mode F: the prose outcome task is closed]")
        prose = client.post(
            f"/api/attempts/{fa}/repair", headers=HDR,
            json={"repair": "average the two middle values"},
        )
        check("written repair refused for break_the_tests", prose.status_code == 409,
              str(prose.status_code))
        check("refusal points at the test endpoint",
              "test" in prose.json()["detail"])

        print("\n[mode F: student input is data, never code]")
        evil = client.post(
            f"/api/attempts/{fa}/test", headers=HDR,
            json={"test_input": "__import__('os').system('echo pwned')"},
        ).json()
        check("code in a test input is rejected",
              evil["accepted"] is False and evil["reason_code"] == "unparseable_input",
              evil["reason_code"])
        expr = client.post(
            f"/api/attempts/{fa}/test", headers=HDR, json={"test_input": "1 + 1"}
        ).json()
        check("expressions rejected too", expr["reason_code"] == "unparseable_input")

        print("\n[mode F: an already-covered input proves nothing]")
        covered = client.post(
            f"/api/attempts/{fa}/test", headers=HDR, json={"test_input": "[1, 2, 3]"}
        ).json()
        check("shipped test input rejected",
              covered["accepted"] is False
              and covered["reason_code"] == "already_covered",
              covered["reason_code"])

        print("\n[mode F: a non-separating input is informative, not accepted]")
        miss = client.post(
            f"/api/attempts/{fa}/test", headers=HDR, json={"test_input": "[9, 1, 5]"}
        ).json()
        check("odd-length input does not separate them",
              miss["accepted"] is False and miss["reason_code"] == "no_divergence",
              miss["reason_code"])
        check("both outcomes reported back",
              miss["shipped_result"] == miss["correct_result"] == "5",
              f"{miss['shipped_result']} / {miss['correct_result']}")

        print("\n[mode F: breaking the suite]")
        broke = client.post(
            f"/api/attempts/{fa}/test", headers=HDR, json={"test_input": "[1, 2]"}
        ).json()
        check("even-length input breaks it", broke["accepted"] is True,
              broke["reason_code"])
        check("shipped result reported", broke["shipped_result"] == "2",
              broke["shipped_result"])
        check("correct result reported", broke["correct_result"] == "1.5",
              broke["correct_result"])
        check("submissions counted", broke["submissions"] == 5,
              str(broke["submissions"]))

        print("\n[mode F: autopsy records the test]")
        fautopsy = client.post(f"/api/attempts/{fa}/complete", headers=HDR).json()
        check("breaking test recorded", fautopsy["test_broke_suite"] is True)
        check("the input itself is kept", fautopsy["test_input"] == "([1, 2],)",
              fautopsy["test_input"])
        check("attempt count kept", fautopsy["test_submissions"] == 5)
        check("outcome band credited",
              fautopsy["score"]["outcome_task"] > 0, str(fautopsy["score"]))

        print("\n[mode F: a second challenge, string arguments]")
        gs = client.post("/api/challenges/prg-bt-002/start", headers=HDR).json()
        ga = gs["attempt_id"]
        client.post(
            f"/api/attempts/{ga}/judge", headers=HDR,
            json={"judgment": "challenge", "located_step": 1},
        )
        empty = client.post(
            f"/api/attempts/{ga}/test", headers=HDR, json={"test_input": '""'}
        ).json()
        check("the empty string breaks the word counter", empty["accepted"] is True,
              empty["reason_code"])
        check("counts reported as 1 against 0",
              (empty["shipped_result"], empty["correct_result"]) == ("1", "0"),
              f"{empty['shipped_result']} / {empty['correct_result']}")

        print("\n[cross-mode guards]")
        wrong_mode = client.post(
            f"/api/attempts/{attempt_id}/test", headers=HDR,
            json={"test_input": "1"},
        )
        check("test endpoint refuses a non-Mode-F challenge",
              wrong_mode.status_code == 409, str(wrong_mode.status_code))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all mode F/G checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
