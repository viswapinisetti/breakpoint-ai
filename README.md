# NxtWave Breakpoint — AI Failure Lab

> **AI says it's right. Prove it.**

A cross-subject AI investigation environment where students learn by finding
hidden failures in plausible AI-generated solutions, defending their judgment
with evidence, and understanding why the reasoning was deceptive.

**Status:** Aptitude past its 60-challenge target at 80, four challenge modes
live (Trust-or-Challenge, Find-the-Failure, Break-the-Tests, Which-AI-Is-Wrong),
process-isolated execution, and the Challenge Studio for content teams. All 19
subject families are configured and served.

---

## Quick start

Two terminals.

```bash
# 1. Backend
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

```bash
# 2. Frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

### If Windows blocks the frontend toolchain

`npm run dev` and `npm run build` work normally on Windows. Skip this section
unless you actually hit the error below.

On a machine with **Smart App Control** on, Windows may block Vite's unsigned
build binary (`@rolldown/binding-win32-x64-msvc`), and both `npm run dev` and
`npm run build` then fail with *"An Application Control policy has blocked this
file"*. Smart App Control cannot allow single files, and turning it off is
permanent, so build in Linux instead - through WSL, or through Docker Desktop,
which runs on WSL 2:

```bash
# from frontend/, with Docker Desktop running - build into dist/
docker run --rm -v "$PWD:/app" -w /app node:24-slim   sh -lc "npm ci && npm run build"

# or run the dev server there, with the API still on the Windows host
docker run --rm -it -p 5173:5173 -v "$PWD:/app" -w /app   -e BREAKPOINT_API_PROXY=http://host.docker.internal:8000 node:24-slim   sh -lc "npm ci && npm run dev -- --host"
```

`node_modules` is platform-specific, so a tree installed on Windows will not
work in the container and vice versa - `npm ci` inside the container replaces
it. The backend is unaffected and still runs on Windows.

The app runs with **no API key**. Challenges, judging, hints, failure replay,
scoring, streaks and stats all work offline against pre-generated content, and
strong evidence is accepted by a deterministic pre-check — so the core loop is
fully demonstrable offline.

Generation, evidence evaluation, AI Debate and the live debrief need a
provider. Put **one** key in `backend/.env`:

```ini
BREAKPOINT_OPENROUTER_API_KEY=sk-or-v1-...   # one key, many vendors
# or
ANTHROPIC_API_KEY=sk-ant-...                 # native Messages API
```

Then verify before spending anything:

```bash
cd backend && ./.venv/Scripts/python.exe -m scripts.check_provider
```

It checks credentials, models, a text call, and — the one that matters —
that structured output round-trips into a validated contract.

---

## AI provider (§73)

The gateway in `app/agents/client.py` is the only place model calls happen.
Agents ask for a **role** (`generation`, `critic`, `debate`, `evidence`) and
the gateway resolves provider and model from settings, so switching vendors is
configuration, not code.

| Provider | When to use | Notes |
|---|---|---|
| **OpenRouter** | You have one key and want many vendors | OpenAI-compatible API. Structured output requested as strict `json_schema`, degrading to `json_object` then prompt-guided JSON, since support varies by model |
| **Anthropic** | You have an Anthropic key | Native Messages API. Adds adaptive thinking, prompt-cache breakpoints and server-side refusal fallbacks |

`BREAKPOINT_AI_PROVIDER=auto` (the default) picks OpenRouter if its key is set,
otherwise Anthropic.

**Worth knowing:** routing a Claude model *through* OpenRouter gives you the
model but not the Anthropic-native controls — adaptive thinking, refusal
fallbacks and explicit cache breakpoints are Messages API features that do not
cross the OpenAI-compatible surface. `effort` is mapped onto OpenRouter's
`reasoning.effort`, which it forwards to models that support it. For Breakpoint
this costs a little quality headroom on generation and loses the refusal-rescue
path, neither of which blocks the product.

Default routing puts the strongest model where the quality bar is (generation,
critique) and a cheaper one where call volume is (debate, evidence):

```ini
BREAKPOINT_OPENROUTER_GENERATION_MODEL=anthropic/claude-opus-5
BREAKPOINT_OPENROUTER_CRITIC_MODEL=anthropic/claude-opus-5
BREAKPOINT_OPENROUTER_DEBATE_MODEL=anthropic/claude-sonnet-5
BREAKPOINT_OPENROUTER_EVIDENCE_MODEL=anthropic/claude-sonnet-5
```

