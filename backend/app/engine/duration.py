"""Time estimates shown against every investigation, topic and subject.

An investigation's estimate comes from its difficulty, plus a little for the
modes that ask for more reading or writing; a topic's is the sum of its
investigations, and a subject's the sum of its topics. So every duration on
screen grows with the number of questions and with how hard they are, and the
contents rail, the subject page and the catalog all show the same numbers.

These are estimates, not measurements - there is no telemetry yet - and this
module is the one place to replace with real medians from the attempts table
once there are enough completions to trust.
"""

from __future__ import annotations

# Minutes for one investigation: read the claim, judge it, build evidence and
# do the outcome task. Level 1 is a visible failure a student can settle in a
# few minutes; level 5 is adversarial and needs a genuine sitting.
MINUTES_BY_DIFFICULTY: dict[str, int] = {
    "1": 5,
    "2": 7,
    "3": 10,
    "4": 14,
    "5": 18,
}
DEFAULT_MINUTES = 10

# Which-AI-Is-Wrong shows two full solutions to read and compare; Break the
# Tests adds writing and re-running test inputs.
EXTRA_MINUTES_BY_MODE: dict[str, int] = {
    "which_ai_is_wrong": 4,
    "break_the_tests": 3,
}


def estimated_minutes(difficulty: str, challenge_mode: str = "") -> int:
    """Estimated minutes for one investigation."""
    return MINUTES_BY_DIFFICULTY.get(str(difficulty), DEFAULT_MINUTES) + (
        EXTRA_MINUTES_BY_MODE.get(str(challenge_mode), 0)
    )
