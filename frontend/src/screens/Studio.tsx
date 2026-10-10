/** Challenge Studio (PRD sections 55-58, 80, 108, 109).
 *
 * The content developer's workspace: describe what you want, watch the funnel,
 * review what survived, and publish. The review pane deliberately shows the
 * *student view* alongside the solution, because the question a reviewer is
 * really answering is "is this fair and findable from what the student sees?"
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ApiError,
  staffAuth,
  studio,
  type AdminChallengeDetail,
  type AdminChallengeRow,
  type GenerationJob,
  type QueueCounts,
  type StudioAnalytics,
  type ReviewItem,
  type StudioReport,
  type Subject,
  type Template,
  api,
} from '../api'
import { Banner, DifficultyIndicator, Spinner, VerificationBadge } from '../components/ui'

type Tab =
  | 'generate'
  | 'review'
  | 'published'
  | 'appeals'
  | 'reports'
  | 'analytics'

const TABS: { key: Tab; label: string }[] = [
  { key: 'generate', label: 'Generate' },
  { key: 'review', label: 'Review Queue' },
  { key: 'published', label: 'Published' },
  { key: 'appeals', label: 'Appeals & Review' },
  { key: 'reports', label: 'Reports' },
  { key: 'analytics', label: 'Analytics' },
]

const STATUS_STYLE: Record<string, string> = {
  published: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  approved: 'bg-blue-50 text-blue-700 border-blue-200',
  auto_validated: 'bg-brand-soft text-brand-hover border-blue-200',
  human_reviewed: 'bg-violet-50 text-violet-700 border-violet-200',
  generated: 'bg-slate-100 text-slate-600 border-slate-200',
  flagged: 'bg-amber-50 text-amber-700 border-amber-200',
  retired: 'bg-slate-100 text-slate-500 border-slate-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-[11px] font-bold tracking-wide uppercase ${
        STATUS_STYLE[status] ?? 'bg-slate-100 text-slate-600 border-slate-200'
      }`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}

type Access = 'checking' | 'granted' | 'locked'

export function Studio() {
  const [tab, setTab] = useState<Tab>('review')
  const [counts, setCounts] = useState<QueueCounts | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState('')
  // The backend decides whether the Studio needs a token: it is open in
  // development and returns 403 once BREAKPOINT_ADMIN_TOKEN is set. The first
  // counts call doubles as that check.
  const [access, setAccess] = useState<Access>('checking')
  const [tokenRejected, setTokenRejected] = useState(false)

  const refreshCounts = useCallback(() => {
    studio
      .counts()
      .then((c) => {
        setCounts(c)
        setAccess('granted')
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 403) {
          // A stored token that stops working (rotated, mistyped) is dropped
          // so the form asks again instead of failing on every call.
          setTokenRejected(staffAuth.hasToken())
          staffAuth.clearToken()
          setAccess('locked')
          return
        }
        setAccess('granted')
        setError(e.message)
      })
  }, [])

  useEffect(refreshCounts, [refreshCounts])

  const unlock = (token: string) => {
    staffAuth.setToken(token)
    setTokenRejected(false)
    setAccess('checking')
    refreshCounts()
  }

  const lock = () => {
    staffAuth.clearToken()
    setCounts(null)
    setAccess('checking')
    refreshCounts()
  }

  if (access === 'checking') {
    return (
      <div className="mx-auto max-w-7xl px-6 py-16">
        <Spinner label="Opening the Studio" />
      </div>
    )
  }

  if (access === 'locked') {
    return <StudioAccess rejected={tokenRejected} onSubmit={unlock} />
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Challenge Studio</h1>
          <p className="mt-1 text-slate-600">
            Generate candidates, review what survives the pipeline, publish what
            earns it.
          </p>
        </div>
        {counts && (
          <div className="flex gap-5 text-sm">
            <div>
              <div className="text-[11px] tracking-wider text-slate-500 uppercase">
                In review
              </div>
              <div className="text-xl font-bold tabular-nums">
                {counts.in_review}
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-wider text-slate-500 uppercase">
                Published
              </div>
              <div className="text-xl font-bold tabular-nums">
                {counts.published}
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-wider text-slate-500 uppercase">
                Awaiting review
              </div>
              <div className="text-xl font-bold tabular-nums">
                {counts.reviews}
              </div>
            </div>
            <div>
              <div className="text-[11px] tracking-wider text-slate-500 uppercase">
                Reports
              </div>
              <div className="text-xl font-bold tabular-nums">
                {counts.reports}
              </div>
            </div>
            {staffAuth.hasToken() && (
              <button
                onClick={lock}
                className="self-center text-xs font-bold text-slate-500 hover:text-brand-hover"
              >
                Lock Studio
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="mt-4">
          <Banner kind="error" onDismiss={() => setError('')}>
            {error}
          </Banner>
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => {
              setTab(t.key)
              setSelected(null)
            }}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-bold transition ${
              tab === t.key
                ? 'border-brand text-brand-hover'
                : 'border-transparent text-slate-500 hover:text-brand-hover'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === 'generate' && (
          <GenerateTab counts={counts} onDone={refreshCounts} />
        )}
        {(tab === 'review' || tab === 'published') && (
          <QueueTab
            key={tab}
            published={tab === 'published'}
            selected={selected}
            onSelect={setSelected}
            onChanged={refreshCounts}
          />
        )}
        {tab === 'appeals' && <ReviewsTab onChanged={refreshCounts} />}
        {tab === 'reports' && <ReportsTab />}
        {tab === 'analytics' && <AnalyticsTab />}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------- access */

