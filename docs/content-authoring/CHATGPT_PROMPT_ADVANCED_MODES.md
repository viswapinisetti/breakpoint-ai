# Add-on: advanced challenge modes

This extends the main Breakpoint author instructions. Everything there still applies. Produce these modes **only** when the author's request names one with `Mode: which_ai_is_wrong` or `Mode: break_the_tests`. They are harder to author, so the catalog uses them sparingly (a few per subject at most).

---

## A. Which AI Is Wrong: `"challenge_mode": "which_ai_is_wrong"`

Two AI assistants answer the same question and disagree. The student decides which, if either, is right, and where the two lines of reasoning part company.

**Subjects:** Aptitude, Mathematics and Data Analytics (numeric answers only), because each rival's answer is verified by running its own solver.

**Verdicts.** The student picks one of five, so any of them may be the true answer. Do not always make one rival right:

| `comparison.verdict` | Meaning | `truth_state` | `failure` |
|---|---|---|---|
| `"a_correct"` | A is right, B is wrong | `"flawed"` | the failure in **B** |
| `"b_correct"` | B is right, A is wrong | `"flawed"` | the failure in **A** |
| `"neither_correct"` | both are wrong | `"flawed"` | the failure in one of them (the more instructive) |
| `"both_correct"` | different routes, same valid answer | `"valid"` | `null` |
| `"underdetermined"` | the question cannot decide between them | `"insufficient_information"` | `null` |

**Fields that differ from the main instructions:**

- `competing`: **exactly two** objects, labelled `"A"` then `"B"`:
  `{"label": "A", "persona": "AI Alpha", "ai_claim": "...", "ai_solution": [{"index": 1, "text": "..."}, ...], "ai_final_answer": "50", "simulated_confidence": 95}`
  - Each rival has at least 2 steps (4-5 is typical), and the step numbering is shared, so step 3 means step 3 in both.
  - The two confidences may differ (e.g. 95 against 71). **The more confident rival must not always be the wrong one, or always the right one.** Vary it.
- Top-level `ai_claim`: `""`, `ai_solution`: `[]`, `ai_final_answer`: `""`, `simulated_confidence`: `0`. The rivals carry these instead.
- `comparison`: `{"verdict": "...", "divergence_step": 3, "explanation": "..."}`
  - `divergence_step`: the first step where the two solutions part company. It must exist in **both** solutions.
  - `explanation`: what the divergence turns on, and why the verdict holds. Shown after completion.
- The rivals' final answers must **differ**, except for `both_correct`, where both equal `canonical_answer`.
- The stated answers must match the verdict: the correct rival(s) state `canonical_answer`; the wrong one(s) do not.
- `failure.location` (when present) is a step in a **losing** solution.
- `underdetermined` also needs `missing_information` and at least 2 `resolving_scenarios`, like insufficient-information items. Its `canonical_answer` is a phrase such as `"cannot be determined"`, and the `solver` must return exactly that string.
- `validation_payload` needs **three** solvers:
  - `"solver"`: the correct answer (== `canonical_answer`);
  - `"solver_a"`: A's reasoning exactly as A argues it (== A's `ai_final_answer`);
  - `"solver_b"`: B's reasoning exactly as B argues it (== B's `ai_final_answer`).

  A rival's wrong answer must **follow from its own stated reasoning**, not be a typo.
- `hints`: the ladder helps the student compare **each rival against the definition**, not against each other.
- Step references on evidence cards are currently unreliable in this mode (a known product bug). Author it, but expect those evidence cards to go to human review.

---

## B. Break the Tests: `"challenge_mode": "break_the_tests"`

The artifact is Python code plus a test suite that **passes**. The student must supply one more test input on which the code is wrong. The answer is decided by running the student's input against the shipped code and a correct reference implementation.

**Subjects:** Programming and DSA only, Python only.

**Fields that differ from the main instructions:**