Browse real options (no key needed):

```bash
./.venv/Scripts/python.exe -m scripts.check_provider --list anthropic/
./.venv/Scripts/python.exe -m scripts.check_provider --list          # all 431
```

---

## Identity: three modes, one contract

`BREAKPOINT_AUTH_MODE` selects who owns identity. Every mode resolves to the
same `User`, so no router, screen or metric knows which is in use.

| Mode | Credential | Use |
|---|---|---|
| `header` (default) | `X-Student-Id` | Local development and the demo — one click, no sign-in |
| `accounts` | Session cookie from email/password or Google | Breakpoint owns identity |
| `oidc` | Bearer token from NxtWave's provider | Inside the NxtWave platform |

### Accounts mode

```bash
cd backend
BREAKPOINT_AUTH_MODE=accounts ./.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

The app then shows a sign-in screen and `X-Student-Id` buys nothing — it fails
closed, like SSO does. What holds it up:

- **Passwords** are scrypt from the standard library (`app/auth/passwords.py`),
  not bcrypt or argon2: both ship native wheels, and one machine here has
  Windows Application Control blocking unsigned native binaries. Cost
  parameters travel inside each hash, so raising them later re-hashes on next
  sign-in instead of locking anyone out.
- **The policy is length-first** (NIST SP 800-63B): at least 10 characters, no
  composition rules, and a refusal for well-known passwords or ones built from
  the student's own address.
- **Sessions are opaque tokens**, stored only as a SHA-256 hash, in an
  httpOnly `SameSite=Lax` cookie. Opaque rather than a JWT so that signing out
  actually revokes. Set `BREAKPOINT_SESSION_COOKIE_SECURE=true` on https.
- **Sign-in does not leak who has an account**: a wrong address and a wrong
  password give the same message and do the same work, and repeated failures
  against one address pause it.

### Google sign-in

Create an OAuth client in a Google Cloud project, add the redirect URI, then:

```ini
BREAKPOINT_GOOGLE_CLIENT_ID=....apps.googleusercontent.com
BREAKPOINT_GOOGLE_CLIENT_SECRET=...
BREAKPOINT_GOOGLE_REDIRECT_URI=http://localhost:5173/api/auth/google/callback
```

Until all three exist the button is absent and the sign-in screen says which
settings are missing. The flow is authorization code with PKCE; state, nonce
and verifier live in the database and are consumed on first use, so a replayed
callback is refused. The ID token's issuer, audience, nonce and expiry are all
checked. A Google sign-in whose *verified* address matches an existing
password account joins that account rather than creating a second one.

`GET /api/auth/status` reports the mode and anything missing, and
`python -m scripts.accounts_test` exercises the whole thing offline, stubbing
Google's token endpoint so every claim check runs against deliberately good
and deliberately bad tokens.

---

## The architecture decision that matters

The engine contains **no subject-specific logic**. Everything routes through
five universal objects (PRD §8):

```
CONCEPT → ARTIFACT → HIDDEN FAILURE → EVIDENCE → VERIFICATION → REPAIR → DEBRIEF
```

A subject is a **row of data** in `app/subjects/catalog.py` plus, optionally, a
validator. That is why all 19 subjects work today against one engine — adding
DevOps or MLOps content requires no engine change.

### Topic registry

`app/subjects/topics.py` is the curriculum: all 19 subjects in order, and
each subject's student-facing topics in order (212 topics). It is the single
source for subject names, subject order and topic lists — `catalog.py` reads
them from it.

- A challenge names its topic exactly as registered (`"topic": "SI & CI"`).
  `governance.validate` runs a `topic_registered` check first, so a challenge
  under an unregistered topic fails validation, cannot be published, and is
  refused by the content seeder and by Studio generation (with a "did you
  mean" suggestion).
- `/api/subjects` returns every registered topic with its published count,
  including topics with no content yet, and the contents rail and subject page
  render all of them as numbered children under their subject.
- Adding, renaming or reordering a topic is an edit to that one file.
  `python -m scripts.validate_content` then lists any challenge still naming
  an old topic.

```
backend/app/
  engine/          subject-independent core
    contracts.py     Challenge, Failure, Evidence, agent response schemas (§49, §74)
    taxonomy.py      F01–F16 universal failure taxonomy (§51)
    scoring.py       Breakpoint Score, verification skills, False Alarm (§52–54)
    registry.py      adapter resolution (§50)
  subjects/
    topics.py        topic registry: subjects and their ordered topics
    catalog.py       all 19 subject families — pure data (§9–27)
    aptitude.py      Tier A: deterministic validator (§48)
    base.py          the six-method adapter contract (§50)
  agents/          agent roles (§45, §46)
    client.py        the AI Gateway - every model call goes through here (§73)
    providers/       openrouter (OpenAI-compatible) + anthropic (native)
  pipeline.py      the quality funnel (§47)
  routers/         student-facing API
