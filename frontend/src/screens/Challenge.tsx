/** The challenge player: AI Claim, Evidence Board, Debate, Repair.
 *
 * PRD sections 37-40. Desktop is a two-pane split; mobile collapses to the
 * CLAIM / EVIDENCE / TOOLS / DEBATE tabs from PRD section 38.
 */

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  api,
  ApiError,
  type Autopsy,
  type DebateTurn,
  type EvidenceResult,
  type EvidenceCardDraft,
  type JudgmentValue,
  type OutcomeTask,
  type StartAttempt,
} from '../api'
import {
  ArtifactView,
  Banner,
  ConfidenceBadge,
  DifficultyIndicator,
  Spinner,
  VerificationBadge,
} from '../components/ui'
import { ToolsPanel } from '../components/tools'
import {
  EvidenceBoard,
  EvidenceResultCard,
  emptyCard,
} from '../components/evidence'
import {
  BreakTestsPanel,
  CompetingSolutions,
  ConfidenceScale,
  ShippedSuite,
  VerdictButtons,
} from '../components/modes'

/** The task after a judgment depends on what was actually true - a correct
 *  artifact must not demand an invented correction (PRD v0.2 section 5.2). */
const OUTCOME_COPY: Record<
  OutcomeTask,
  { title: string; help: string; placeholder: string }
> = {
  repair: {
    title: 'Repair the artifact',
    help: 'Rewrite the failing step so the reasoning becomes correct.',
    placeholder: 'Step N should read…',
  },
  justify: {
    title: 'Justify your approval',
    help: 'This artifact needed no correction. Say what you checked and why it holds for the stated scope.',
    placeholder: 'I verified that…',
  },
  clarify: {
    title: 'Name the missing information',
    help: 'Say which fact is absent and show why the supplied information cannot settle the claim.',
    placeholder: 'The problem does not state… Without it, X gives … and Y gives …',
  },
  // Break the Tests replaces the prose task with an executable one, so this
  // entry is never rendered as a textarea - BreakTestsPanel takes over.
  break_tests: {
    title: 'Break the tests',
    help: 'Supply an input the shipped suite never covers, on which the implementation is wrong.',
    placeholder: '',
  },
}

type Tab = 'claim' | 'evidence' | 'debate'

interface Props {
  challengeId: string
  onComplete: (autopsy: Autopsy, attemptId: number) => void
  onExit: () => void
  /** Where the shell wants the Back / Hint / Complete actions: the breadcrumb
   *  bar, so they cost no vertical space above the question. Rendered in
   *  place when the shell supplies no slot. */
  actionSlot?: HTMLElement | null
}