- `truth_state`: `"flawed"` (the code is always wrong for some input). `ai_final_answer`: `"correct"` (the AI claims the code is correct). `canonical_answer`: a short phrase naming the gap, e.g. `"incorrect for even-length lists"`.
- `ai_claim` and `ai_solution`: the AI argues the code is correct *because the tests pass*. The failure step is usually the one that trusts the tests.
- `artifact`:

```json
{
  "language": "python",
  "code": "def median(numbers):\n    ordered = sorted(numbers)\n    return ordered[len(ordered) // 2]",
  "tests": ["assert median([1, 2, 3]) == 2", "assert median([7]) == 7"],
  "test_result": "2 passed, 0 failed"
}
```

- `test_gap`:

```json
{
  "entry_point": "median",
  "signature": "median(numbers)",
  "arity": 1,
  "existing_tests": ["[1, 2, 3]", "[7]"],
  "input_guidance": "One list of numbers, e.g. [1, 2, 3]"
}
```

  - `arity`: the number of arguments (1-4).
  - `existing_tests`: the **arguments** of each shipped test, written the way a student would type them: for one argument just the value (`"[1, 2, 3]"`), for two arguments comma-separated (`"3, 4"`). One entry per test in `artifact.tests`, in the same order.
- `validation_payload`:
  - `entry_point`, `ai_code` (exactly the artifact code), `reference_code` (correct, same name and signature);
  - `test_inputs`: tuple strings as in the main instructions, e.g. `"([1, 2, 3],)"`;
  - `counterexample_input`: one breaking input;
  - `breaking_inputs`: **2-3 tuple strings** that make the two implementations return different results.
- **Both promises are checked by execution:**
  1. every existing test gives the **same** result from both implementations (the suite really is green);
  2. at least one `breaking_inputs` entry gives **different** results (a winning answer exists).
- The gap should be a whole *class* of input the suite never considers (empty input, even length, duplicates, negatives, zero, unicode, boundary values), not an exotic one.
- `hints`: lead the student to read the tests **as a set** and ask which input class is missing.
- `valid_evidence`: use `test_case` or `counterexample` specs.

---

## Examples

<!-- BEGIN GENERATED: advanced-examples (python -m scripts.authoring_prompt) -->
### Example 1: Which AI Is Wrong: verdict b_correct, three solvers

