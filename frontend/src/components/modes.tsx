/** The P1 challenge modes: F (Break the Tests) and G (Which AI Is Wrong).
 *
 * PRD v0.2 section 4.2. Both are variations on the same investigation loop, so
 * everything here is presentational - the verdict and the test outcome are
 * decided on the server, and this file never knows which rival is right.
 */

import { useState } from 'react'
import type {
  BreakTestResult,
  CompetingSolution,
  JudgmentValue,
  TestGap,
} from '../api'
import { Banner, ConfidenceBadge, Spinner, VerificationBadge } from './ui'

/* ======================================================================
 * Mode G - Which AI Is Wrong
 * ==================================================================== */

/** Two rival solutions, side by side on desktop and stacked on mobile.
 *
 * Deliberately symmetrical: same width, same typography, same confidence
 * badge treatment. Any asymmetry would be a hint, and the whole point of the
 * mode is that presentation carries no information about correctness. */
export function CompetingSolutions({
  solutions,
  selectedStep,
  onSelectStep,
}: {
  solutions: CompetingSolution[]
  selectedStep: number | null
  onSelectStep: (step: number | null) => void
}) {
  return (
    <div>
      <p className="text-sm text-ink-muted">
        Two assistants answered the same question and disagree. Click the step
        where you think they part company.
        {selectedStep
          ? ` You have marked step ${selectedStep}.`
          : ''}
      </p>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        {solutions.map((solution) => (
          <RivalCard
            key={solution.label}
            solution={solution}
            selectedStep={selectedStep}
            onSelectStep={onSelectStep}
          />
        ))}
      </div>
    </div>
  )
}