```

### Content coverage

**Every registered topic has a playable pack** — AC-01's coverage gate, and
then some. 1,080 challenges, truth mix 68% flawed / 26% valid / 6%
insufficient against a v0.2 §3.2 target of 68/26/5. All 212 topics across the
19 subjects have at least five challenges each. Per-topic coverage and truth
mix:

```bash
cd backend && ./.venv/Scripts/python.exe -m scripts.topics_report            # all subjects
cd backend && ./.venv/Scripts/python.exe -m scripts.topics_report aptitude   # one subject
```

Topics are assigned by subject matter, never by truth state. In particular,
insufficient-information challenges are not gathered under *Data Sufficiency*:
a topic that predicted the verdict would leak the answer before the student
judges.

**Coverage is by topic, not by mode or difficulty.** Two caveats a content
plan has to account for:

- **Mode mix is lopsided.** 1,075 of the 1,080 are Trust-or-Challenge; Mode F
  has 2 and Mode G has 3. Both engines are complete and tested, but a student
  working through a subject will effectively only meet Mode B.
- **Validation depth varies.** 236 challenges are machine-verified (150 by
  canonical solver, 86 by code execution); the remaining 770 are Tier B,
  curated and human-reviewed with no deterministic validator. The
  flawed-solver reproduction check in §75 — the one that separates a
  controlled failure from a hallucination — only runs on the Tier A subset.
- **No difficulty-1 content.** The floor is 2, and 65% of the inventory sits
  at 3–4, so there is no gentle on-ramp for a first session.

### Challenge modes

| Mode | What the student does | Decided by |
|---|---|---|
| **B** Trust or Challenge | Approve, challenge, or say the information is insufficient | authored truth state |
| **A** Find the Failure | Locate the first failing step | authored failure location |
| **F** Break the Tests | Supply a test input the shipped green suite never covers | **execution** — the input must make the shipped and reference implementations disagree |
| **G** Which AI Is Wrong | Adjudicate two rival solutions: A, B, both, neither, or undecidable | authored comparison verdict, with each rival's answer computed by its own solver |

Mode F is the only mode whose success criterion is not authored at all. The
student's input is run against both implementations and the verdict is the
disagreement, or its absence. Nothing about it consults a model.

Mode G deliberately offers five verdicts rather than two. Forcing a choice
between A and B would teach that one of two confident answers must be right,
which is the misconception the mode exists to break — so `apt-wg-002` is
undecidable and `apt-wg-003` has both rivals wrong.

| Validation | Subjects |
|---|---|
| **Tier A** — answers computed, not asserted | Aptitude, Mathematics, Data Analytics (solvers executed); Programming, DSA (code executed against test inputs) |
| **Tier B** — curated, reviewed | the other 14 |

The artifact types are deliberately unalike — arithmetic, Python, SQL, a
Kubernetes manifest, a CI pipeline, an English sentence, a chart with a
truncated axis, a confusion matrix, a tensor shape, a monitoring config — and
every one runs through the identical investigate → judge → evidence → outcome →
debrief flow. That is the cross-domain claim in v0.2 §1, demonstrable rather
than asserted.

Per v0.2 §3.3 each non-Aptitude pack is two flawed artifacts plus one genuinely
valid one that requires justification, so no subject teaches that everything is
wrong.

### Why Aptitude is the reference implementation

Because its correctness is **computable**. Every Aptitude challenge carries
executable solver code, and a challenge only publishes if:

1. the canonical solver runs and reproduces the stated correct answer;
2. the *flawed* solver runs and reproduces the AI's wrong answer;
3. the two disagree — otherwise there is no detectable failure;
4. the declared first-failure step actually exists in the reasoning.

Check 2 is the one that matters most. It separates a **controlled educational
failure** from an **accidental model hallucination** (§75). If the misconception
doesn't land on the number the AI claims, the artifact is broken some other way
and is rejected.

Solvers execute with no builtins, no imports and no I/O.

**Programming works the same way** (§96). Each challenge carries the AI's code
and a reference implementation; the validator runs both across a set of inputs
and requires that a flawed challenge actually disagrees somewhere. The
mutable-default challenge, for instance, is confirmed by execution: the AI's
code returns `['a','b']` on a second call where the reference returns `['b']`.
A claimed bug that no input exposes is rejected as unfair.

```bash
cd backend && ./.venv/Scripts/python.exe -m scripts.validate_content
```

```
ok   apt-pct-001      [flawed ] canonical_solver, flawed_solver, failure_location
ok   apt-net-008      [flawed ] canonical_solver, reasoning_only_failure, failure_location
ok   apt-mark-009     [correct] canonical_solver, correct_artifact, failure_location
...
1080 challenges by truth state:
  flawed                     733  (68%)
  valid                      278  (26%)
  insufficient_information    69  (6%)
