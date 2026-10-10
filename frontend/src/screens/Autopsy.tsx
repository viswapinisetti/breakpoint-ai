/** Failure Replay, Counterfactual and Debrief.
 *
 * PRD v0.2 sections 5.2, 10.1. The screen adapts to the artifact's truth
 * state: a flawed artifact gets a first-cause replay, a valid one explains why
 * it held, and an insufficient-information one shows the competing readings
 * that prove the gap.
 */

import { useState } from 'react'
import {
  api,
  type Autopsy as AutopsyData,
  type ComparisonJudgment,
  type TransferResult,
  type TruthState,
} from '../api'
import { StatCard, VerificationBadge } from '../components/ui'

const HEADLINE: Record<TruthState, string> = {
  flawed: 'Failure exposed',
  valid: 'The artifact was valid',
  insufficient_information: 'The information was insufficient',
}

const SUBHEAD: Record<TruthState, string> = {
  flawed: '',
  valid:
    'This artifact held up under scrutiny. Approving valid work, and saying why, is a verification skill in its own right.',
  insufficient_information:
    'The supplied facts could not settle this claim. Recognising that is different from answering the question, and just as important.',
}

/** Step labels per PRD v0.2 section 7.2 - plain words, no decorative marks. */
const STEP_LABEL: Record<string, string> = {
  valid: 'Valid step',
  first_failure: 'First failure',
  derived: 'Depends on the earlier failure',
  divergence: 'The two solutions part company here',
}

/** Mode G. Stated as what was true, not as whether the student was right -
 *  the score already says that, and the lesson is the verdict itself. */
const VERDICT_HEADLINE: Record<ComparisonJudgment, string> = {
  a_correct: 'Solution A was right',
  b_correct: 'Solution B was right',
  both_correct: 'Both solutions were right',
  neither_correct: 'Neither solution was right',
  underdetermined: 'Neither could be right',
}

const VERDICT_SUBHEAD: Record<ComparisonJudgment, string> = {
  a_correct: 'B looked authoritative and was not.',
  b_correct: 'A looked authoritative and was not.',
  both_correct:
    'Two different routes, both valid. Confident disagreement is not evidence that one side is wrong.',
  neither_correct:
    'Two confident answers, both wrong. Choosing between them was the wrong move.',
  underdetermined:
    'Both derived the mathematics correctly and then filled a gap the question left open. The honest answer was that it cannot be decided.',
}

const SOLUTION_LABELS = ['A', 'B'] as const

function num(value: number | boolean | undefined): string {
  return typeof value === 'number' ? value.toFixed(0) : '0'
}

/** A short check on new values, asked after the debrief (PRD v0.2 5.2, 8.3).
 *
 * Scored separately from the attempt: it measures whether the idea transferred,
 * not how the original investigation went. Skipping it is explicitly allowed
 * and simply records no transfer score.
 */
function TransferCheck({
  attemptId,
  question,
}: {
  attemptId: number
  question: string
}) {
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<TransferResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [skipped, setSkipped] = useState(false)

  async function submit() {
    if (!answer.trim()) return
    setBusy(true)
    try {
      setResult(await api.transfer(attemptId, answer))
    } catch {
      /* leave the field for a retry */
    } finally {
      setBusy(false)
    }
  }

  if (skipped) return null

  return (
    <section className="mt-7">
      <h2 className="text-lg font-bold">Transfer check</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Different numbers, same idea. Scored separately from this investigation.
      </p>
      <div className="bp-card mt-3 p-5">
        <p className="text-sm">{question}</p>
        {result === null ? (
          <>
            <div className="mt-3 flex flex-wrap gap-2">
              <input
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void submit()
                }}
                placeholder="Your answer"
                className="flex-1 rounded-control border border-slate-200 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none"
                aria-label="Transfer check answer"
              />
              <button
                onClick={submit}
                disabled={busy || !answer.trim()}
                className="bp-btn bp-btn-primary"
              >
                Check
              </button>
              <button onClick={() => setSkipped(true)} className="bp-btn bp-btn-ghost">
                Skip
              </button>
            </div>
          </>
        ) : (
          <div
            className={`mt-3 rounded-card border px-4 py-3 text-sm ${
              result.correct
                ? 'border-emerald-200 bg-emerald-50'
                : 'border-amber-200 bg-amber-50'
            }`}
          >
            <div className="font-bold">
              {result.correct ? 'Correct' : 'Not quite'}
            </div>
            <p className="mt-1">{result.message}</p>
          </div>
        )}
      </div>
    </section>
  )
}