```json
{
  "id": "apt-wg-001",
  "subject": "aptitude",
  "topic": "Time, Speed & Distance",
  "subtopic": "Time, speed and distance",
  "difficulty": "3",
  "challenge_mode": "which_ai_is_wrong",
  "question": "A car covers the first 120 km of a journey at 40 km/h and the next 120 km at 60 km/h. Two AI assistants were asked for the average speed over the whole journey. They disagree. Which of them - if either - is right?",
  "artifact_type": "numeric_solution",
  "artifact": {
    "given": [
      "First leg: 120 km at 40 km/h",
      "Second leg: 120 km at 60 km/h"
    ]
  },
  "ai_claim": "",
  "ai_solution": [],
  "ai_final_answer": "",
  "simulated_confidence": 0,
  "truth_state": "flawed",
  "failure": {
    "category": "F03",
    "location": 3,
    "misconception": "Averaging rates directly instead of weighting them by the time each is sustained",
    "explanation": "A's step 3 asserts that equal distances make the legs contribute equally. They contribute equally to the distance but not to the time, and average speed is a time-weighted quantity. The correct value is the harmonic mean of the two speeds, 2*40*60/(40+60) = 48, which is always below the arithmetic mean unless the speeds are equal.",
    "why_convincing": "A's reasoning sounds like a symmetry argument, and symmetry arguments are usually sound. The equal 120 km legs make 'they count equally' feel like a statement about the problem rather than an assumption about the averaging. A is also the more confident of the two, and 50 is the rounder number."
  },
  "missing_information": "",
  "resolving_scenarios": [],
  "answer_coincidentally_correct": false,
  "competing": [
    {
      "label": "A",
      "persona": "AI Alpha",
      "ai_claim": "The average speed is 50 km/h.",
      "ai_solution": [
        {
          "index": 1,
          "text": "The journey has two legs of equal length, 120 km each.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 2,
          "text": "The speeds on the two legs are 40 km/h and 60 km/h.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 3,
          "text": "Because the two distances are equal, the two legs contribute equally to the journey, so the average speed is the mean of the two speeds.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 4,
          "text": "(40 + 60) / 2 = 50, so the average speed is 50 km/h.",
          "is_first_failure": false,
          "derived_from_failure": false
        }
      ],
      "ai_final_answer": "50",
      "simulated_confidence": 95
    },
    {
      "label": "B",
      "persona": "AI Beta",
      "ai_claim": "The average speed is 48 km/h.",
      "ai_solution": [
        {
          "index": 1,
          "text": "The journey has two legs of equal length, 120 km each, so the total distance is 240 km.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 2,
          "text": "The speeds on the two legs are 40 km/h and 60 km/h.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 3,
          "text": "Average speed is total distance over total time, so the times matter, not the speeds directly: the slower leg takes longer and so counts for more.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 4,
          "text": "First leg: 120/40 = 3 h. Second leg: 120/60 = 2 h. Total time 5 h.",
          "is_first_failure": false,
          "derived_from_failure": false
        },
        {
          "index": 5,
          "text": "240 / 5 = 48, so the average speed is 48 km/h.",
          "is_first_failure": false,
          "derived_from_failure": false
        }
      ],
      "ai_final_answer": "48",
      "simulated_confidence": 71
    }
  ],
  "comparison": {
    "verdict": "b_correct",
    "divergence_step": 3,
    "explanation": "Both agree on the distances and the speeds. They part company at step 3, on what 'average' means. Equal distances do not mean equal weight: the 40 km/h leg takes 3 hours and the 60 km/h leg takes 2, so the slow leg occupies more of the journey and pulls the average below the midpoint. Average speed is always total distance over total time."
  },
  "test_gap": null,
  "canonical_solution": "Total distance = 120 + 120 = 240 km. Time on the first leg = 120/40 = 3 h; on the second = 120/60 = 2 h; total 5 h. Average speed = 240/5 = 48 km/h. Equivalently, for equal distances the average speed is the harmonic mean 2(40)(60)/(40+60) = 48 km/h. The arithmetic mean 50 km/h would only be correct if equal *times* were spent at each speed, not equal distances.",
  "canonical_answer": "48",
  "valid_evidence": [
    {
      "type": "calculation",
      "summary": "Total time is 5 h, so 240/5 = 48 km/h.",
      "must_reference_step": 3,
      "must_contain_values": [
        "48",
        "5"
      ]
    },
    {
      "type": "contradiction",
      "summary": "At 50 km/h the 240 km journey would take 4.8 h, but the two legs take 3 + 2 = 5 h.",
      "must_reference_step": 4,
      "must_contain_values": [
        "4.8"
      ]
    }
  ],
  "counterexamples": [
    "If A were right, 240 km at 50 km/h would take 4.8 h, but the legs demonstrably take 3 h and 2 h.",
    "Push the speeds apart: 120 km at 1 km/h and 120 km at 100 km/h averages 1.98 km/h, nowhere near the mean of 50.5."
  ],
  "hints": [
    {
      "level": 1,
      "kind": "attention",
      "text": "The two solutions agree on every number until one specific claim. Find the step where they stop agreeing."
    },
    {
      "level": 2,
      "kind": "direction",
      "text": "Work out how long each leg actually takes. Are the two legs equal in time?"
    },
    {
      "level": 3,
      "kind": "concept",
      "text": "Average speed is defined as total distance divided by total time. Check each solution against that definition rather than against your intuition."
    },
    {
      "level": 4,
      "kind": "strong",
      "text": "Test A's answer: if the average really were 50 km/h, how long would 240 km take? Compare with 3 + 2 hours."
    },
    {
      "level": 5,
      "kind": "reveal",
      "text": "A's step 3 is the failure: equal distances weight the distance, not the time. The slow leg takes 3 h against 2 h, so the true average is 240/5 = 48 km/h. B is right."
    }
  ],
  "repair": "Replace A's step 3 with a time computation: 120/40 = 3 h and 120/60 = 2 h, total 5 h, so the average speed is 240/5 = 48 km/h.",
  "debrief": "Two assistants, two confident answers, and the more confident one is wrong. Notice what was *not* useful here: the confidence badge, the roundness of the answer, and the length of the explanation. What was useful was a definition - total distance over total time - applied to both solutions independently. When two sources disagree, do not compare them to each other. Compare each to the thing that decides.",
  "transfer_check": {
    "question": "A cyclist rides 60 km at 20 km/h and 60 km at 30 km/h. What is the average speed in km/h?",
    "answer": "24",
    "explanation": "Times are 3 h and 2 h, total 5 h for 120 km: 120/5 = 24 km/h, the harmonic mean of 20 and 30."
  },
  "validation_payload": {
    "solver": "d = 120\nt = Fraction(d, 40) + Fraction(d, 60)\nanswer = Fraction(2 * d, 1) / t\n",
    "solver_a": "answer = Fraction(40 + 60, 2)\n",
    "solver_b": "d = 120\nt = Fraction(d, 40) + Fraction(d, 60)\nanswer = Fraction(2 * d, 1) / t\n"
  }
}
```