function RivalCard({
  solution,
  selectedStep,
  onSelectStep,
}: {
  solution: CompetingSolution
  selectedStep: number | null
  onSelectStep: (step: number | null) => void
}) {
  return (
    <div className="bp-card flex flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-page px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-xs font-bold text-white">
            {solution.label}
          </span>
          <span className="text-sm font-bold">
            {solution.persona || `Solution ${solution.label}`}
          </span>
        </div>
        <ConfidenceBadge value={solution.simulated_confidence} />
      </div>

      <blockquote className="border-b border-slate-100 px-5 py-4 text-[15px] font-normal text-ink">
        &ldquo;{solution.ai_claim}&rdquo;
      </blockquote>

      <div className="flex-1 px-2 py-2">
        {solution.ai_solution.map((step) => {
          const selected = selectedStep === step.index
          return (
            <button
              key={step.index}
              onClick={() => onSelectStep(selected ? null : step.index)}
              aria-pressed={selected}
              className={`bp-step bp-step-selectable ${
                selected ? 'bp-step-selected' : ''
              } flex w-full gap-3 rounded-lg px-3 py-2.5 text-left`}
            >
              <span
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-md text-xs font-bold ${
                  selected ? 'bg-brand text-white' : 'bg-slate-100 text-slate-600'
                }`}
              >
                {step.index}
              </span>
              <span className="text-sm leading-relaxed">{step.text}</span>
            </button>
          )
        })}
      </div>

      <div className="border-t border-slate-100 bg-page px-5 py-3 text-sm">
        <span className="font-bold">Final answer:</span>{' '}
        <span className="font-mono">{solution.ai_final_answer}</span>
      </div>
    </div>
  )
}

/** Verdict buttons, driven by what the server says the mode accepts.
 *
 * The comparison verdicts include `both`, `neither` and `underdetermined` on
 * purpose: offering only A and B would teach that one of two confident answers
 * must be right, which is the misconception the mode exists to break. */
const VERDICT_COPY: Record<JudgmentValue, { label: string; hint: string }> = {
  challenge: { label: 'Challenge', hint: 'Something here is wrong' },
  approve: { label: 'Approve', hint: 'The reasoning holds' },
  insufficient_information: {
    label: 'Not enough information',
    hint: 'This cannot be decided',
  },
  a_correct: { label: 'A is right', hint: 'B goes wrong somewhere' },
  b_correct: { label: 'B is right', hint: 'A goes wrong somewhere' },
  both_correct: { label: 'Both are right', hint: 'Different routes, same valid answer' },
  neither_correct: { label: 'Neither is right', hint: 'Both of them fail' },
  underdetermined: {
    label: 'Cannot be decided',
    hint: 'A fact is missing from the question',
  },
}

/** The four-step certainty scale, asked before the verdict.
 *
 * Numbers, not adjectives alone: calibration is arithmetic, and "fairly sure"
 * means nothing to a Brier score. The steps match the bands the backend
 * scores against (app/engine/calibration.py), and 50 is the floor because a
 * student who is truly guessing is guessing between two readings, not five.
 *
 * Asked first, and locked once the verdict is in: a confidence chosen after
 * the outcome is known measures nothing. */
const CONFIDENCE_STEPS = [
  { value: 50, label: 'Guessing', hint: 'Could go either way' },
  { value: 65, label: 'Leaning', hint: 'A hunch, no more' },
  { value: 80, label: 'Fairly sure', hint: 'I have a reason' },
  { value: 95, label: 'Certain', hint: 'I can show why' },
] as const

export function ConfidenceScale({
  value,
  onChange,
  disabled,
}: {
  value: number | null
  onChange: (value: number) => void
  disabled?: boolean
}) {
  return (
    <fieldset disabled={disabled} className="mt-4">
      <legend className="text-sm font-bold">
        Before you decide — how sure are you?
      </legend>
      <p className="mt-1 text-sm text-slate-600">
        Recorded with your verdict and scored against how often you turn out to
        be right. Being wrong is fine; being certain and wrong is the habit
        worth catching.
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-4">
        {CONFIDENCE_STEPS.map((step) => {
          const active = value === step.value
          return (
            <button
              key={step.value}
              type="button"
              onClick={() => onChange(step.value)}
              aria-pressed={active}
              className={`rounded-control border px-3 py-2 text-left transition ${
                active
                  ? 'border-brand bg-brand-soft text-brand-hover'
                  : 'border-slate-200 bg-white hover:border-brand'
              } disabled:opacity-45`}
            >
              <span className="block text-sm font-bold">
                {step.label} <span className="tabular-nums">{step.value}%</span>
              </span>
              <span className="mt-0.5 block text-[11px] text-slate-500">
                {step.hint}
              </span>
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

export function VerdictButtons({
  allowed,
  onJudge,
  busy,
}: {
  allowed: JudgmentValue[]
  onJudge: (verdict: JudgmentValue) => void
  busy: boolean
}) {
  return (
    <div
      className={`mt-4 grid gap-2 ${
        allowed.length > 3 ? 'sm:grid-cols-2 lg:grid-cols-3' : 'sm:grid-cols-3'
      }`}
    >
      {allowed.map((verdict, i) => {
        const copy = VERDICT_COPY[verdict]
        return (
          <button
            key={verdict}
            onClick={() => onJudge(verdict)}
            disabled={busy}
            className={`bp-btn ${i === 0 ? 'bp-btn-primary' : 'bp-btn-ghost'}`}
          >
            {copy.label}
            <span
              className={`mt-0.5 block text-[11px] font-normal ${
                i === 0 ? 'opacity-80' : 'text-slate-500'
              }`}
            >
              {copy.hint}
            </span>
          </button>
        )
      })}
    </div>
  )
}

/* ======================================================================
 * Mode F - Break the Tests
 * ==================================================================== */

/** The shipped suite, shown as the thing not to trust. */
export function ShippedSuite({
  tests,
  result,
}: {
  tests: string[]
  result: string
}) {
  if (tests.length === 0) return null
  return (
    <div className="bp-card mt-4 overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-page px-4 py-2.5">
        <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
          Shipped test suite
        </span>
        {result && (
          <VerificationBadge state="verified">{result}</VerificationBadge>
        )}
      </div>
      <ul className="divide-y divide-slate-100">
        {tests.map((test, i) => (
          <li key={i} className="px-4 py-2 font-mono text-sm">
            {test}
          </li>
        ))}
      </ul>
      <p className="border-t border-slate-100 bg-page px-4 py-2.5 text-xs text-ink-muted">
        Every one of these passes. That is the claim you are investigating, not
        the evidence that settles it.
      </p>
    </div>
  )
}

const REASON_TONE: Record<BreakTestResult['reason_code'], 'success' | 'info' | 'warn'> = {
  suite_broken: 'success',
  no_divergence: 'info',
  already_covered: 'info',
  unparseable_input: 'warn',
  execution_error: 'warn',
}

/** The outcome task for Mode F: supply an input the suite forgot.
 *
 * Repeated submissions are expected - narrowing an input space by elimination
 * is the skill - so a rejected input is reported as information rather than as
 * a failure, and the running list of what has been tried stays on screen. */
export function BreakTestsPanel({
  gap,
  onSubmit,
  disabled,
}: {
  gap: TestGap
  onSubmit: (input: string, rationale: string) => Promise<BreakTestResult>
  disabled: boolean
}) {
  const [input, setInput] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempts, setAttempts] = useState<BreakTestResult[]>([])
  const broken = attempts.some((a) => a.accepted)

  async function submit() {
    if (!input.trim() || busy) return
    setBusy(true)
    try {
      const result = await onSubmit(input.trim(), rationale.trim())
      setAttempts((prev) => [...prev, result])
      if (result.accepted) setInput('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bp-card p-5">
      <h3 className="text-sm font-bold">Break the tests</h3>
      <p className="mt-1 text-sm text-ink-muted">
        Supply one input on which this implementation and correct behaviour
        disagree. Worth 20 of your 100-point Investigation Score.
      </p>

      <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="font-bold text-slate-500">Call</dt>
        <dd className="font-mono">{gap.signature || `${gap.entry_point}(…)`}</dd>
        {gap.input_guidance && (
          <>
            <dt className="font-bold text-slate-500">Input</dt>
            <dd>{gap.input_guidance}</dd>
          </>
        )}
      </dl>

      <div className="mt-4 space-y-2">
        <label className="block">
          <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            Test input
          </span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submit()
            }}
            disabled={disabled || busy}
            placeholder={gap.input_guidance || '[1, 2]'}
            className="mt-1 w-full rounded-card border border-slate-200 px-3.5 py-2.5 font-mono text-sm focus:border-brand focus:outline-none disabled:bg-page"
          />
        </label>
        <label className="block">
          <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            Why this input (optional)
          </span>
          <textarea
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
            disabled={disabled || busy}
            rows={2}
            placeholder="The suite never covers…"
            className="mt-1 w-full resize-y rounded-card border border-slate-200 px-3.5 py-2.5 text-sm focus:border-brand focus:outline-none disabled:bg-page"
          />
        </label>
      </div>

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => void submit()}
          disabled={disabled || busy || !input.trim()}
          className="bp-btn bp-btn-primary"
        >
          Run this test
        </button>
        {busy && <Spinner label="Running against both implementations" />}
        {broken && (
          <VerificationBadge state="verified">Suite broken</VerificationBadge>
        )}
      </div>

      {attempts.length > 0 && (
        <ol className="mt-4 space-y-2">
          {attempts.map((attempt, i) => (
            <li key={i}>
              <Banner kind={REASON_TONE[attempt.reason_code]}>
                <div className="text-sm">
                  {attempt.normalised_input && (
                    <span className="font-mono">{attempt.normalised_input}</span>
                  )}
                  {attempt.normalised_input && ' — '}
                  {attempt.message}
                </div>
              </Banner>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
