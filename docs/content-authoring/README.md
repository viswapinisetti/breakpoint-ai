# Writing Breakpoint challenges with ChatGPT

This is the workflow for authoring question content yourself. ChatGPT drafts the challenges, the validator checks them, and you review what only a human can judge.

| File | What it is |
|---|---|
| [CHATGPT_PROMPT.md](CHATGPT_PROMPT.md) | The full instructions for ChatGPT: format, rules, style, every subject and topic, and 5 worked examples. **This is the format specification.** |
| [CHATGPT_PROMPT_ADVANCED_MODES.md](CHATGPT_PROMPT_ADVANCED_MODES.md) | Add-on for the two advanced modes (Which AI Is Wrong, Break the Tests). Use only when you want those. |

---

## 1. The loop

```
pick a topic -> ask ChatGPT for 5 -> save as a .json file -> validate
     -> paste errors back to ChatGPT -> validate again -> review by hand
     -> restart the API -> play it in the app
```

### Step 1: set up ChatGPT (once per chat)

Use a model with reasoning ("thinking"). Arithmetic and code accuracy matter more than speed.

Pick either option:

- **Simplest:** start a new chat and attach `CHATGPT_PROMPT.md` (or paste its entire contents), with this message:
  > Read this file completely. It defines exactly how you write challenges for me. Reply only "Ready" and wait for my first request.
- **Reusable:** create a ChatGPT **Project**, upload `CHATGPT_PROMPT.md` as a project file, and set the project instructions to:
  > You author challenges for NxtWave Breakpoint. Follow the attached CHATGPT_PROMPT.md exactly, every time. Reply only with the JSON block and Reviewer notes it specifies.

  Every chat in the project then starts ready.

For the advanced modes, attach `CHATGPT_PROMPT_ADVANCED_MODES.md` as well.

Start a fresh chat every 3-4 batches. Long chats drift from the rules.

### Step 2: ask for a batch

Copy this, fill it in and send it. The subject key and topic name must match the tables in section 8 of the prompt exactly.

```
Subject: aptitude
Topic: SI & CI
Count: 5
Mix: 3 flawed, 1 valid, 1 insufficient_information
Difficulties: 2, 3, 3, 4, 5
Start ID number: 001
Notes: cover half-yearly compounding and the SI-vs-CI difference over 3 years
```

- **5 per request** gives the best quality. Do not go above 8.
- **Start ID number** continues from the last challenge in that topic (the next batch starts at 006). A reused id is rejected by the validator.
- **Notes** is where you steer: concepts to cover, traps to use, scenarios to avoid repeating, and difficulty intent.
- For an advanced mode, add a line: `Mode: which_ai_is_wrong` or `Mode: break_the_tests`.

### Step 3: save the output

Copy **only the contents of the JSON code block** (from `[` to `]`) into a new file:

```
backend/content/<subject key>/<topic key>-<batch>.json
```

For example, `backend/content/aptitude/si-ci-01.json`. The next batch for that topic goes in `si-ci-02.json`. One file per batch means you never have to merge JSON by hand. Any file name works, since the app loads every `.json` under `backend/content/`, but this scheme keeps things findable.

Save as **UTF-8**. VS Code does this by default.

Keep ChatGPT's **Reviewer notes** in view: they list what you must verify in step 5.

### Step 4: validate and fix

**Every command in this guide runs from the `backend` folder**, where the Python environment (`.venv`) lives. Run from the project root instead and PowerShell reports *"'.\.venv\Scripts\python.exe' is not recognized"*. Open PowerShell and go there first:

```powershell
cd C:\Users\Nxtwave\Documents\Breakpoint_AI\backend
```

Then check your file:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_content content\aptitude\si-ci-01.json
```

- `ok` lines passed. **FAIL** lines will be rejected by the app, and each one says why.
- `warn:` lines will load, but work worse than they should. Aim for zero.
- The exit summary shows the truth-state mix of the file.

If there is any FAIL or warning, paste the output back to ChatGPT:

```
The validator reported these problems. Fix all of them and return the complete corrected JSON array for this batch.

<paste the validator output here>
```

Replace the file contents with the new JSON and run the validator again. Repeat until it is clean; two rounds is typical.

Before restarting the API, run the validator over **everything** once. It also catches an id that collides with another file:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate_content
```

### Step 5: review by hand

The validator checks structure, and **for Aptitude, Mathematics, Data Analytics, Programming and DSA it runs the solvers and code**, so the numbers and the bug are proven. For the other 14 subjects nothing checks whether the content is *true*. You are the only check. Use the checklist in section 3 below, and go through every item in the Reviewer notes.

### Step 6: publish and play

Restart the backend. Content is loaded at startup, and a challenge that fails validation is skipped, not published:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Open the app, go to the subject and topic in the contents rail, and **play one or two challenges as a student**: judge, submit evidence, finish, read the debrief. Five minutes of playing catches what reading misses.

To see coverage across all topics at any time:

