/** My Progress (PRD v0.2 sections 10, 15.1).
 *
 * Two honesty rules drive this screen:
 *   - Rates below the minimum sample are not shown as numbers. A "67% accuracy"
 *     computed from three attempts is noise presented as insight.
 *   - The full three-way judgment matrix is shown rather than a right/wrong
 *     summary, because approving a flawed artifact and calling a determinate
 *     artifact undecidable are different errors that need different practice.
 */

import { useEffect, useState } from 'react'
import {
  api,
  type Calibration,
  type Stats,
  type TrustJudgment,
  type TruthState,
} from '../api'
import { Banner, SkillBar, StatCard } from '../components/ui'

const SKILL_LABELS: Record<string, string> = {
  counterexample_building: 'Counterexample building',
  assumption_checking: 'Assumption checking',
  logical_verification: 'Logical verification',
  error_localization: 'Error localization',
  evidence_quality: 'Evidence quality',
}

const TRUTH_LABEL: Record<TruthState, string> = {
  flawed: 'Artifact was flawed',
  valid: 'Artifact was valid',
  insufficient_information: 'Information was insufficient',
}

// The three-way matrix is defined over the trust verdicts only. Comparison
// verdicts ("A is right") are not answers to "when the artifact was flawed,
// what did you say", so the server excludes those attempts entirely rather
// than showing them as a blank row.
const JUDGMENT_LABEL: Record<TrustJudgment, string> = {
  challenge: 'Challenged',
  approve: 'Approved',
  insufficient_information: 'Said not enough info',
}

const JUDGMENTS: TrustJudgment[] = [
  'challenge',
  'approve',
  'insufficient_information',
]

const CORRECT_FOR: Record<TruthState, TrustJudgment> = {
  flawed: 'challenge',
  valid: 'approve',
  insufficient_information: 'insufficient_information',
}

const SCORE_LABELS: Record<string, string> = {
  initial_judgment: 'Initial judgment /20',
  evidence: 'Evidence /35',
  reasoning: 'Reasoning /25',
  outcome_task: 'Outcome task /20',
}

/** Confidence calibration: how well certainty matched being right.
 *
 * The bars are a reliability chart. Each band's bar is the accuracy inside
 * it, and the marker is the confidence claimed: a calibrated student's bar
 * reaches the marker. Bars are shown against the claimed confidence rather
 * than as a single number, because "80% sure and right 55% of the time" is a
 * different lesson from a Brier score, and it is the one a student can act on.
 */
