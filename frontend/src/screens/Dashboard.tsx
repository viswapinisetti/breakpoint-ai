/** Student dashboard (PRD sections 34-36). */

import { useEffect, useState } from 'react'
import {
  api,
  type ChallengeCard,
  type Stats,
  type Subject,
  type HistoryEntry,
} from '../api'
import {
  Banner,
  ConfidenceBadge,
  DifficultyIndicator,
  Spinner,
  StatCard,
} from '../components/ui'

interface Props {
  onInvestigate: (challengeId: string) => void
  onExplore: () => void
  onStats: () => void
}

export function Dashboard({ onInvestigate, onExplore, onStats }: Props) {
  const [daily, setDaily] = useState<ChallengeCard | null>(null)
  const [resume, setResume] = useState<ChallengeCard[]>([])
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Settled, not all. These five panels are independent, and with
    // `Promise.all` a single failing endpoint discarded the other four
    // results as well - one 500 on the resume list blanked the daily
    // challenge, the subject grid, the stats and the history, which reads as
    // "there is no content" rather than "one request failed".
    Promise.allSettled([
      api.daily(),
      api.continueList(),
      api.subjects(),
      api.stats(),
      api.history(),
    ])
      .then(([d, c, s, st, h]) => {
        if (d.status === 'fulfilled') setDaily(d.value)
        if (c.status === 'fulfilled') setResume(c.value)
        if (s.status === 'fulfilled') setSubjects(s.value)
        if (st.status === 'fulfilled') setStats(st.value)
        if (h.status === 'fulfilled') setHistory(h.value)

        // Name what actually broke. A generic message sends people looking at
        // the wrong thing, which is exactly what happened here.
        const failed = (
          [
            ["today's challenge", d],
            ['your in-progress investigations', c],
            ['the subject catalog', s],
            ['your statistics', st],
            ['your history', h],
          ] as const
        ).filter(([, r]) => r.status === 'rejected')

        if (failed.length > 0) {
          setError(
            `Could not load ${failed
              .map(([label]) => label)
              .join(', ')}. Everything else on this page is current.`,
          )
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-16">
        <Spinner label="Loading your lab" />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {error && (
        <div className="mb-6">
          <Banner kind="error">{error}</Banner>
        </div>
      )}

      {/* Hero - Today's Breakpoint (PRD section 35) */}
      {daily ? (
        <section className="bp-banner relative overflow-hidden rounded-2xl p-8 text-white">
          <div className="relative z-10 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-2xl">
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-full bg-white/15 px-3 py-1 text-[11px] font-bold tracking-widest uppercase">
                  {daily.subject}
                </span>
                <span className="text-sm font-normal opacity-90">
                  {daily.subtopic || daily.topic}
                </span>
              </div>
              <h1 className="mt-4 text-2xl leading-snug font-bold md:text-3xl">
                Today&apos;s Breakpoint
              </h1>
              <p className="mt-3 text-[15px] leading-relaxed text-white/90">
                {daily.question}
              </p>
              <p className="mt-4 border-l-2 border-white/40 pl-3 text-sm italic text-white/80">
                Breakpoint AI states this artifact is correct.
              </p>
            </div>
            <div className="flex shrink-0 flex-col items-start gap-4 md:items-end">
              <ConfidenceBadge value={daily.simulated_confidence} />
              <button
                onClick={() => onInvestigate(daily.id)}
                className="bp-btn rounded-[10px] bg-white px-6 py-3 text-brand-hover hover:bg-brand-soft"
              >
                INVESTIGATE →
              </button>
            </div>
          </div>
        </section>
      ) : (
        <Banner kind="warn">
          No published challenges yet. Run the content seeder in the backend.
        </Banner>
      )}

      {/* Evidence stats (PRD section 36.4) - explicitly not mastery */}
      {stats && (
        <section className="mt-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-bold">Your investigations</h2>
            <button
              onClick={onStats}
              className="text-sm font-bold text-brand hover:text-brand-hover"
            >
              Full profile →
            </button>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            These measure verification behaviour, not topic mastery.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
            <StatCard
              label="Investigations"
              value={stats.claims_investigated}
            />
            <StatCard label="Failures found" value={stats.failures_found} />
            <StatCard
              label="Valid approvals"
              value={stats.correct_approvals}
              hint="Correctly trusted"
            />
            <StatCard
              label="Insufficient info"
              value={stats.correct_insufficient}
              hint="Correctly identified"
            />
            <StatCard
              label="Strong evidence"
              value={stats.strong_evidence}
            />
            <StatCard
              label="Practice streak"
              value={`${stats.streak_days}d`}
              hint={stats.streak_days > 0 ? 'Keep it going' : 'Start today'}
            />
          </div>
        </section>
      )}

      {/* Continue investigation (PRD section 36.2) */}
      {resume.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-bold">Continue Investigation</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {resume.map((c) => (
              <button
                key={c.id}
                onClick={() => onInvestigate(c.id)}
                className="bp-card p-5 text-left transition hover:border-brand"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[11px] font-bold tracking-widest text-slate-500 uppercase">
                    {c.subject} · {c.subtopic || c.topic}
                  </span>
                  <DifficultyIndicator level={c.difficulty} />
                </div>
                <p className="mt-2 line-clamp-2 text-sm text-slate-700">
                  {c.question}
                </p>
                <span className="mt-3 inline-block text-sm font-bold text-brand">
                  Resume →
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Explore subjects (PRD section 36.3) */}
      <section className="mt-8">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-bold">Explore Subjects</h2>
          <button
            onClick={onExplore}
            className="text-sm font-bold text-brand hover:text-brand-hover"
          >
            All {subjects.length} subjects →
          </button>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-5">
          {subjects.slice(0, 10).map((s) => (
            <button
              key={s.key}
              onClick={onExplore}
              className="bp-card p-4 text-left transition hover:border-brand"
            >
              <div className="text-sm font-bold">{s.name}</div>
              <div className="mt-1 text-xs text-slate-500">
                {s.challenge_count > 0
                  ? `${s.challenge_count} challenge${s.challenge_count === 1 ? '' : 's'}`
                  : 'Coming deeper soon'}
              </div>
              {s.tier === 'A' && (
                <div className="mt-2 inline-block rounded bg-brand-soft px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-brand-hover uppercase">
                  Deep
                </div>
              )}
            </button>
          ))}
        </div>
      </section>

      {/* Failure categories encountered (PRD section 36.7) */}
      {stats && Object.keys(stats.failure_categories).length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-bold">Failure Categories Encountered</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(stats.failure_categories).map(([label, count]) => (
              <span
                key={label}
                className="bp-card px-3 py-1.5 text-sm"
              >
                {label}
                <span className="ml-2 tabular-nums text-slate-500">{count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {/* Recent breakpoints (PRD section 36.6) */}
      {history.length > 0 && (
        <section className="mt-8 mb-4">
          <h2 className="text-lg font-bold">Recent Breakpoints</h2>
          <div className="bp-card mt-4 divide-y divide-slate-100">
            {history.slice(0, 8).map((h) => (
              <div
                key={h.attempt_id}
                className="flex items-center justify-between gap-4 px-5 py-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-normal">
                    {h.subtopic || h.topic}
                  </div>
                  <div className="truncate text-xs text-slate-500">
                    {h.question}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  {h.judged_correctly !== null && (
                    <span
                      className={`text-xs font-bold ${
                        h.judged_correctly ? 'text-emerald-600' : 'text-amber-600'
                      }`}
                    >
                      {h.judged_correctly ? '✓ Correct call' : '! Misjudged'}
                    </span>
                  )}
                  {h.status === 'completed' ? (
                    <span className="text-sm font-bold tabular-nums">
                      {h.score.toFixed(0)}
                    </span>
                  ) : (
                    <button
                      onClick={() => onInvestigate(h.challenge_id)}
                      className="text-xs font-bold text-brand"
                    >
                      Resume
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