all challenges passed deterministic validation
```

---

## What is built

| Area | Status |
|---|---|
| Universal engine, 19 subject adapters | ✅ |
| Aptitude deterministic validator | ✅ |
| Dashboard, hero, evidence stats, streak, history | ✅ (§34–36) |
| Challenge player, step selection, Trust-or-Challenge | ✅ (§29 Mode B, §37) |
| Evidence Board, 8 card types, 6-dimension scoring | ✅ (§31, §32) |
| Progressive 5-level hint ladder | ✅ (§40) |
| AI Debate, bounded turns, evidence-gated concession | ✅ (§30, §46.8) |
| Repair | ✅ (§29 Mode D) |
| Failure Replay, Counterfactual, Autopsy | ✅ (§41–44) |
| Breakpoint Score, verification skills, False Alarm | ✅ (§52–54) |
| Achievements, streak | ✅ (§60, §61) |
| Generation pipeline + quality funnel | ✅ (§47, §76) |
| Content: 1,080 challenges, every registered topic playable | ✅ (AC-01 gate met) |
| **Aptitude past its 60-challenge target** (80) | ✅ (v0.2 §3.2) |
| **Mode F** Break the Tests, decided by execution | ⚠️ engine ✅, content thin — 2 challenges (v0.2 §4.2, P1) |
| **Mode G** Which AI Is Wrong, five verdicts | ⚠️ engine ✅, content thin — 3 challenges (v0.2 §4.2, P1) |
| **Process-isolated execution** with import allowlist + timeout | ✅ (v0.2 §12.6) |
| **OIDC identity adapter**, fail-closed | ⚠️ built, unwired — see below |
| Executable validators: 5 subjects | ✅ (v0.2 §12.4) |
| Investigation tools: scratchpad, calculator, formulas | ✅ (§37, §39) |
| Alembic migrations + schema-drift guard | ✅ |
| Mobile tab layout | ✅ (§38) |
| Accessibility: keyboard, ARIA, non-colour-only state | ✅ (§107) |
| **Challenge Studio**: generate, review, edit, publish | ✅ (§11.1) |
| Content lifecycle + audit history | ✅ (§11.2) |
| Challenge templates | ✅ |
| Student report triage | ✅ |
| Challenge analytics | ✅ (§15.2) |
| **Three truth states** flawed / valid / insufficient | ✅ (v0.2 §4.1) |
| **Investigation Score** 20/35/25/20 out of 100 | ✅ (v0.2 §10.1) |
| **Typed evidence cards**, 1–5 per immutable submission | ✅ (v0.2 §6.4) |
| Validation hierarchy: structure → deterministic → rubric | ✅ (v0.2 §9.1) |
| Restricted arithmetic parser (exact rationals, no eval) | ✅ (v0.2 §9.1) |
| Idempotent submissions | ✅ (v0.2 §13.3) |
| Appeals + staff review queue | ✅ (v0.2 §9.4, §11.2) |
| Transfer check after debrief | ✅ (v0.2 §5.2, §8.3) |
| Three-way judgment matrix, small-sample suppression | ✅ (v0.2 §15.1) |
| **Confidence calibration**: certainty asked before each verdict | ✅ |
| **Accounts**: email/password sign-up, Google sign-in, sessions | ✅ |

**Not yet built**, and the honest reasons why:

- **Google sign-in needs a Google Cloud client**, which is an account
  credential rather than code. Everything else about accounts mode is built
  and tested; the button appears the moment the two values exist.

- **NxtWave SSO is built but not wired, and cannot be finished here.**
  `app/auth/oidc.py` does real verification — discovery document, JWKS with
  rotation, signature, issuer, audience, expiry — and `app/deps.py` resolves
  both modes to one `Identity`, so no router knows which is in use. Three
  values are missing and cannot be guessed: `BREAKPOINT_OIDC_ISSUER`,
  `BREAKPOINT_OIDC_AUDIENCE` and `BREAKPOINT_OIDC_SUBJECT_CLAIM`. v0.2 §12.5
  forbids claiming a working integration without credentials and an API
  contract, so the app runs in header mode until they are supplied and
  `/api/health` reports exactly which are absent.

  `python -m scripts.auth_check` verifies what *can* be verified without a
  provider — the claim-mapping contract and the fail-closed guard — and says
  plainly that SSO itself is unverified. Enabling OIDC without configuration
  returns 503 on every request rather than falling back to the header: SSO
  that silently accepts an unverified header is worse than SSO that is
  visibly down.

  There is no safe default for the subject claim. Providers use `sub`,
  `preferred_username` or a tenant-specific id, and guessing wrong merges or
  duplicates student accounts.

- **Sandboxed student-facing tools** — the container, request and model
  tools (DevOps, API, AI subjects). Two sets are done, both running entirely
  in the student's browser, so nothing executes on the server:
  - *Databases* — SQL Editor, Schema Viewer, Query Executor — run PGlite, the
    real PostgreSQL compiled to WebAssembly, loaded with the investigation's
    tables (`frontend/src/lib/sql/`).
  - *Code* — Editor, Terminal, Test Runner, Debugger — run Python on Pyodide
    (real CPython, with a line-by-line tracer for the debugger) and plain
    JavaScript in a worker (`frontend/src/lib/code/`; the Python side is
    `harness.py`, tested under CPython by `harness_test.py`). JSX, TypeScript,
    CSS, HTML, bash and C say plainly that they cannot run.

  Both live in Web Workers: a statement or loop running past 5 seconds is
  stopped by terminating the worker. Test them with
  `node src/lib/sql/prepare.test.mjs`, `node src/lib/code/plan.test.mjs` and
  `python src/lib/code/harness_test.py` from `frontend/`.

  For the server side, `app/engine/sandbox.py` now provides the isolation layer these need, and
  Break-the-Tests already runs on it. What it guarantees: a fresh `python -I -S`
  child per run, wall-clock timeout with process termination, an import
  allowlist, restricted builtins, no inherited environment, and an empty
  working directory. What it does **not** guarantee: it is not a security
  boundary against a determined attacker, and **memory is bounded only on
  POSIX** — Windows has no `setrlimit`, so there the timeout is the only
  backstop. That is acceptable for Mode F, where student input reaches the
  sandbox as `ast.literal_eval`-parsed *data* and never as code. A tool that
  executes arbitrary student **code** needs a container or a jailed worker
  first, so per v0.2 §12.4 those tools stay hidden with the reason shown
  beneath the tools panel rather than presented as functional.

---

## Challenge Studio

Open the **Studio** tab. It is the content developer's workspace (§56):

| Tab | What it does |
|---|---|
| **Generate** | Describe subject / topic / concept / difficulty / failure type, or apply a saved template, and queue a run |
| **Review Queue** | Everything awaiting a human decision, with validator results and the student preview |
| **Published** | Live content, with the same review pane for flagging or retiring |
| **Reports** | Student reports awaiting triage (§109) |
| **Analytics** | Detection rate, completion, hint usage and token spend per challenge (§80) |

The review pane shows the **student view** next to the full solution, because
the question a reviewer is really answering is *"is this fair and findable from
what the student actually sees?"*

Two governance rules are enforced in the backend, not the UI, so every caller
gets them:

1. **A challenge cannot be published unless it currently validates.** Approval
   is a human judgment layered on a machine check, never a replacement for one.
2. **An edit that breaks the solver un-publishes the challenge.** It disappears
   from the student catalog immediately and cannot be re-published until fixed.

Every transition and edit appends to an audit trail: who, when, what changed and
why. Note the two distinct numbers — `seq` is the audit position (incremented by
status changes *and* edits), `body_version` is the version of the challenge body
(only changes when the body does).

### Authoring content by hand (with ChatGPT)

[docs/content-authoring/](docs/content-authoring/README.md) is the guide for
writing challenges yourself: the file format, style rules, the
validate-and-fix loop, a review checklist, and a complete prompt for ChatGPT.
The prompt's subject, topic and example sections are generated from the code
(`python -m scripts.authoring_prompt`), so it never names a topic or field the
validator would reject. Check a draft file with:

```bash
cd backend && ./.venv/Scripts/python.exe -m scripts.validate_content content/aptitude/si-ci-01.json
```

### Content generation

Challenges are **pre-generated offline and human-reviewed**, never generated in
the student request path (§47, §106). This is what keeps latency and cost down
and gives content teams control. The CLI below and the Studio's Generate tab run
the same pipeline.

```bash
cd backend
./.venv/Scripts/python.exe -m scripts.generate \
    --topic "Ratio, Proportion & Mixtures" \
    --concept "Ratio and proportion" \
    --difficulty 3 --count 5