function CalibrationSection({ calibration }: { calibration: Calibration }) {
  const c = calibration
  const used = c.bands.filter((b) => b.count > 0)
  const gapLabel =
    c.gap === null
      ? 'Not enough yet'
      : c.gap > 5
        ? `+${c.gap} overconfident`
        : c.gap < -5
          ? `${c.gap} underconfident`
          : `${c.gap > 0 ? '+' : ''}${c.gap} well matched`

  return (
    <section className="mt-8">
      <h2 className="text-lg font-bold">Confidence calibration</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Recorded before each verdict, scored against how it turned out. Being
        wrong is ordinary; being certain and wrong is the habit this trains
        away — especially when the AI sounded certain too.
      </p>

      {c.judged === 0 ? (
        <p className="mt-3 rounded-card bg-page px-4 py-5 text-sm text-slate-600">
          No judgments carry a confidence yet. The next investigation will ask
          how sure you are before you decide.
        </p>
      ) : (
        <>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Confidence gap"
              value={<span className="text-xl">{gapLabel}</span>}
              hint={
                c.gap === null
                  ? `Needs ${c.min_sample} rated judgments; you have ${c.judged}.`
                  : `${c.mean_confidence}% average certainty, ${c.accuracy}% right`
              }
            />
            <StatCard
              label="Brier score"
              value={c.brier === null ? <Rate value={null} /> : c.brier.toFixed(2)}
              hint="0 is perfect, 0.25 is a coin flip"
            />
            <StatCard
              label="Certain and wrong"
              value={c.over_trust}
              hint={`${c.recent_over_trust} in the last ${c.recent_days} days`}
            />
            <StatCard
              label="Right but hedged"
              value={c.under_trust}
              hint="You had it and talked yourself out of it"
            />
          </div>

          {c.believed_confident_ai > 0 && (
            <div className="mt-3">
              <Banner kind="warn">
                <strong>
                  You sided with a confident AI that was wrong{' '}
                  {c.believed_confident_ai}{' '}
                  {c.believed_confident_ai === 1 ? 'time' : 'times'}
                </strong>
                {c.recent_believed_confident_ai > 0 &&
                  `, ${c.recent_believed_confident_ai} of them in the last ${c.recent_days} days`}
                . A high confidence badge is a design choice, not evidence.
              </Banner>
            </div>
          )}

          <div className="mt-4 space-y-2">
            {used.map((band) => (
              <div key={band.label} className="bp-card p-3">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-bold">
                    {band.label}{' '}
                    <span className="font-normal text-slate-500 tabular-nums">
                      said {band.mean_confidence}% sure
                    </span>
                  </span>
                  <span className="text-slate-600 tabular-nums">
                    right {band.accuracy}% of {band.count}
                  </span>
                </div>
                <div className="relative mt-2 h-2.5 rounded-full bg-slate-100">
                  <div
                    className={`h-full rounded-full ${
                      (band.accuracy ?? 0) + 10 < (band.mean_confidence ?? 0)
                        ? 'bg-amber-500'
                        : 'bg-brand'
                    }`}
                    style={{ width: `${band.accuracy ?? 0}%` }}
                  />
                  <span
                    aria-hidden="true"
                    className="absolute top-[-3px] h-[17px] w-0.5 bg-ink"
                    style={{ left: `${band.mean_confidence ?? 0}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            The line marks the certainty claimed; the bar is how often it was
            right. A bar short of the line is overconfidence in that band.
          </p>
        </>
      )}
    </section>
  )
}

function Rate({ value, suffix }: { value: number | null; suffix?: string }) {
  if (value === null) {
    return <span className="text-sm font-normal text-slate-500">Not enough yet</span>
  }
  return (
    <>
      {value}%{suffix ? <span className="text-sm font-normal"> {suffix}</span> : null}
    </>
  )
}

export function StatsScreen() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <Banner kind="error">{error}</Banner>
      </div>
    )
  }
  if (!stats) return null

  const belowSample = stats.resolved_mixed_mode < stats.min_sample

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <h1 className="text-2xl font-bold">My Progress</h1>
      <p className="mt-1 text-ink-muted">
        These are verification capabilities, not concept mastery. Topic Mastery
        lives in its own NxtWave system.
      </p>

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard
          label="Investigation Score"
          value={stats.investigation_score.toFixed(0)}
          hint="Mean of completed attempts"
        />
        <StatCard
          label="First-judgment accuracy"
          value={<Rate value={stats.first_judgment_accuracy} />}
        />
        <StatCard
          label="False-alarm rate"
          value={<Rate value={stats.false_alarm_rate} />}
          hint="Valid artifacts challenged"
        />
        <StatCard
          label="Missed-failure rate"
          value={<Rate value={stats.missed_failure_rate} />}
          hint="Flawed artifacts approved"
        />
      </div>

      {belowSample && (
        <div className="mt-4">
          <Banner kind="info">
            {stats.resolved_mixed_mode} of {stats.min_sample} resolved
            investigations needed before rates are reported. Percentages from a
            handful of attempts are noise, so they are withheld rather than
            shown.
          </Banner>
        </div>
      )}

      {/* Three-way judgment matrix (PRD v0.2 section 15.1) */}
      <section className="mt-8">
        <h2 className="text-lg font-bold">Judgment matrix</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Rows are what the artifact actually was; columns are what you decided.
          The goal is not maximum skepticism — it is calibrated trust.
        </p>
        <div className="bp-scrollx bp-card mt-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-page text-left">
                <th className="px-4 py-2.5 font-bold">Actually</th>
                {JUDGMENTS.map((j) => (
                  <th key={j} className="px-4 py-2.5 font-bold">
                    {JUDGMENT_LABEL[j]}
                  </th>
                ))}
                <th className="px-4 py-2.5 font-bold">Total</th>
              </tr>
            </thead>
            <tbody>
              {stats.judgment_matrix.map((row) => (
                <tr
                  key={row.truth_state}
                  className="border-b border-slate-100 last:border-0"
                >
                  <td className="px-4 py-2.5 font-normal">
                    {TRUTH_LABEL[row.truth_state]}
                  </td>
                  {JUDGMENTS.map((j) => {
                    const right = CORRECT_FOR[row.truth_state] === j
                    const n = row.judgments[j] ?? 0
                    return (
                      <td
                        key={j}
                        className={`px-4 py-2.5 tabular-nums ${
                          right && n > 0
                            ? 'font-bold text-verified'
                            : n > 0
                              ? 'text-needs-evidence'
                              : 'text-slate-400'
                        }`}
                      >
                        {n}
                        {right && <span className="ml-1 text-[10px]">correct</span>}
                      </td>
                    )
                  })}
                  <td className="px-4 py-2.5 tabular-nums font-bold">
                    {row.total}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <CalibrationSection calibration={stats.calibration} />

      <section className="mt-8">
        <h2 className="text-lg font-bold">Investigation ledger</h2>
        <div className="bp-card mt-4 divide-y divide-slate-100">
          {(
            [
              ['Investigations resolved', stats.claims_investigated],
              ['Counted toward trust metrics', stats.resolved_mixed_mode],
              ['Failures correctly found', stats.failures_found],
              ['Valid artifacts correctly approved', stats.correct_approvals],
              [
                'Insufficient information correctly identified',
                stats.correct_insufficient,
              ],
              ['Strong evidence submitted', stats.strong_evidence],
              ['Completed independently', stats.independent_completions],
              ['Completed with guidance', stats.assisted_attempts],
            ] as [string, number][]
          ).map(([label, value]) => (
            <div
              key={label}
              className="flex items-center justify-between px-5 py-2.5"
            >
              <span className="text-sm">{label}</span>
              <span className="font-bold tabular-nums">{value}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-bold">Verification skills</h2>
        <div className="bp-card mt-4 space-y-4 p-5">
          {Object.entries(stats.verification_skills).map(([key, value]) => (
            <SkillBar
              key={key}
              label={SKILL_LABELS[key] ?? key.replace(/_/g, ' ')}
              value={value}
            />
          ))}
        </div>
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-bold">Score components</h2>
        <p className="mt-1 text-sm text-ink-muted">
          Mean across completed investigations, out of 100 total.
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {Object.entries(stats.score_components).map(([k, v]) => (
            <StatCard key={k} label={SCORE_LABELS[k] ?? k} value={v.toFixed(0)} />
          ))}
        </div>
      </section>

      {stats.achievements.length > 0 && (
        <section className="mt-8 mb-4">
          <h2 className="text-lg font-bold">Achievements</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {stats.achievements.map((a) => {
              const [title, ...rest] = a.split(' - ')
              return (
                <div key={a} className="bp-card p-4">
                  <div className="text-sm font-bold text-brand-hover">{title}</div>
                  <div className="mt-0.5 text-xs text-ink-muted">
                    {rest.join(' - ')}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}