function StudioAccess({
  rejected,
  onSubmit,
}: {
  rejected: boolean
  onSubmit: (token: string) => void
}) {
  const [token, setToken] = useState('')
  return (
    <div className="mx-auto max-w-md px-6 py-16">
      <h1 className="text-2xl font-bold">Challenge Studio</h1>
      <p className="mt-2 text-slate-600">
        This Studio is protected. Enter the staff access token from your
        Breakpoint administrator. It is kept for this browser tab only.
      </p>
      <form
        className="mt-6 space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (token.trim()) onSubmit(token)
        }}
      >
        <label className="block">
          <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
            Access token
          </span>
          <input
            type="password"
            autoComplete="off"
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>
        {rejected && (
          <Banner kind="error">
            That token was not accepted. Check it and try again.
          </Banner>
        )}
        <button
          type="submit"
          disabled={!token.trim()}
          className="bp-btn bp-btn-primary"
        >
          Open Studio
        </button>
      </form>
    </div>
  )
}

/* ------------------------------------------------------------------ generate */

function GenerateTab({
  counts,
  onDone,
}: {
  counts: QueueCounts | null
  onDone: () => void
}) {
  const aiConfigured = counts?.ai_configured ?? false
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [jobs, setJobs] = useState<GenerationJob[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const pollRef = useRef<number | null>(null)

  // An empty `topic` means "the subject's first topic" (see `topic` below).
  // The server rejects any topic not registered for the subject.
  const [form, setForm] = useState({
    subject: 'aptitude',
    topic: '',
    concept: '',
    difficulty: '3',
    count: 3,
    desired_failure: '',
    make_correct: false,
  })

  const loadJobs = useCallback(() => {
    studio.jobs().then(setJobs).catch(() => undefined)
  }, [])

  useEffect(() => {
    api.subjects().then(setSubjects).catch(() => undefined)
    studio.templates().then(setTemplates).catch(() => undefined)
    loadJobs()
  }, [loadJobs])

  // Poll while any job is unfinished, then stop. Generation is slow (four
  // model calls per candidate), so the queue must not look frozen.
  useEffect(() => {
    const active = jobs.some((j) => j.status === 'queued' || j.status === 'running')
    if (active && pollRef.current === null) {
      pollRef.current = window.setInterval(loadJobs, 3000)
    } else if (!active && pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [jobs, loadJobs])

  const subject = subjects.find((s) => s.key === form.subject)

  // Always one of the chosen subject's registered topics: the stored choice
  // if it belongs to this subject, otherwise the subject's first topic. That
  // covers first load and a template switching the subject underneath it.
  const topic = subject?.topics.some((t) => t.name === form.topic)
    ? form.topic
    : (subject?.topics[0]?.name ?? '')

  async function submit() {
    if (!form.concept.trim()) {
      setNotice('Give the concept you want challenges for.')
      return
    }
    if (!topic) {
      setNotice('Choose a topic.')
      return
    }
    setBusy(true)
    setNotice('')
    try {
      await studio.generate({ ...form, topic, challenge_mode: 'trust_or_challenge' })
      loadJobs()
      onDone()
    } catch (e) {
      setNotice((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function applyTemplate(t: Template) {
    setForm((f) => ({
      ...f,
      desired_failure: t.desired_failure,
      difficulty: t.difficulty,
      make_correct: t.make_correct,
      subject: t.applicable_subjects.includes(f.subject)
        ? f.subject
        : (t.applicable_subjects[0] ?? f.subject),
    }))
    setNotice(`Applied template "${t.name}".`)
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1.1fr]">
      <div className="space-y-5">
        {aiConfigured && counts && (
          <div className="bp-card p-4">
            <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
              Active provider
            </div>
            <div className="mt-1 text-sm font-bold">{counts.ai_provider}</div>
            <dl className="mt-2 space-y-0.5 text-xs text-slate-600">
              {Object.entries(counts.ai_models).map(([role, model]) => (
                <div key={role} className="flex justify-between gap-3">
                  <dt className="capitalize">{role}</dt>
                  <dd className="font-mono">{model}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {!aiConfigured && (
          <Banner kind="warn">
            Generation needs an AI provider. Set{' '}
            <code>BREAKPOINT_OPENROUTER_API_KEY</code> in{' '}
            <code>backend/.env</code> and restart the API. Reviewing, editing
            and publishing existing challenges all work without one.
          </Banner>
        )}

        <div className="bp-card p-5">
          <h2 className="text-sm font-bold">New generation run</h2>
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                Subject
              </span>
              <select
                value={form.subject}
                onChange={(e) => {
                  const next = subjects.find((s) => s.key === e.target.value)
                  setForm({
                    ...form,
                    subject: e.target.value,
                    topic: next?.topics[0]?.name ?? '',
                  })
                }}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                {subjects.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.name}
                    {s.tier === 'A' ? ' (deep)' : ''}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                Topic
              </span>
              <select
                value={topic}
                onChange={(e) => setForm({ ...form, topic: e.target.value })}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              >
                {(subject?.topics ?? []).map((t) => (
                  <option key={t.key} value={t.name}>
                    {t.number}. {t.name}
                    {t.challenge_count > 0 ? ` (${t.challenge_count})` : ''}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                Concept
              </span>
              <input
                value={form.concept}
                onChange={(e) => setForm({ ...form, concept: e.target.value })}
                placeholder="Successive percentage change"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                  Difficulty
                </span>
                <select
                  value={form.difficulty}
                  onChange={(e) =>
                    setForm({ ...form, difficulty: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                >
                  <option value="1">1 — Visible failure</option>
                  <option value="2">2 — One-step hidden</option>
                  <option value="3">3 — Plausible</option>
                  <option value="4">4 — Expert trap</option>
                  <option value="5">5 — Adversarial</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                  Count
                </span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={form.count}
                  onChange={(e) =>
                    setForm({ ...form, count: Number(e.target.value) })
                  }
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                />
              </label>
            </div>

            <label className="block">
              <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
                Desired failure
              </span>
              <input
                value={form.desired_failure}
                onChange={(e) =>
                  setForm({ ...form, desired_failure: e.target.value })
                }
                placeholder="Leave blank to rotate across failure types"
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
              />
            </label>

            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.make_correct}
                onChange={(e) =>
                  setForm({ ...form, make_correct: e.target.checked })
                }
              />
              <span className="text-sm">
                Generate <strong>correct</strong> artifacts (false-failure
                challenges)
              </span>
            </label>

            {notice && <Banner kind="info">{notice}</Banner>}

            <div className="flex items-center gap-3 pt-1">
              <button
                onClick={submit}
                disabled={busy || !aiConfigured}
                className="bp-btn bp-btn-primary"
              >
                Generate
              </button>
              <span className="text-xs text-slate-500">
                ~{form.count * 4} model calls
              </span>
              {busy && <Spinner label="Queueing" />}
            </div>
          </div>
        </div>

        <div className="bp-card p-5">
          <h2 className="text-sm font-bold">Templates</h2>
          <p className="mt-1 text-xs text-slate-500">
            Saved authoring patterns that apply across subjects.
          </p>
          <div className="mt-3 space-y-2">
            {templates.map((t) => (
              <button
                key={t.key}
                onClick={() => applyTemplate(t)}
                className="w-full rounded-xl border border-slate-200 p-3 text-left transition hover:border-brand"
              >
                <div className="text-sm font-bold">{t.name}</div>
                <div className="mt-0.5 text-xs text-slate-600">
                  {t.description}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {t.applicable_subjects.map((s) => (
                    <span
                      key={s}
                      className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <h2 className="text-sm font-bold">Generation queue</h2>
        {jobs.length === 0 && (
          <p className="rounded-xl bg-page px-4 py-6 text-center text-sm text-slate-500">
            No generation runs yet.
          </p>
        )}
        {jobs.map((job) => (
          <div key={job.id} className="bp-card p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-bold">
                #{job.id} · {String(job.params.concept ?? '')}
              </div>
              <span
                className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${
                  job.status === 'completed'
                    ? 'bg-emerald-50 text-emerald-700'
                    : job.status === 'failed'
                      ? 'bg-red-50 text-red-700'
                      : 'bg-amber-50 text-amber-700'
                }`}
              >
                {job.status}
              </span>
            </div>

            {/* The funnel, stated honestly (PRD section 57) */}
            <div className="mt-2 text-xs text-slate-600">
              {job.requested} generated → <strong>{job.survived} survived</strong>,{' '}
              {job.rejected} rejected
            </div>
            {job.error && (
              <p className="mt-2 text-xs text-red-700">{job.error}</p>
            )}
            {job.funnel.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {job.funnel.map((f) => (
                  <li key={f.index} className="text-xs">
                    <span
                      className={
                        f.stage === 'publish'
                          ? 'font-bold text-emerald-700'
                          : 'font-bold text-amber-700'
                      }
                    >
                      #{f.index} {f.stage === 'publish' ? 'survived' : `died at ${f.stage}`}
                    </span>
                    {f.quality !== undefined && f.stage === 'publish' && (
                      <span className="text-slate-500"> · quality {f.quality}/10</span>
                    )}
                    {f.reasons.map((r, i) => (
                      <div key={i} className="pl-3 text-slate-500">
                        — {r}
                      </div>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------- queue */

function QueueTab({
  published,
  selected,
  onSelect,
  onChanged,
}: {
  published: boolean
  selected: string | null
  onSelect: (id: string | null) => void
  onChanged: () => void
}) {
  const [rows, setRows] = useState<AdminChallengeRow[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    studio
      .queue(published ? 'published' : undefined)
      .then(setRows)
      .finally(() => setLoading(false))
  }, [published])

  useEffect(load, [load])

  if (loading) return <Spinner label="Loading queue" />

  if (rows.length === 0) {
    return (
      <Banner kind="info">
        {published
          ? 'Nothing published yet.'
          : 'Review queue is empty — every generated challenge has been dealt with.'}
      </Banner>
    )
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_1.3fr]">
      <div className="space-y-3">
        {rows.map((r) => (
          <button
            key={r.challenge_id}
            onClick={() => onSelect(r.challenge_id)}
            className={`bp-card w-full p-4 text-left transition ${
              selected === r.challenge_id
                ? 'border-brand ring-1 ring-brand'
                : 'hover:border-brand'
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={r.status} />
              {r.failed_validators > 0 && (
                <VerificationBadge state="exposed">
                  {r.failed_validators} failing validator
                  {r.failed_validators === 1 ? '' : 's'}
                </VerificationBadge>
              )}
              {r.reports > 0 && (
                <VerificationBadge state="caution">
                  {r.reports} report{r.reports === 1 ? '' : 's'}
                </VerificationBadge>
              )}
            </div>
            <p className="mt-2 line-clamp-2 text-sm">{r.question}</p>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
              <span className="font-mono">{r.challenge_id}</span>
              <DifficultyIndicator level={r.difficulty} />
              <span>{r.failure_label || r.truth_state.replace(/_/g, ' ')}</span>
              {r.quality_score > 0 && <span>Q {r.quality_score.toFixed(1)}</span>}
              <span>v{r.version}</span>
            </div>
          </button>
        ))}
      </div>

      <div>
        {selected ? (
          <ReviewPane
            challengeId={selected}
            onChanged={() => {
              load()
              onChanged()
            }}
            onClose={() => onSelect(null)}
          />
        ) : (
          <p className="rounded-xl bg-page px-4 py-10 text-center text-sm text-slate-500">
            Select a challenge to review it.
          </p>
        )}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- review pane */

function ReviewPane({
  challengeId,
  onChanged,
  onClose,
}: {
  challengeId: string
  onChanged: () => void
  onClose: () => void
}) {
  const [detail, setDetail] = useState<AdminChallengeDetail | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [showStudent, setShowStudent] = useState(true)

  const load = useCallback(() => {
    studio
      .detail(challengeId)
      .then((d) => {
        setDetail(d)
        setDraft(JSON.stringify(d.body, null, 2))
      })
      .catch((e) => setNotice(e.message))
  }, [challengeId])

  useEffect(load, [load])

  if (!detail) return <Spinner label="Loading challenge" />

  const { row, student_view: sv, validations, versions } = detail
  const failing = validations.filter((v) => !v.passed)

  async function move(status: string) {
    setBusy(true)
    setNotice('')
    try {
      await studio.transition(challengeId, status, note)
      setNote('')
      load()
      onChanged()
    } catch (e) {
      setNotice(
        e instanceof ApiError && e.status === 409
          ? e.message
          : (e as Error).message,
      )
    } finally {
      setBusy(false)
    }
  }

  async function saveEdit() {
    setBusy(true)
    setNotice('')
    try {
      const parsed = JSON.parse(draft)
      const updated = await studio.edit(challengeId, parsed, note || 'edited')
      setDetail(updated)
      setDraft(JSON.stringify(updated.body, null, 2))
      setEditing(false)
      setNotice(
        updated.row.failed_validators > 0
          ? 'Saved, but the challenge no longer validates — it has been withdrawn from students.'
          : 'Saved and re-validated.',
      )
      onChanged()
    } catch (e) {
      setNotice(
        e instanceof SyntaxError
          ? `Invalid JSON: ${e.message}`
          : (e as Error).message,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bp-card p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={row.status} />
            <span className="font-mono text-xs text-slate-500">
              {row.challenge_id} · v{row.version}
            </span>
          </div>
          <h2 className="mt-2 text-sm font-bold">
            {row.subject} · {row.subtopic || row.topic}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-700"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      {notice && (
        <div className="mt-3">
          <Banner
            kind={notice.startsWith('Saved and') ? 'success' : 'warn'}
            onDismiss={() => setNotice('')}
          >
            {notice}
          </Banner>
        </div>
      )}

      {/* Validators — the machine check, shown before any human judgment */}
      <section className="mt-4">
        <h3 className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
          Deterministic validation
        </h3>
        <div className="mt-2 space-y-1.5">
          {validations.map((v) => (
            <div
              key={v.validator}
              className={`rounded-lg border px-3 py-2 text-xs ${
                v.passed
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-red-200 bg-red-50'
              }`}
            >
              <span className="font-bold">
                {v.passed ? '✓' : '✕'} {v.validator}
              </span>
              <div className="mt-0.5 text-slate-600">{v.detail}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Student preview vs full solution */}
      <section className="mt-5">
        <div className="flex items-center justify-between">
          <h3 className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            {showStudent ? 'Student view' : 'Full challenge (solution visible)'}
          </h3>
          <button
            onClick={() => setShowStudent((s) => !s)}
            className="text-xs font-bold text-brand"
          >
            {showStudent ? 'Show solution' : 'Preview student view'}
          </button>
        </div>

        {showStudent ? (
          <div className="mt-2 rounded-xl border border-slate-200 p-4">
            <p className="text-sm font-normal">{sv.question}</p>
            <p className="mt-2 border-l-2 border-brand pl-3 text-sm italic">
              &ldquo;{sv.ai_claim}&rdquo;
            </p>
            <ol className="mt-3 space-y-1">
              {sv.ai_solution.map((s) => (
                <li key={s.index} className="flex gap-2 text-sm">
                  <span className="font-mono text-xs text-slate-400">
                    {s.index}
                  </span>
                  <span>{s.text}</span>
                </li>
              ))}
            </ol>
            <div className="mt-3 text-sm">
              <span className="font-bold">AI answer:</span>{' '}
              <span className="font-mono">{sv.ai_final_answer}</span>
              <span className="ml-3 text-xs text-slate-500">
                confidence {sv.simulated_confidence}%
              </span>
            </div>
          </div>
        ) : editing ? (
          <div className="mt-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={18}
              spellCheck={false}
              className="w-full rounded-xl border border-slate-200 p-3 font-mono text-xs"
            />
            <div className="mt-2 flex gap-2">
              <button
                onClick={saveEdit}
                disabled={busy}
                className="bp-btn bp-btn-primary"
              >
                Save &amp; re-validate
              </button>
              <button
                onClick={() => {
                  setEditing(false)
                  setDraft(JSON.stringify(detail.body, null, 2))
                }}
                className="bp-btn bp-btn-ghost"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-2">
            <pre className="bp-scrollx max-h-80 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-3 text-[11px] leading-relaxed">
              {draft}
            </pre>
            <button
              onClick={() => setEditing(true)}
              className="bp-btn bp-btn-ghost mt-2"
            >
              Edit
            </button>
          </div>
        )}
      </section>

      {/* Actions */}
      <section className="mt-5 border-t border-slate-100 pt-4">
        <label className="block">
          <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            Review note
          </span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Why are you making this decision?"
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
          />
        </label>

        {failing.length > 0 && (
          <p className="mt-2 text-xs text-red-700">
            This challenge cannot be published while a validator is failing.
          </p>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          {detail.allowed_transitions.map((t) => (
            <button
              key={t}
              onClick={() => move(t)}
              disabled={busy}
              className={`bp-btn ${
                t === 'published' || t === 'approved'
                  ? 'bp-btn-primary'
                  : 'bp-btn-ghost'
              }`}
            >
              {t.replace(/_/g, ' ')}
            </button>
          ))}
          {busy && <Spinner label="Applying" />}
        </div>
      </section>

      {/* Audit trail */}
      {versions.length > 0 && (
        <section className="mt-5 border-t border-slate-100 pt-4">
          <h3 className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
            History
          </h3>
          <ul className="mt-2 space-y-1">
            {versions.map((v) => (
              <li key={v.seq} className="text-xs text-slate-600">
                <span className="font-mono text-slate-400">#{v.seq}</span>{' '}
                <span className="font-bold">{v.status}</span> · {v.note}
                {v.author && <span className="text-slate-400"> — {v.author}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------- reports */

function ReportsTab() {
  const [reports, setReports] = useState<StudioReport[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    studio
      .reports()
      .then(setReports)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spinner label="Loading reports" />
  if (reports.length === 0)
    return <Banner kind="success">No student reports outstanding.</Banner>

  return (
    <div className="space-y-3">
      {reports.map((r) => (
        <div key={r.id} className="bp-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <VerificationBadge state="caution">{r.reason}</VerificationBadge>
            <StatusPill status={r.status} />
            <span className="font-mono text-xs text-slate-500">
              {r.challenge_id}
            </span>
          </div>
          <p className="mt-2 text-sm">{r.question}</p>
          {r.detail && (
            <p className="mt-1.5 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">
              &ldquo;{r.detail}&rdquo;
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

/* ----------------------------------------------------------------- analytics */

function AnalyticsTab() {
  const [data, setData] = useState<StudioAnalytics | null>(null)

  useEffect(() => {
    studio.analytics().then(setData).catch(() => undefined)
  }, [])

  if (!data) return <Spinner label="Loading analytics" />

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="bp-card p-4">
          <div className="text-[11px] tracking-wider text-slate-500 uppercase">
            Published
          </div>
          <div className="text-2xl font-bold tabular-nums">{data.published}</div>
        </div>
        <div className="bp-card p-4">
          <div className="text-[11px] tracking-wider text-slate-500 uppercase">
            Subject coverage
          </div>
          <div className="text-2xl font-bold tabular-nums">
            {data.subjects_with_content}/{data.total_subjects}
          </div>
        </div>
        <div className="bp-card p-4">
          <div className="text-[11px] tracking-wider text-slate-500 uppercase">
            Evidence accepted
          </div>
          <div className="text-2xl font-bold tabular-nums">
            {data.evidence_acceptance_rate}%
          </div>
        </div>
        <div className="bp-card p-4">
          <div className="text-[11px] tracking-wider text-slate-500 uppercase">
            Model calls
          </div>
          <div className="text-2xl font-bold tabular-nums">
            {data.model_calls}
          </div>
          <div className="text-xs text-slate-500">
            {data.input_tokens.toLocaleString()} in ·{' '}
            {data.cached_tokens.toLocaleString()} cached
          </div>
        </div>
      </div>

      <section>
        <h2 className="text-sm font-bold">Failure distribution</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(data.failure_distribution).map(([label, n]) => (
            <span key={label} className="bp-card px-3 py-1.5 text-sm">
              {label}
              <span className="ml-2 tabular-nums text-slate-500">{n}</span>
            </span>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-sm font-bold">Challenge performance</h2>
        <p className="mt-1 text-xs text-slate-500">
          Sorted by detection rate — the hardest to detect first. A very low rate
          may mean the failure is unfair rather than merely subtle.
        </p>
        {data.challenges.length === 0 ? (
          <div className="mt-3">
            <Banner kind="info">
              No attempts recorded yet, so there is nothing to measure.
            </Banner>
          </div>
        ) : (
          <div className="bp-scrollx bp-card mt-3">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-page text-left">
                  <th className="px-4 py-2.5 font-bold">Challenge</th>
                  <th className="px-4 py-2.5 font-bold">Failure</th>
                  <th className="px-4 py-2.5 font-bold">Attempts</th>
                  <th className="px-4 py-2.5 font-bold">Detection</th>
                  <th className="px-4 py-2.5 font-bold">Completion</th>
                  <th className="px-4 py-2.5 font-bold">Avg hints</th>
                </tr>
              </thead>
              <tbody>
                {data.challenges.map((c) => (
                  <tr
                    key={c.challenge_id}
                    className="border-b border-slate-100 last:border-0"
                  >
                    <td className="px-4 py-2.5">
                      <div className="font-normal">{c.subtopic}</div>
                      <div className="font-mono text-xs text-slate-400">
                        {c.challenge_id}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-xs">{c.failure_label}</td>
                    <td className="px-4 py-2.5 tabular-nums">{c.attempts}</td>
                    <td className="px-4 py-2.5 tabular-nums">
                      <span
                        className={
                          c.detection_rate < 30
                            ? 'font-bold text-amber-700'
                            : ''
                        }
                      >
                        {c.detection_rate}%
                      </span>
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">
                      {c.completion_rate}%
                    </td>
                    <td className="px-4 py-2.5 tabular-nums">{c.avg_hints}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}


/* ----------------------------------------------------------------- reviews */

const OUTCOMES: { key: string; label: string; blurb: string }[] = [
  {
    key: 'accept',
    label: 'Accept the evidence',
    blurb: 'Credit the learner and update the score.',
  },
  {
    key: 'uphold',
    label: 'Uphold the decision',
    blurb: 'The original evaluation stands.',
  },
  {
    key: 'quarantine',
    label: 'Quarantine the challenge',
    blurb: 'The defect is in the content. Withdraws the attempt rather than marking it wrong.',
  },
]

function ReviewsTab({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<ReviewItem[]>([])
  const [loading, setLoading] = useState(true)
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [notice, setNotice] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    studio
      .reviews()
      .then(setItems)
      .catch((e) => setNotice(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  async function resolve(item: ReviewItem, outcome: string) {
    setBusy(item.id)
    setNotice('')
    try {
      await studio.resolveReview(item.kind, item.id, outcome, notes[item.id] ?? '')
      load()
      onChanged()
    } catch (e) {
      setNotice((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <Spinner label="Loading review queue" />
  if (items.length === 0)
    return (
      <Banner kind="success">
        Nothing awaiting review. Appeals and submissions the evaluator could not
        settle appear here.
      </Banner>
    )

  return (
    <div className="space-y-4">
      {notice && (
        <Banner kind="error" onDismiss={() => setNotice('')}>
          {notice}
        </Banner>
      )}
      <p className="text-sm text-ink-muted">
        A learner whose submission is here has not been marked wrong. Resolve
        promptly — the target is two working days.
      </p>

      {items.map((item) => (
        <div key={`${item.kind}-${item.id}`} className="bp-card p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 text-[11px] font-bold tracking-wide uppercase ${
                item.kind === 'appeal'
                  ? 'border-amber-200 bg-amber-50 text-needs-evidence'
                  : 'border-blue-200 bg-brand-soft text-brand-hover'
              }`}
            >
              {item.kind === 'appeal' ? 'Learner appeal' : 'Evaluator unsure'}
            </span>
            <span className="font-mono text-xs text-slate-500">
              {item.challenge_id}
            </span>
            <span className="text-xs text-slate-500">
              actually {item.truth_state.replace(/_/g, ' ')} · learner said{' '}
              {item.learner_judgment.replace(/_/g, ' ')}
            </span>
          </div>

          <p className="mt-2 text-sm">{item.question}</p>

          <div className="mt-3 rounded-card bg-page px-4 py-3">
            <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
              {item.kind === 'appeal' ? 'Why they disagree' : 'Why it stalled'}
            </div>
            <p className="mt-1 text-sm">{item.reason}</p>
            {item.evaluator_feedback && (
              <p className="mt-2 text-sm text-ink-muted">
                Evaluator said: {item.evaluator_feedback}
              </p>
            )}
          </div>

          {/* The exact submission, so the reviewer judges what was judged. */}
          {item.cards.length > 0 && (
            <div className="mt-3">
              <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
                Submitted evidence
              </div>
              <div className="mt-2 space-y-2">
                {item.cards.map((c) => (
                  <div
                    key={c.ordinal}
                    className="rounded-card border border-slate-200 p-3 text-sm"
                  >
                    <div className="text-xs font-bold text-brand-hover">
                      {c.ordinal}. {c.type.replace(/_/g, ' ')}
                      {c.references_step ? ` · step ${c.references_step}` : ''}
                    </div>
                    <dl className="mt-1 space-y-0.5">
                      {Object.entries(c.payload)
                        .filter(([k]) => k !== 'type' && k !== 'references_step')
                        .map(([k, v]) => (
                          <div key={k} className="flex gap-2">
                            <dt className="text-xs text-slate-500 capitalize">
                              {k.replace(/_/g, ' ')}:
                            </dt>
                            <dd className="font-mono text-xs">{String(v)}</dd>
                          </div>
                        ))}
                    </dl>
                    {c.why_supports && (
                      <p className="mt-1 text-xs text-slate-700">
                        {c.why_supports}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <label className="mt-4 block">
            <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
              Resolution note
            </span>
            <input
              value={notes[item.id] ?? ''}
              onChange={(e) =>
                setNotes({ ...notes, [item.id]: e.target.value })
              }
              placeholder="What did you decide, and why?"
              className="mt-1 w-full rounded-control border border-slate-200 px-3 py-2 text-sm"
            />
          </label>

          <div className="mt-3 flex flex-wrap gap-2">
            {OUTCOMES.map((o) => (
              <button
                key={o.key}
                onClick={() => resolve(item, o.key)}
                disabled={busy === item.id}
                title={o.blurb}
                className={`bp-btn ${
                  o.key === 'accept' ? 'bp-btn-primary' : 'bp-btn-ghost'
                }`}
              >
                {o.label}
              </button>
            ))}
            {busy === item.id && <Spinner label="Resolving" />}
          </div>
        </div>
      ))}
    </div>
  )
}