```powershell
.\.venv\Scripts\python.exe -m scripts.topics_report
.\.venv\Scripts\python.exe -m scripts.topics_report aptitude
```

---

## 2. Format and style in brief

The full rules are in [CHATGPT_PROMPT.md](CHATGPT_PROMPT.md). These are the ones that matter most when you review.

**A challenge** is a question, plus a confident AI answer (a one-line claim, 3-6 numbered steps and a final answer), plus the private answer key (truth state, failure, correct solution, hints, debrief). The student sees only the first two until they have judged.

**Three truth states, in roughly this mix across a topic:**

| Truth state | Share | What it is |
|---|---|---|
| `flawed` | about 2 in 3 | The AI is wrong, with exactly **one** root mistake at a specific step. |
| `valid` | about 1 in 4 | The AI is **right**, but the solution looks like it might not be. |
| `insufficient_information` | about 1 in 15 | The question cannot be answered. The AI silently invented the missing fact. |

**Style rules to check:**

1. **One root failure** per flawed challenge. Steps before it are correct; steps after may carry the wrong value but must not add a second mistake.
2. **The mistake is plausible and real.** It is one a good student or a fluent AI actually makes. No invented rules, functions or statistics.
3. **Nothing gives the verdict away.** The question, artifact, AI claim, steps, subtopic title and confidence look the same whether the AI is right or wrong. The confidence is always 88-97.
4. **Hints climb a ladder.** Level 1 says what kind of thing to check; level 2 where; level 3 which principle; level 4 what to recompute; level 5 reveals everything. Levels 1-4 never state the answer.
5. **The debrief teaches a habit**, not only the answer: why the mistake was convincing, and what to do next time (e.g. "trace every number back to the question").
6. **Answers are bare values**: `960`, not `Rs 960`; `yes`/`no` or `correct`/`incorrect` for review questions.
7. **Topics are chosen by subject matter, never by verdict.** Don't put all the "insufficient information" items under a "Data Sufficiency" topic; the topic would give the answer away.
8. **Indian context** (Rs, Indian names, local businesses) where natural, but never needed to solve the problem.
9. **Original material only.** For reading-comprehension passages and code, have ChatGPT write original text. Don't paste copyrighted passages.

---

## 3. Review checklist: what only you can check

For every challenge, before publishing:

- [ ] **Solve it yourself first**, before reading the AI's steps. Do you reach the canonical answer?
- [ ] **Flawed:** is the mistake findable from what the student sees, with no outside knowledge? Is there exactly one? Would a strong student agree it is wrong once shown?
- [ ] **Valid:** is it *genuinely* correct? A wrong "valid" item teaches students to approve bad work, which is the worst defect this product can have.
- [ ] **Insufficient:** is it truly undecidable, and not just badly worded? Do both resolving scenarios fit every stated fact?
- [ ] **Facts (non-computed subjects):** is every technical claim accurate for the version or setting stated? When in doubt, check the official documentation, or ask ChatGPT to "cite the documentation for claim X" and verify the citation yourself.
- [ ] **No leaks:** the question, artifact, subtopic and claim don't hint at the verdict. Hints 1-4 don't state the answer.
- [ ] **Consistency:** the reveal hint, repair, canonical solution, counterexamples and transfer check all tell the same story with the same numbers.
- [ ] **Played it** in the app at least once per batch.

---

## 4. Validator messages you will see

| Message | Meaning | Fix |
|---|---|---|
| `invalid JSON at line N, column M` | ChatGPT's JSON is malformed, or the copy included text outside the block. | Re-copy only `[ ... ]`, or ask ChatGPT to return valid JSON. |
| `topic_registered: Topic '...' is not registered ... Did you mean '...'?` | The topic name is misspelled. | Use the exact name suggested. |
| `id is used 2 times` | The id collides with another challenge. | Continue numbering from the last used id. |
| `canonical_solver: Solver computed 'X' but canonical_answer is 'Y'` | The correct answer and the solver disagree. One of them is wrong. | Work out which is right; ask ChatGPT to fix the other. |
| `flawed_solver: Intended misconception yields 'X' but the AI claims 'Y'` | The AI's wrong answer does not follow from its stated mistake. There is a second, accidental error. | Ask ChatGPT to make the steps, the flawed solver and `ai_final_answer` agree. |
| `failure_is_material: Flawed and canonical paths agree` | The "mistake" does not change the answer, so there is nothing to find. | Pick a different mistake, or mark it `answer_coincidentally_correct` if that is the intent. |
| `failure_location: ... is not among the reasoning steps` | `failure.location` points at a step that doesn't exist. | Point it at the step where the error first appears. |
| `failure_is_reproducible: The AI's code agrees with the reference on every test input` | The claimed bug is never triggered by the test inputs. | Add a test input that exposes it. |
| `correct_artifact: ... does not match` | A "valid" challenge isn't actually valid. | Fix the answer, or the truth state. |
| `insufficient_information: Needs at least two resolving scenarios` | The undecidability is asserted, not shown. | Add two readings that give different answers. |
| `... - schema` / `Field required` | A required field is missing or has the wrong type. | Ask ChatGPT to include every field from section 4. |
| `warn: hints should be exactly 5 ...` | The hint ladder is malformed. | Five hints, kinds in order, ending with `reveal`. |
| `warn: valid_evidence types [...] cannot be submitted` | The evidence spec uses a card type students don't have in this subject. | Use one of the subject's evidence types (section 8). |
| `warn: numeric answer, but no valid_evidence entry has a number` | Student evidence can't be auto-accepted offline. | Put the key numbers in `must_contain_values`. |
| `warn: transfer_check answer '...' is text` | Students must type the answer exactly, case-sensitive. | Prefer a numeric answer. |