# false-failure challenges, where the AI is genuinely correct
./.venv/Scripts/python.exe -m scripts.generate --concept "Averages" --correct --count 2
```

Each candidate passes through eight gates and reports its funnel honestly:

```
GENERATE → SOLVE INDEPENDENTLY → INJECT FAILURE → CRITIQUE
 → DETERMINISTIC CHECK → SECOND VALIDATION → DIFFICULTY CHECK
 → QUALITY FILTER → PUBLISH
```

Rejection reasons are printed per candidate, so a content developer can see
*why* the funnel narrowed. The critic sees only the student view — if it cannot
find the planted failure, the challenge is unfair and is rejected; if it finds a
*second* error, the artifact is broken and is rejected.

Use `--dry-run` to see the model-call count before spending anything.

---

## Testing

```bash
cd backend
./.venv/Scripts/python.exe -m scripts.validate_content   # content integrity (incl. topic registry)
./.venv/Scripts/python.exe -m scripts.topics_report      # topic coverage report
./.venv/Scripts/python.exe -m scripts.e2e_test           # student loop
./.venv/Scripts/python.exe -m scripts.modes_test         # modes F and G
./.venv/Scripts/python.exe -m scripts.admin_test         # Studio + governance
./.venv/Scripts/python.exe -m scripts.review_test        # appeals + review queue
./.venv/Scripts/python.exe -m scripts.auth_check         # identity config + claim contract
./.venv/Scripts/python.exe -m scripts.calibration_test   # confidence calibration maths
./.venv/Scripts/python.exe -m scripts.accounts_test      # sign-up, sessions, Google (offline)
./.venv/Scripts/python.exe -m scripts.check_provider     # live provider check (needs a key)
```

```bash
cd frontend
node src/lib/calc.test.mjs                               # calculator parser
node src/lib/sql/prepare.test.mjs                        # SQL sandbox preparation
node src/lib/code/plan.test.mjs                          # code tools: what runs where
../backend/.venv/Scripts/python.exe src/lib/code/harness_test.py   # Python code tools
```

Only `check_provider` needs a key.

The e2e suite's most important assertion is the **leak check**: it verifies the
student payload contains no `contains_failure`, `failure`, `canonical_answer`,
`hints`, `repair`, `debrief` or solver code. Leaking any of those turns an
investigation into a reading exercise.

---

## Evidence and evaluation (v0.2 §6.4, §9.1–9.2)

An evidence card is **structured, not a paragraph** — that is what makes it
checkable. Fields differ by type: a Calculation asks for an expression, a value
and a unit; a Counterexample asks for an input and two differing outcomes.
Every card also carries *"Why this supports my judgment"*, because a checked
calculation is not on its own an argument.

Submissions are **immutable revisions** of 1–5 cards, keyed by an idempotency
token so a retried request cannot create a second revision.

The validation hierarchy runs in order:

| Stage | What it does | Where |
|---|---|---|
| 1. Structure | Schema, required fields per type, step references | `engine/evidence.py` |
| 2. Deterministic | Exact arithmetic, distinct references, differing outcomes | `engine/arithmetic.py` |
| 3–4. Relevance + rubric | Does this evidence support *this* judgment | runtime evaluator |
| 5. Review | Uncertainty and evaluator outage park for a human | review queue |

Two rules are enforced in code, not left to the model:

- **Deterministic failure is final.** Arithmetic that does not check out is
  rejected before any model call. A fluent explanation cannot override it.
- **Deterministic success is not sufficient.** `checks_passed` and `accepted`
  are separate fields, and the UI shows them as two separate statements —
  "Checks passed" is not "Evidence supports your claim".

The arithmetic parser is hand-written over `Fraction`: no `eval`, exact
rationals (so `(1/2)/(1/15)` is exactly 7.5), and anything outside the
allowlist is rejected rather than interpreted.

## Database migrations

Schema is owned by Alembic.

```bash
cd backend
./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "what changed"
./.venv/Scripts/python.exe -m alembic upgrade head
```

Startup handles three cases so a stale database never fails mid-request:

| Database state | Behaviour |
|---|---|
| Brand new | Built from the models and stamped at head |
| Pre-migrations, schema matches | Adopted and stamped |
| Pre-migrations, schema behind | Refused, naming the missing columns |
| Migrations pending | Upgraded to head automatically |

`render_as_batch` is on because SQLite cannot alter columns in place.

## Configuration

`backend/.env`, all keys prefixed `BREAKPOINT_`:

| Setting | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `auto` | `auto` \| `openrouter` \| `anthropic` |
| `OPENROUTER_API_KEY` | *(empty)* | OpenRouter credential |
| `OPENROUTER_*_MODEL` | see above | Per-role model routing for OpenRouter |
| `GENERATION_MODEL` | `claude-opus-5` | Composer / injector (Anthropic) |
| `CRITIC_MODEL` | `claude-opus-5` | Critic and quality filter (Anthropic) |
| `DEBATE_MODEL` | `claude-opus-5` | Debate agent (Anthropic) |
| `EVIDENCE_MODEL` | `claude-opus-5` | Evidence evaluator (Anthropic) |
| `QUALITY_THRESHOLD` | `7.0` | Mean score below which nothing publishes |
| `MAX_AMBIGUITY` | `0.35` | Critic ambiguity ceiling |
| `VALID_ARTIFACT_RATIO` | `30/114` (≈26%) | Share of challenges where the AI is right |
| `INSUFFICIENT_INFORMATION_RATIO` | `6/114` (≈5%) | Share that cannot be judged from what is shown |
| `MAX_DEBATE_TURNS` | `3` | Bounded debate (v0.2 §9.3) |
| `ADMIN_TOKEN` | *(empty)* | Studio access. Empty = open (dev). Set it and `X-Admin-Token` becomes mandatory |
| `MAX_GENERATION_BATCH` | `10` | Cap on candidates per generation job |

Model IDs are settings, not literals, so the product survives model changes
(§73).

---

## Design system

Provisional palette aligned to NxtWave's public blue-led identity (§85–90).
Purple is a restrained secondary accent for AI states only and must not compete
with NxtWave blue.

| Token | Value |
|---|---|
| NxtWave Blue | `#2563EB` |
| Deep Blue | `#0F3D99` |
| Dark Navy | `#0F172A` |
| Light Blue | `#EAF2FF` |
| Soft Blue | `#F5F9FF` |
| Accent Purple | `#7C3AED` |

One rule worth calling out: **red never appears before verification**, because
red would reveal that the AI is wrong (§87). Pre-judgment states are neutral
blue.

---

## Product boundaries

Breakpoint measures **verification behaviour**, never topic mastery. It does not
compute or modify Topic Mastery, which stays in its own NxtWave system (§59,
§110 risk 6). Every metric here — Correct Trust Rate, False Alarm Rate,
verification skills — describes whether a student can tell a *verified* answer
from a *convincing* one.

Roughly one challenge in four is genuinely correct (26% of the shipped 1,080),
and approving it correctly scores as a win. A further 6% cannot be judged from
what is shown, where saying so is the win. The product must not teach blind
skepticism (§54).