interface Props {
  data: AutopsyData
  attemptId: number
  onNext: () => void
  onExit: () => void
}

export function Autopsy({ data, attemptId, onNext, onExit }: Props) {
  const score = data.score
  const verdict = data.comparison_verdict || null
  // In a comparison there is no single artifact to have been flawed, so the
  // replay and the headline follow the verdict instead of the truth state.
  const flawed = !verdict && data.truth_state === 'flawed'
  const triedTests = data.test_submissions > 0

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="bp-banner rounded-2xl p-7 text-white">
        <div className="text-[11px] font-bold tracking-widest uppercase opacity-80">
          Investigation debrief
        </div>
        <h1 className="mt-2 text-2xl font-bold">
          {verdict ? VERDICT_HEADLINE[verdict] : HEADLINE[data.truth_state]}
        </h1>
        <p className="mt-2 text-[15px] text-white/90">
          {verdict
            ? VERDICT_SUBHEAD[verdict]
            : flawed
              ? data.misconception
              : SUBHEAD[data.truth_state]}
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-6">
          <div>
            <div className="text-[11px] tracking-widest uppercase opacity-75">
              Investigation Score
            </div>
            <div className="text-3xl font-bold tabular-nums">
              {num(score.total)}
              <span className="text-lg font-normal opacity-70">/100</span>
            </div>
          </div>
          <div className="text-sm">
            <div className="opacity-75">Correct answer</div>
            <div className="font-mono text-lg font-bold">
              {data.canonical_answer}
            </div>
          </div>
          {flawed && (
            <div className="text-sm">
              <div className="opacity-75">AI claimed</div>
              <div className="font-mono text-lg font-bold line-through opacity-80">
                {data.ai_final_answer}
              </div>
            </div>
          )}
        </div>
        {data.assisted && (
          <p className="mt-4 rounded-lg bg-white/15 px-3 py-2 text-xs">
            Completed with guidance. Your score stands; this attempt is not
            counted toward independent-success statistics.
          </p>
        )}
      </div>

      {data.answer_coincidentally_correct && (
        <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
          <div className="font-bold text-needs-evidence">
            Correct answer, invalid reasoning
          </div>
          <p className="mt-1 text-sm text-amber-900">
            The AI reached the right number through reasoning that does not hold.
            A correct answer is not evidence of a correct method.
          </p>
        </div>
      )}

      {/* Insufficient information: the competing readings are the proof. */}
      {data.truth_state === 'insufficient_information' && (
        <section className="mt-7">
          <h2 className="text-lg font-bold">What was missing</h2>
          <p className="mt-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
            {data.missing_information}
          </p>
          {data.resolving_scenarios.length > 0 && (
            <>
              <h3 className="mt-4 text-[11px] font-bold tracking-wider text-slate-500 uppercase">
                Readings that fit the problem and disagree
              </h3>
              <ul className="mt-2 space-y-2">
                {data.resolving_scenarios.map((sc, i) => (
                  <li
                    key={i}
                    className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"
                  >
                    {sc}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {/* Failure Replay - only meaningful when something failed. */}
      {flawed && (
        <section className="mt-7">
          <h2 className="text-lg font-bold">Failure Replay</h2>
          <p className="mt-1 text-sm text-slate-600">
            Find the first cause, not the final wrong answer.
          </p>
          <div className="bp-card mt-4 divide-y divide-slate-100">
            {data.replay.map((s) => {
              const isFirst = s.status === 'first_failure'
              const derived = s.status === 'derived'
              return (
                <div
                  key={s.index}
                  className={`flex gap-4 px-5 py-3.5 ${
                    isFirst ? 'bg-red-50' : derived ? 'bg-amber-50/40' : ''
                  }`}
                >
                  <span
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold ${
                      isFirst
                        ? 'bg-red-700 text-white'
                        : derived
                          ? 'bg-amber-200 text-amber-900'
                          : 'bg-emerald-100 text-emerald-900'
                    }`}
                  >
                    {s.index}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-relaxed">{s.text}</p>
                    <div className="mt-1.5 text-xs font-bold text-slate-600">
                      {STEP_LABEL[s.status] ?? s.status}
                    </div>
                    {isFirst && (
                      <div className="mt-2">
                        <VerificationBadge state="exposed">
                          validity breaks here
                        </VerificationBadge>
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          {data.first_failure_step !== null && (
            <p className="mt-3 rounded-xl bg-brand-soft px-4 py-3 text-sm text-brand-hover">
              Everything after step {data.first_failure_step} followed
              consistently from it. That is precisely why the solution reads as
              correct — the error entered once and was never revisited.
            </p>
          )}
        </section>
      )}

      {/* Mode G: both solutions replayed, with the divergence marked in each. */}
      {verdict && (
        <section className="mt-7">
          <h2 className="text-lg font-bold">Where they diverged</h2>
          <p className="mt-1 text-sm text-slate-600">
            {data.comparison_explanation}
          </p>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {SOLUTION_LABELS.map((label) => (
              <div key={label} className="bp-card overflow-hidden">
                <div className="border-b border-slate-200 bg-page px-5 py-2.5 text-sm font-bold">
                  Solution {label}
                </div>
                <div className="divide-y divide-slate-100">
                  {data.replay
                    .filter((s) => s.solution === label)
                    .map((s) => {
                      const diverges = s.status === 'divergence'
                      const after = s.status === 'derived'
                      return (
                        <div
                          key={label + s.index}
                          className={
                            'flex gap-3 px-4 py-3 ' +
                            (diverges
                              ? 'bg-amber-50'
                              : after
                                ? 'bg-amber-50/30'
                                : '')
                          }
                        >
                          <span
                            className={
                              'grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold ' +
                              (diverges
                                ? 'bg-amber-500 text-white'
                                : after
                                  ? 'bg-amber-200 text-amber-900'
                                  : 'bg-emerald-100 text-emerald-900')
                            }
                          >
                            {s.index}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-sm leading-relaxed">{s.text}</p>
                            {diverges && (
                              <div className="mt-1.5 text-xs font-bold text-slate-600">
                                {STEP_LABEL.divergence}
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Mode F: what the student's own test established. */}
      {triedTests && (
        <section className="mt-7">
          <h2 className="text-lg font-bold">Your test</h2>
          <div className="bp-card mt-3 p-5">
            {data.test_broke_suite ? (
              <>
                <VerificationBadge state="exposed">
                  suite broken
                </VerificationBadge>
                <p className="mt-3 text-sm leading-relaxed text-slate-700">
                  <span className="font-mono">{data.test_input}</span> is the
                  input the shipped suite never asked about. You found it in{' '}
                  {data.test_submissions}{' '}
                  {data.test_submissions === 1 ? 'attempt' : 'attempts'}.
                </p>
              </>
            ) : (
              <p className="text-sm leading-relaxed text-slate-700">
                You tried {data.test_submissions}{' '}
                {data.test_submissions === 1 ? 'input' : 'inputs'} without
                separating the two implementations. Each one ruled out a region
                of the input space, which is how this work actually goes. The
                repair below shows where the gap was.
              </p>
            )}
          </div>
        </section>
      )}

      <section className="mt-7">
        <h2 className="text-lg font-bold">Counterfactual</h2>
        <p className="mt-2 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
          {data.counterfactual}
        </p>
      </section>

      {data.why_convincing && (
        <section className="mt-7">
          <h2 className="text-lg font-bold">Why this was easy to miss</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-700">
            {data.why_convincing}
          </p>
        </section>
      )}

      <section className="mt-7">
        <h2 className="text-lg font-bold">The real reason</h2>
        <div className="bp-card mt-3 p-5">
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-slate-700">
            {data.debrief}
          </p>
          {data.repair && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
                {flawed ? 'Correct repair' : 'What was needed'}
              </div>
              <p className="mt-1 text-sm">{data.repair}</p>
            </div>
          )}
          {data.counterexamples.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
                Evidence that settles it
              </div>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                {data.counterexamples.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>

      {/* Investigation Score, out of 100 (PRD v0.2 section 10.1). */}
      <section className="mt-7">
        <h2 className="text-lg font-bold">Investigation Score</h2>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard
            label="Initial judgment /20"
            value={num(score.initial_judgment)}
          />
          <StatCard label="Evidence /35" value={num(score.evidence)} />
          <StatCard label="Reasoning /25" value={num(score.reasoning)} />
          <StatCard
            label="Outcome task /20"
            value={num(score.outcome_task)}
            hint={data.hints_used > 0 ? `${data.hints_used} hints used` : undefined}
          />
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Hints never deduct points. Using them marks the attempt as completed
          with guidance, which keeps independent-success statistics honest.
        </p>
      </section>

      {data.transfer_question && (
        <TransferCheck attemptId={attemptId} question={data.transfer_question} />
      )}

      <div className="mt-8 mb-4 flex flex-wrap gap-3">
        <button onClick={onNext} className="bp-btn bp-btn-primary">
          Next investigation
        </button>
        <button onClick={onExit} className="bp-btn bp-btn-ghost">
          Back to dashboard
        </button>
      </div>
    </div>
  )
}