export function Challenge({ challengeId, onComplete, onExit, actionSlot }: Props) {
  const [data, setData] = useState<StartAttempt | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<Tab>('claim')

  // Investigation state
  const [selectedStep, setSelectedStep] = useState<number | null>(null)
  const [judged, setJudged] = useState<{
    correct: boolean
    message: string
    outcomeTask: OutcomeTask
    calibrationNote: string
  } | null>(null)
  // Stated before the verdict and never editable afterwards: a confidence
  // chosen once the outcome is known measures nothing.
  const [confidence, setConfidence] = useState<number | null>(null)
  const [judging, setJudging] = useState(false)

  const [cards, setCards] = useState<EvidenceCardDraft[]>([])
  const [evidenceResults, setEvidenceResults] = useState<EvidenceResult[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [structuralErrors, setStructuralErrors] = useState<string[]>([])

  const [hints, setHints] = useState<{ level: number; text: string }[]>([])
  const [hintBusy, setHintBusy] = useState(false)

  const [debate, setDebate] = useState<DebateTurn[]>([])
  const [debateMsg, setDebateMsg] = useState('')
  const [debateBusy, setDebateBusy] = useState(false)
  const [debateEnded, setDebateEnded] = useState(false)
  const [turnsLeft, setTurnsLeft] = useState(0)

  const [repairText, setRepairText] = useState('')
  const [repairResult, setRepairResult] = useState<string | null>(null)
  const [finishing, setFinishing] = useState(false)
  const [notice, setNotice] = useState('')

  const debateScrollRef = useRef<HTMLDivElement>(null)
  // Turn count at the last scroll, so loading existing history does not read
  // as "a new message arrived".
  const seenTurns = useRef<number | null>(null)

  useEffect(() => {
    setError('')
    api
      .start(challengeId)
      .then((d) => {
        setData(d)
        setTurnsLeft(d.max_debate_turns)
        setCards([emptyCard(d.evidence_types[0] ?? 'calculation')])
        return api.debateHistory(d.attempt_id)
      })
      .then((turns) => {
        setDebate(turns)
        if (turns.some((t) => t.conceded)) setDebateEnded(true)
      })
      .catch((e) => setError(e.message))
  }, [challengeId])

  useEffect(() => {
    // Scroll the debate's own container, never the window. `scrollIntoView`
    // walks every scrollable ancestor including the document, so using it here
    // pulled the whole page down to the debate panel the moment the existing
    // history loaded - which is why an investigation opened mid-page.
    const previous = seenTurns.current
    seenTurns.current = debate.length
    if (previous === null || debate.length <= previous) return

    const box = debateScrollRef.current
    if (box) box.scrollTo({ top: box.scrollHeight, behavior: 'smooth' })
  }, [debate])

  if (error && !data) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16">
        <Banner kind="error">{error}</Banner>
        <button onClick={onExit} className="bp-btn bp-btn-ghost mt-4">
          Back to dashboard
        </button>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16">
        <Spinner label="Opening investigation" />
      </div>
    )
  }

  const c = data.challenge

  async function judge(judgment: JudgmentValue) {
    if (!data) return
    setJudging(true)
    setNotice('')
    try {
      const r = await api.judge(data.attempt_id, judgment, selectedStep, confidence)
      setJudged({
        correct: r.correct,
        message: r.message,
        outcomeTask: r.outcome_task,
        calibrationNote: r.calibration_note,
      })
      setTab('evidence')
    } catch (e) {
      setNotice((e as Error).message)
    } finally {
      setJudging(false)
    }
  }

  async function submitEvidence() {
    if (!data || cards.length === 0) return
    setSubmitting(true)
    setNotice('')
    setStructuralErrors([])
    // A fresh key per submission, reused across retries of that submission, so
    // a flaky connection cannot create two revisions (PRD v0.2 section 13.3).
    const key = `${data.attempt_id}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    try {
      const r = await api.evidence(data.attempt_id, cards, key)
      setEvidenceResults((prev) => [r, ...prev])
      if (r.status === 'supported') setCards([])
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setStructuralErrors(e.fieldErrors ?? [e.message])
      } else if (e instanceof ApiError && e.status === 503) {
        setNotice('Evidence evaluation is unavailable. Your work is saved.')
      } else {
        setNotice((e as Error).message)
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function takeHint() {
    if (!data) return
    setHintBusy(true)
    try {
      const h = await api.hint(data.attempt_id)
      setHints((prev) => [...prev, { level: h.level, text: h.text }])
    } catch (e) {
      setNotice((e as Error).message)
    } finally {
      setHintBusy(false)
    }
  }

  async function sendDebate() {
    if (!data || !debateMsg.trim()) return
    const message = debateMsg
    setDebateMsg('')
    setDebateBusy(true)
    setDebate((prev) => [
      ...prev,
      { turn: prev.length, role: 'student', message, conceded: false },
    ])
    try {
      const r = await api.debate(data.attempt_id, message)
      setDebate((prev) => [
        ...prev,
        { turn: r.turn, role: 'ai', message: r.reply, conceded: r.conceded },
      ])
      setTurnsLeft(r.turns_remaining)
      if (r.conceded || r.exhausted) setDebateEnded(true)
    } catch (e) {
      setNotice(
        e instanceof ApiError && e.status === 503
          ? 'Breakpoint AI is unavailable (no AI credential configured).'
          : (e as Error).message,
      )
    } finally {
      setDebateBusy(false)
    }
  }

  async function finish() {
    if (!data) return
    setFinishing(true)
    try {
      if (repairText.trim()) {
        const r = await api.repair(data.attempt_id, repairText)
        setRepairResult(r.feedback)
      }
      const autopsy = await api.complete(data.attempt_id)
      onComplete(autopsy, data.attempt_id)
    } catch (e) {
      setNotice((e as Error).message)
      setFinishing(false)
    }
  }

  const canFinish = judged !== null

  // The mode changes what the claim pane shows and what the outcome task is.
  // Both are read off the payload rather than off the mode string, so a mode
  // that arrives without its data degrades to the single-artifact view instead
  // of rendering blank.
  const isComparison = c.competing.length === 2
  const testGap = c.test_gap
  // Break the Tests gives the suite its own presentation - green, trusted,
  // and wrong - so it is lifted out of the generic artifact rendering rather
  // than appearing as one more labelled field.
  const shippedTests = Array.isArray(c.artifact.tests)
    ? (c.artifact.tests as unknown[]).map(String)
    : []
  const artifactBody = testGap
    ? Object.fromEntries(
        Object.entries(c.artifact).filter(
          ([k]) => k !== 'tests' && k !== 'test_result',
        ),
      )
    : c.artifact
  const stepCount = isComparison
    ? Math.max(...c.competing.map((s) => s.ai_solution.length))
    : c.ai_solution.length

  /* ---------------------------------------------------------------- panes */

  const claimPane = (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-full bg-brand-soft px-3 py-1 text-[11px] font-bold tracking-widest text-brand-hover uppercase">
            {c.subject} · {c.subtopic || c.topic}
          </span>
          <DifficultyIndicator level={c.difficulty} />
        </div>
        <h2 className="mt-2.5 text-[15px] leading-relaxed font-normal">
          {c.question}
        </h2>
        <ArtifactView artifact={artifactBody} type={c.artifact_type} />
        {testGap && (
          <ShippedSuite
            tests={shippedTests}
            result={String(c.artifact.test_result ?? '')}
          />
        )}
      </div>

      {isComparison ? (
        <CompetingSolutions
          solutions={c.competing}
          selectedStep={selectedStep}
          onSelectStep={setSelectedStep}
        />
      ) : (
      <div className="bp-card overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-page px-5 py-2.5">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-xs font-bold text-white">
              AI
            </span>
            <span className="text-sm font-bold">Breakpoint AI</span>
          </div>
          <ConfidenceBadge value={c.simulated_confidence} />
        </div>

        <blockquote className="border-b border-slate-100 px-5 py-3 text-[15px] font-normal text-ink">
          &ldquo;{c.ai_claim}&rdquo;
        </blockquote>

        <div className="px-2 py-2">
          <div className="px-3 pb-2 text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            Reasoning — click a step to mark where it first fails
          </div>
          {c.ai_solution.map((s) => {
            const selected = selectedStep === s.index
            return (
              <button
                key={s.index}
                onClick={() => setSelectedStep(selected ? null : s.index)}
                aria-pressed={selected}
                className={`bp-step bp-step-selectable ${
                  selected ? 'bp-step-selected' : ''
                } flex w-full gap-3 rounded-lg px-3 py-2.5 text-left`}
              >
                <span
                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-md text-xs font-bold ${
                    selected
                      ? 'bg-brand text-white'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {s.index}
                </span>
                <span className="text-sm leading-relaxed">{s.text}</span>
              </button>
            )
          })}
        </div>

        <div className="border-t border-slate-100 bg-page px-5 py-3 text-sm">
          <span className="font-bold">Final answer:</span>{' '}
          <span className="font-mono">{c.ai_final_answer}</span>
        </div>
      </div>
      )}

      {/* Trust or Challenge (PRD section 29, Mode B) */}
      {!judged ? (
        <div className="bp-card p-5">
          <h3 className="text-sm font-bold">Your judgment</h3>
          <p className="mt-1 text-sm text-slate-600">
            {isComparison
              ? 'Two confident answers do not mean one of them is right. They may both be right, both be wrong, or the question may not settle it.'
              : 'Not every artifact here is wrong, and some cannot be settled from what you were given. Decide, then prove it.'}
            {selectedStep
              ? ` You have marked step ${selectedStep}${
                  isComparison ? ' as the divergence' : ' as the first failure'
                }.`
              : isComparison
                ? ' Optionally click the step where the two part company.'
                : ' Optionally click the step where you think it first fails.'}
          </p>
          <ConfidenceScale
            value={confidence}
            onChange={setConfidence}
            disabled={judging}
          />
          <VerdictButtons
            allowed={c.allowed_judgments}
            onJudge={judge}
            busy={judging || confidence === null}
          />
          {confidence === null && (
            <p className="mt-2 text-xs text-slate-500">
              Choose how sure you are to unlock the verdict.
            </p>
          )}
          {judging && (
            <div className="mt-3">
              <Spinner label="Recording" />
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <Banner kind={judged.correct ? 'success' : 'warn'}>
            <strong>
              {judged.correct ? 'Correct call.' : 'That call was not right.'}
            </strong>{' '}
            {judged.message}
          </Banner>
          {judged.calibrationNote && (
            <Banner kind="info">
              <strong>Your certainty.</strong> {judged.calibrationNote}
            </Banner>
          )}
        </div>
      )}
    </div>
  )

  const evidencePane = (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-bold">Evidence Board</h3>
        <p className="mt-1 text-sm text-ink-muted">
          Selecting “wrong” is not evidence. Each card states something
          checkable; up to five per submission.
        </p>
      </div>

      {!judged && (
        <Banner kind="info">
          Record your judgment on the claim first — approve, challenge, or say
          the information is not enough.
        </Banner>
      )}

      <EvidenceBoard
        cards={cards}
        setCards={setCards}
        allowedTypes={data.evidence_types}
        stepCount={stepCount}
        disabled={!judged}
      />

      {structuralErrors.length > 0 && (
        <Banner kind="warn" onDismiss={() => setStructuralErrors([])}>
          <div className="font-bold">This submission is not complete yet:</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {structuralErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </Banner>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={submitEvidence}
          disabled={!judged || submitting || cards.length === 0}
          className="bp-btn bp-btn-primary"
        >
          Submit evidence
        </button>
        {submitting && <Spinner label="Checking" />}
      </div>

      {evidenceResults.map((r, i) => (
        <EvidenceResultCard key={`${r.revision}-${i}`} result={r} />
      ))}

      {/* Outcome task - branches on what was actually true (PRD v0.2 5.2),
          and on the mode: Break the Tests wants a test, not prose. */}
      {judged && judged.outcomeTask === 'break_tests' && testGap && (
        <BreakTestsPanel
          gap={testGap}
          disabled={finishing}
          onSubmit={(input, why) =>
            api.breakTests(data.attempt_id, input, why)
          }
        />
      )}
      {judged && judged.outcomeTask !== 'break_tests' && (
        <div className="bp-card p-5">
          <h3 className="text-sm font-bold">
            {OUTCOME_COPY[judged.outcomeTask].title}
          </h3>
          <p className="mt-1 text-sm text-ink-muted">
            {OUTCOME_COPY[judged.outcomeTask].help} Worth 20 of your 100-point
            Investigation Score.
          </p>
          <textarea
            value={repairText}
            onChange={(e) => setRepairText(e.target.value)}
            rows={3}
            placeholder={OUTCOME_COPY[judged.outcomeTask].placeholder}
            className="mt-3 w-full resize-y rounded-card border border-slate-200 px-3.5 py-3 font-mono text-sm focus:border-brand focus:outline-none"
          />
          {repairResult && (
            <p className="mt-2 text-sm text-slate-700">{repairResult}</p>
          )}
        </div>
      )}
    </div>
  )

  const debatePane = (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold">Debate Breakpoint AI</h3>
        <span className="text-xs text-slate-500 tabular-nums">
          {turnsLeft} turn{turnsLeft === 1 ? '' : 's'} left
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        It will not concede to assertion. Bring evidence.
      </p>

      <div ref={debateScrollRef} className="mt-4 flex-1 space-y-3 overflow-y-auto">
        {debate.length === 0 && (
          <p className="rounded-xl bg-page px-4 py-6 text-center text-sm text-slate-500">
            Open with your strongest objection.
          </p>
        )}
        {debate.map((t, i) => (
          <div
            key={i}
            className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
              t.role === 'student'
                ? 'ml-auto bg-brand text-white'
                : 'bg-white border border-slate-200'
            }`}
          >
            <div
              className={`mb-1 text-[10px] font-bold tracking-widest uppercase ${
                t.role === 'student' ? 'text-white/70' : 'text-slate-400'
              }`}
            >
              {t.role === 'student' ? 'You' : 'Breakpoint AI'}
            </div>
            <p className="leading-relaxed whitespace-pre-wrap">{t.message}</p>
            {t.conceded && (
              <div className="mt-2">
                <VerificationBadge state="verified">
                  Conceded to your evidence
                </VerificationBadge>
              </div>
            )}
          </div>
        ))}
        {debateBusy && <Spinner label="Breakpoint AI is responding" />}
      </div>

      <div className="mt-3 flex gap-2">
        <input
          value={debateMsg}
          onChange={(e) => setDebateMsg(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void sendDebate()
            }
          }}
          disabled={!judged || debateBusy || debateEnded}
          placeholder={
            debateEnded ? 'This debate is settled.' : 'Your argument…'
          }
          className="flex-1 rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm focus:border-brand focus:outline-none disabled:bg-slate-50"
          aria-label="Your debate message"
        />
        <button
          onClick={sendDebate}
          disabled={!judged || debateBusy || debateEnded || !debateMsg.trim()}
          className="bp-btn bp-btn-primary"
        >
          Send
        </button>
      </div>
    </div>
  )

  const actions = (
    <div className="flex items-center gap-2">
      <button
        onClick={onExit}
        className="hidden px-2 text-sm font-bold text-slate-500 hover:text-brand-hover sm:block"
      >
        ← Back to contents
      </button>
      <button
        onClick={takeHint}
        disabled={hintBusy || hints.length >= c.hint_count}
        className="bp-btn bp-btn-ghost"
      >
        Hint {hints.length}/{c.hint_count}
      </button>
      <button
        onClick={finish}
        disabled={!canFinish || finishing}
        className="bp-btn bp-btn-primary"
      >
        {finishing ? 'Finishing…' : 'Complete investigation'}
      </button>
    </div>
  )

  return (
    <div className="mx-auto max-w-7xl">
      {actionSlot ? (
        createPortal(actions, actionSlot)
      ) : (
        <div className="mb-4 flex justify-end">{actions}</div>
      )}

      {notice && (
        <div className="mb-4">
          <Banner kind="warn" onDismiss={() => setNotice('')}>
            {notice}
          </Banner>
        </div>
      )}

      {hints.map((h) => (
        <div key={h.level} className="mb-3">
          <Banner kind="info">
            <span className="font-bold">Hint {h.level}:</span> {h.text}
          </Banner>
        </div>
      ))}

      {/* Mobile tabs (PRD section 38) */}
      <div className="mb-4 flex gap-1 rounded-xl bg-slate-100 p-1 lg:hidden">
        {(['claim', 'evidence', 'debate'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 rounded-lg py-2 text-xs font-bold tracking-wide uppercase transition ${
              tab === t ? 'bg-white text-brand-hover shadow-sm' : 'text-slate-500'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Desktop split (PRD section 37). The claim column is pinned below the
          header and breadcrumb bar and scrolls on its own, so the question
          and the AI's answer stay in view while the evidence side is worked
          on. 130px = 58px header + 56px breadcrumb bar + 16px gap. */}
      <div className="hidden gap-5 lg:grid lg:grid-cols-[1.25fr_1fr]">
        <div className="bp-pane-scroll lg:sticky lg:top-[130px] lg:max-h-[calc(100vh-146px)] lg:self-start lg:overflow-y-auto lg:pr-1.5">
          {claimPane}
          <ToolsPanel
            tools={data.tools}
            attemptId={data.attempt_id}
            selectedStep={selectedStep}
            artifact={c.artifact}
            question={c.question}
          />
        </div>
        <div className="space-y-6">
          <div className="bp-card p-5">{evidencePane}</div>
          <div className="bp-card h-[26rem] p-5">{debatePane}</div>
        </div>
      </div>

      {/* Mobile single pane */}
      <div className="lg:hidden">
        {tab === 'claim' && (
          <>
            {claimPane}
            <ToolsPanel
              tools={data.tools}
              attemptId={data.attempt_id}
              selectedStep={selectedStep}
              artifact={c.artifact}
              question={c.question}
            />
          </>
        )}
        {tab === 'evidence' && <div className="bp-card p-5">{evidencePane}</div>}
        {tab === 'debate' && (
          <div className="bp-card h-[28rem] p-5">{debatePane}</div>
        )}
      </div>
    </div>
  )
}
