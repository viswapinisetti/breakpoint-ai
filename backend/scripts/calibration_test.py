"""Tests for the confidence calibration engine (app/engine/calibration.py).

Pure arithmetic over plain records, so this needs no database and no server.

    python -m scripts.calibration_test
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from app.engine.calibration import (
    CONFIDENT_AT,
    Judgment,
    build,
    judgment_note,
)

failures: list[str] = []
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}  {detail}")


def j(confidence, correct, *, ai=90, sided=False, days_ago=0) -> Judgment:
    return Judgment(
        confidence=confidence,
        correct=correct,
        ai_confidence=ai,
        sided_with_ai=sided,
        judged_at=NOW - timedelta(days=days_ago),
    )


def main() -> int:  # noqa: PLR0915 - a linear script reads better here
    print("\n[an empty record says nothing]")
    empty = build([], now=NOW)
    check("no judgments, no rates", empty.judged == 0 and empty.brier is None, empty)
    check("bands are still listed", len(empty.bands) == 5, empty.bands)

    print("\n[judgments without a confidence are skipped, not assumed]")
    r = build([j(None, True), j(None, False), j(80, True)], now=NOW)
    check("only the rated one counts", r.judged == 1, r.judged)

    print("\n[perfect calibration]")
    # 80% sure, right 8 of 10.
    perfect = [j(80, i < 8) for i in range(10)]
    r = build(perfect, now=NOW)
    check("mean confidence 80", r.mean_confidence == 80.0, r.mean_confidence)
    check("accuracy 80%", r.accuracy == 80.0, r.accuracy)
    check("gap is zero", r.gap == 0.0, r.gap)
    # 8 * 0.04 + 2 * 0.64 = 1.6 over 10.
    check("Brier 0.16", r.brier == 0.16, r.brier)

    print("\n[overconfidence shows as a positive gap]")
    r = build([j(95, i < 5) for i in range(10)], now=NOW)
    check("95% sure, right half the time", r.accuracy == 50.0, r.accuracy)
    check("gap +45", r.gap == 45.0, r.gap)
    check("Brier 0.452", r.brier == 0.452, r.brier)
    check("five over-trust errors", r.over_trust == 5, r.over_trust)
    check("no under-trust", r.under_trust == 0, r.under_trust)

    print("\n[underconfidence shows as a negative gap]")
    r = build([j(50, True) for _ in range(10)], now=NOW)
    check("gap -50", r.gap == -50.0, r.gap)
    check("ten under-trust hedges", r.under_trust == 10, r.under_trust)
    check("no over-trust", r.over_trust == 0, r.over_trust)

    print("\n[rates need the same sample as every other rate]")
    r = build([j(80, True) for _ in range(9)], now=NOW)
    check("nine judgments: no Brier yet", r.brier is None and r.gap is None, r)
    check("but the count is reported", r.judged == 9, r.judged)
    r = build([j(80, True) for _ in range(10)], now=NOW)
    check("ten judgments: rates appear", r.brier == 0.04, r.brier)

    print("\n[counts do not wait for the sample]")
    r = build([j(95, False)], now=NOW)
    check("one confident error is named immediately", r.over_trust == 1, r.over_trust)

    print("\n[believing a loud AI]")
    r = build(
        [
            j(95, False, ai=88, sided=True),  # approved a flawed artifact
            j(95, False, ai=88, sided=False),  # wrong, but not by agreeing
            j(95, False, ai=60, sided=True),  # agreed with a quiet AI
            j(95, True, ai=95, sided=True),  # agreed, and was right
        ],
        now=NOW,
    )
    check("only the loud, agreed, wrong one counts", r.believed_confident_ai == 1, r)

    print("\n[the last seven days]")
    r = build(
        [
            j(95, False, ai=88, sided=True, days_ago=1),
            j(95, False, ai=88, sided=True, days_ago=3),
            j(95, False, ai=88, sided=True, days_ago=6),
            j(95, False, ai=88, sided=True, days_ago=9),
            j(50, True, days_ago=2),
        ],
        now=NOW,
    )
    check("four judgments this week", r.recent_judged == 4, r.recent_judged)
    check("three of them over-trust", r.recent_over_trust == 3, r.recent_over_trust)
    check(
        "three believed a loud AI this week, four in all",
        (r.recent_believed_confident_ai, r.believed_confident_ai) == (3, 4),
        (r.recent_believed_confident_ai, r.believed_confident_ai),
    )

    print("\n[a naive timestamp, as SQLite returns it]")
    naive = Judgment(
        confidence=95,
        correct=False,
        ai_confidence=90,
        sided_with_ai=True,
        judged_at=(NOW - timedelta(days=1)).replace(tzinfo=None),
    )
    r = build([naive], now=NOW)
    check("counted in the recent window rather than raising", r.recent_judged == 1, r)

    print("\n[reliability bands]")
    r = build(
        [j(50, False), j(65, True), j(80, True), j(80, False), j(95, True)], now=NOW
    )
    by_label = {b.label: b for b in r.bands}
    check("50 lands in Guessing", by_label["Guessing"].count == 1, by_label["Guessing"])
    check("65 lands in Leaning", by_label["Leaning"].count == 1, by_label["Leaning"])
    check(
        "both 80s land in Fairly sure, 50% accurate",
        (by_label["Fairly sure"].count, by_label["Fairly sure"].accuracy) == (2, 50.0),
        by_label["Fairly sure"],
    )
    check("95 lands in Certain", by_label["Certain"].count == 1, by_label["Certain"])
    check(
        "every judgment lands in exactly one band",
        sum(b.count for b in r.bands) == r.judged,
        [b.count for b in r.bands],
    )
    check(
        "an empty band reports no accuracy rather than zero",
        by_label["Below even"].accuracy is None,
        by_label["Below even"],
    )

    print("\n[the boundaries are the scale the player offers]")
    check("80 is confident", CONFIDENT_AT == 80, CONFIDENT_AT)
    check(
        "a 79 is not counted as over-trust",
        build([j(79, False)], now=NOW).over_trust == 0,
    )
    check(
        "a 66 is not counted as under-trust",
        build([j(66, True)], now=NOW).under_trust == 0,
    )

    print("\n[what the student is told, one judgment at a time]")
    note = judgment_note(confidence=95, correct=False, ai_confidence=88, sided_with_ai=True)
    check("confident, wrong, agreed with a loud AI: both numbers are quoted",
          "95%" in note and "88%" in note, note)
    note = judgment_note(confidence=95, correct=False, ai_confidence=40, sided_with_ai=False)
    check("confident and wrong on its own: no AI number invented",
          "95%" in note and "40" not in note, note)
    note = judgment_note(confidence=50, correct=True, ai_confidence=90, sided_with_ai=False)
    check("right while hedging is named as hedging", "hedged" in note, note)
    note = judgment_note(confidence=95, correct=True, ai_confidence=90, sided_with_ai=False)
    check("confident and right is praised plainly", "calibration" in note, note)
    note = judgment_note(confidence=50, correct=False, ai_confidence=90, sided_with_ai=False)
    check("unsure and wrong credits the doubt", "doubt" in note, note)
    check(
        "no confidence, no note",
        judgment_note(confidence=None, correct=True, ai_confidence=90, sided_with_ai=False)
        == "",
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("all calibration checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