---

## 5. Generating many topics at once

Doing every topic by hand means about 200 ChatGPT requests. There are two faster ways, both driven by `scripts.bulk_author`. Both use the same prompt and checks as the manual loop, and both assign ids and file names for you.

### Option A: fully automatic, through the API (needs a paid API key)

The ChatGPT **website** cannot be automated. The same kind of model can be, through an **API key**, which is billed per use and is separate from a ChatGPT subscription. The script then requests every missing topic, validates each batch, sends the errors back to the model to fix (up to 2 rounds), and writes the passing challenges into `backend/content/`.

1. **Get a key and put it in `backend/.env`** (this file is never shared or committed). One OpenRouter key reaches both GPT and Claude models:

   ```ini
   BREAKPOINT_OPENROUTER_API_KEY=sk-or-v1-...
   ```

   Check it works:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.check_provider
   ```

2. **See the plan and cost first.** This makes no calls and costs nothing:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.bulk_author --dry-run
   ```

   It shows how many challenges each subject will get, the model, the estimated tokens, and the cost at OpenRouter's current price for that model. To use a different model (e.g. a GPT model), list the real ids and pass one with `--model`:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.check_provider --list openai/
   .\.venv\Scripts\python.exe -m scripts.bulk_author --dry-run --model openai/<model-id>
   ```

3. **Try a small run and read the results** before spending on everything:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.bulk_author --subject english --max-batches 3
   ```

4. **Run everything.** It takes a few hours, with 3 topics in parallel:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.bulk_author
   ```

   You can stop it at any time with Ctrl+C. Running the same command again continues where it stopped, because it only requests what is still missing.

5. **Review and publish.**
   - Every run writes a review file, `backend\content_review\<date-time>.md`, listing each new challenge with the model's Reviewer notes and any warnings. Work through it with the checklist in section 3.
   - Challenges that still failed after the fix rounds are in `backend\content_rejected\`, each with its errors, and are **not** published.
   - Then run `.\.venv\Scripts\python.exe -m scripts.validate_content` and restart the API.

Useful options:

| Option | Default | Meaning |
|---|---|---|
| `--subject aptitude` | all | Only this subject. |
| `--topic "SI & CI"` | all | Only this topic (needs `--subject`). |
| `--per-topic 10` | 5 | Target number of challenges per topic. Raise it later to grow the catalog. |
| `--max-batches 20` | none | Stop after this many requests: a spending cap. |
| `--workers 3` | 3 | Topics generated at the same time. |
| `--model <id>` | from `.env` | Which model to use. |

The mix of answer types is planned across the whole catalog, so it lands on about 68% flawed, 26% valid and 6% insufficient overall. Each request also tells the model which subtopics already exist in that topic, so it doesn't repeat them.

### Option B: keep using the ChatGPT website, and let the script do the filing (free)

This saves the saving, naming, numbering and validating, but you still send the requests yourself.

1. In one ChatGPT chat, send requests for several topics one after another. The "Start ID number" line no longer matters, because the script assigns ids.
2. Copy each **whole reply** (JSON block plus Reviewer notes) and paste them one after another into a single text file, e.g. `C:\Users\Nxtwave\Documents\replies.txt`.
3. Import them all at once:

   ```powershell
   .\.venv\Scripts\python.exe -m scripts.bulk_author --import C:\Users\Nxtwave\Documents\replies.txt
   ```

   Each challenge is filed under its subject and topic (`backend\content\<subject>\<topic-key>-NN.json`) and validated. The same review file is written.
4. Anything rejected is in `backend\content_rejected\` with its errors. Paste those errors into ChatGPT, put the corrected reply into a new text file, and import that.
5. Empty `replies.txt` afterwards. Importing the same reply twice is refused as a duplicate question, so nothing is published twice.

---

## 6. Keeping the prompt in sync

Sections 8-10 of the prompt (subjects, topics, allowed values and examples) are generated from the code. After any change to the topic registry or the subject catalog, refresh them:

```powershell
.\.venv\Scripts\python.exe -m scripts.authoring_prompt
```

Then re-upload `CHATGPT_PROMPT.md` to your ChatGPT Project. Everything outside those three sections is hand-written; edit it freely.