### Example 2: Break the Tests: a green suite with an untested input class

```json
{
  "id": "prg-bt-001",
  "subject": "programming",
  "topic": "Debugging & Testing",
  "subtopic": "Test coverage",
  "difficulty": "3",
  "challenge_mode": "break_the_tests",
  "question": "An AI wrote this median function and a test suite for it. Every test passes. Find one input the suite never asks about, on which the function is wrong.",
  "artifact_type": "code",
  "artifact": {
    "language": "python",
    "code": "def median(numbers):\n    ordered = sorted(numbers)\n    return ordered[len(ordered) // 2]",
    "tests": [
      "assert median([1, 2, 3]) == 2",
      "assert median([5, 3, 1]) == 3",
      "assert median([7]) == 7",
      "assert median([9, 2, 8, 1, 4]) == 4"
    ],
    "test_result": "4 passed, 0 failed"
  },
  "ai_claim": "median() is correct. I wrote four tests covering sorted input, unsorted input, a single element and a longer list. All four pass.",
  "ai_solution": [
    {
      "index": 1,
      "text": "Sorting first means the elements are in order, so the middle position is meaningful.",
      "is_first_failure": false,
      "derived_from_failure": false
    },
    {
      "index": 2,
      "text": "Integer division by 2 gives the index of the middle element.",
      "is_first_failure": false,
      "derived_from_failure": false
    },
    {
      "index": 3,
      "text": "The four tests cover sorted, unsorted, single-element and longer inputs, and all four pass.",
      "is_first_failure": false,
      "derived_from_failure": false
    },
    {
      "index": 4,
      "text": "Since every test passes and the tests cover the interesting cases, median() is correct.",
      "is_first_failure": false,
      "derived_from_failure": false
    }
  ],
  "ai_final_answer": "correct",
  "simulated_confidence": 91,
  "truth_state": "flawed",
  "failure": {
    "category": "F09",
    "location": 3,
    "misconception": "Treating a passing test suite as proof of correctness, when the suite shares the author's blind spot",
    "explanation": "Every test list has an odd length. For an even-length list the median is the mean of the two middle values, but this implementation returns the upper of the two. median([1, 2]) returns 2 where the median is 1.5. The tests pass because the same assumption that produced the bug also chose the test cases.",
    "why_convincing": "Four green tests, including an 'edge case' single-element list, reads as thorough coverage. The missing case is not an exotic input - it is half of all possible inputs - which is exactly why nobody notices its absence."
  },
  "missing_information": "",
  "resolving_scenarios": [],
  "answer_coincidentally_correct": false,
  "competing": [],
  "comparison": null,
  "test_gap": {
    "entry_point": "median",
    "signature": "median(numbers)",
    "arity": 1,
    "existing_tests": [
      "[1, 2, 3]",
      "[5, 3, 1]",
      "[7]",
      "[9, 2, 8, 1, 4]"
    ],
    "input_guidance": "One list of numbers, e.g. [1, 2, 3]"
  },
  "canonical_solution": "Every shipped test uses an odd-length list, where the median genuinely is the single middle element. For even-length input the median is the mean of the two middle values. median([1, 2]) returns 2, but the median of [1, 2] is 1.5. The fix is to average the two central elements when the length is even.",
  "canonical_answer": "incorrect for even-length lists",
  "valid_evidence": [
    {
      "type": "test_case",
      "summary": "An even-length list where the function returns the upper middle value instead of the mean.",
      "must_reference_step": 3,
      "must_contain_values": [
        "1.5"
      ]
    },
    {
      "type": "counterexample",
      "summary": "median([1, 2]) returns 2, expected 1.5.",
      "must_reference_step": 3,
      "must_contain_values": [
        "2"
      ]
    }
  ],
  "counterexamples": [
    "median([1, 2]) returns 2, but the median is 1.5.",
    "median([1, 2, 3, 4]) returns 3, but the median is 2.5."
  ],
  "hints": [
    {
      "level": 1,
      "kind": "attention",
      "text": "Look at the four test inputs as a set, not one at a time. What do all four have in common?"
    },
    {
      "level": 2,
      "kind": "direction",
      "text": "Count the elements in each test list. Every count is odd."
    },
    {
      "level": 3,
      "kind": "concept",
      "text": "The definition of the median splits into two cases by parity. Only one of them is exercised."
    },
    {
      "level": 4,
      "kind": "strong",
      "text": "Try a list with exactly two elements and work out by hand what the median should be."
    },
    {
      "level": 5,
      "kind": "reveal",
      "text": "median([1, 2]) returns 2 because len//2 is 1. The median of [1, 2] is (1+2)/2 = 1.5."
    }
  ],
  "repair": "Return ordered[middle] only when the length is odd; when it is even return (ordered[middle - 1] + ordered[middle]) / 2.",
  "debrief": "A test suite written by whoever wrote the code inherits its blind spots. This suite is not weak because it is small - it is weak because all four cases sit on the same side of the one branch that matters. When you review tests, read them as a set and ask which input classes are absent, not whether the listed ones pass.",
  "transfer_check": {
    "question": "What does this implementation return for median([4, 10])?",
    "answer": "10",
    "explanation": "len//2 is 1, so it returns ordered[1] = 10. The median is 7."
  },
  "validation_payload": {
    "entry_point": "median",
    "ai_code": "def median(numbers):\n    ordered = sorted(numbers)\n    return ordered[len(ordered) // 2]\n",
    "reference_code": "def median(numbers):\n    ordered = sorted(numbers)\n    n = len(ordered)\n    middle = n // 2\n    if n % 2 == 1:\n        return ordered[middle]\n    return (ordered[middle - 1] + ordered[middle]) / 2\n",
    "test_inputs": [
      "([1, 2, 3],)",
      "([5, 3, 1],)",
      "([7],)",
      "([9, 2, 8, 1, 4],)",
      "([1, 2],)"
    ],
    "counterexample_input": "([1, 2],)",
    "breaking_inputs": [
      "([1, 2],)",
      "([1, 2, 3, 4],)",
      "([10, 20],)"
    ]
  }
}
```
<!-- END GENERATED: advanced-examples -->
