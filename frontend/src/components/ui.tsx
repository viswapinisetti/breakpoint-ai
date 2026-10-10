/** Reusable Breakpoint components (PRD section 91).
 *
 * Accessibility rule that shapes several of these: failure state is never
 * signalled by colour alone (PRD section 107), and no pre-verification surface
 * may use red, because red would reveal that the AI is wrong (PRD section 87).
 */

import type { ReactNode } from 'react'

export function ConfidenceBadge({ value }: { value: number }) {
  return (
    <div className="bp-banner inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-white">
      <span className="text-[11px] font-bold tracking-widest uppercase opacity-80">
        Scenario confidence
      </span>
      <span className="text-sm font-bold tabular-nums">{value}%</span>
      <span
        className="cursor-help text-xs opacity-70"
        title="Fictional confidence belonging to the AI character in this scenario. It is sampled independently of whether the artifact is correct, and carries no score weight."
        aria-label="Scenario confidence: fictional, independent of whether the artifact is correct"
      >
        ⓘ
      </span>
    </div>
  )
}

const DIFFICULTY_LABEL: Record<string, string> = {
  '1': 'Visible failure',
  '2': 'One-step hidden',
  '3': 'Plausible',
  '4': 'Expert trap',
  '5': 'Adversarial',
}

/** Names the challenge mode on a listing card - but only for the modes that
 *  ask for something other than a verdict.
 *
 *  Trust-or-Challenge is the default and covers most of the catalog, so
 *  labelling it would be noise on almost every card. Break-the-Tests wants a
 *  test and Which-AI-Is-Wrong wants an adjudication between two solutions,
 *  and a student choosing what to work on should know that before opening it.
 */
const MODE_BADGE: Record<string, string> = {
  break_the_tests: 'Break the tests',
  which_ai_is_wrong: 'Which AI is wrong',
  find_the_failure: 'Find the failure',
  prove_it: 'Prove it',
  repair_it: 'Repair it',
  ai_debate: 'AI debate',
}

export function ModeBadge({ mode }: { mode: string }) {
  const label = MODE_BADGE[mode]
  if (!label) return null
  return (
    <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[10px] font-bold tracking-wider text-brand-hover uppercase">
      {label}
    </span>
  )
}

export function DifficultyIndicator({ level }: { level: string }) {
  const filled = Number(level) || 1
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={DIFFICULTY_LABEL[level]}
    >
      <span className="flex gap-0.5" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            className={`h-1.5 w-3.5 rounded-full ${
              i <= filled ? 'bg-brand' : 'bg-slate-200'
            }`}
          />
        ))}
      </span>
      <span className="sr-only">
        Difficulty {filled} of 5: {DIFFICULTY_LABEL[level]}
      </span>
      <span className="text-xs text-slate-500">{DIFFICULTY_LABEL[level]}</span>
    </span>
  )
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: ReactNode
  hint?: string
}) {
  return (
    <div className="bp-card p-4">
      <div className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
        {label}
      </div>
      <div className="mt-1 text-2xl font-bold tabular-nums text-ink">
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

export function VerificationBadge({
  state,
  children,
}: {
  state: 'verified' | 'caution' | 'exposed' | 'neutral'
  children: ReactNode
}) {
  const styles = {
    verified: 'bg-emerald-50 text-verified border-emerald-200',
    caution: 'bg-amber-50 text-needs-evidence border-amber-200',
    exposed: 'bg-red-50 text-failure border-red-200',
    neutral: 'bg-brand-soft text-brand-hover border-blue-200',
  }[state]
  // PRD v0.2 section 7.2 rules out decorative ticks and crosses. Status is
  // carried by a word, not a glyph, which also satisfies the non-colour-only
  // requirement in section 7.3 without relying on symbol legibility.
  const prefix = {
    verified: 'Verified',
    caution: 'Needs evidence',
    exposed: 'Failure',
    neutral: 'Status',
  }[state]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-bold ${styles}`}
    >
      <span className="opacity-70">{prefix}:</span>
      {children}
    </span>
  )
}

export function Spinner({ label = 'Working' }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span
        className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-brand"
        aria-hidden="true"
      />
      <span role="status">{label}…</span>
    </span>
  )
}

export function Banner({
  kind,
  children,
  onDismiss,
}: {
  kind: 'info' | 'warn' | 'error' | 'success'
  children: ReactNode
  onDismiss?: () => void
}) {
  const styles = {
    info: 'bg-brand-soft border-blue-200 text-brand-hover',
    warn: 'bg-amber-50 border-amber-200 text-amber-800',
    error: 'bg-red-50 border-red-200 text-red-800',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  }[kind]
  return (
    <div
      className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${styles}`}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      <div className="flex-1">{children}</div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 opacity-60 hover:opacity-100"
          aria-label="Dismiss"
        >
          ✕
        </button>
      )}
    </div>
  )
}

export function SkillBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-bold tracking-wide text-slate-600 uppercase">
          {label}
        </span>
        <span className="text-xs tabular-nums text-slate-500">
          {value.toFixed(0)}
        </span>
      </div>
      <div
        className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100"
        role="meter"
        aria-valuenow={Math.round(value)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className="h-full rounded-full bg-brand transition-[width] duration-500"
          style={{ width: `${Math.max(2, Math.min(100, value))}%` }}
        />
      </div>
    </div>
  )
}

/** Renders a subject-supplied data artifact.
 *
 * Artifact payloads are deliberately free-form - the engine passes them
 * through untouched and the subject decides their shape (PRD section 50). So
 * this renders by *value shape* rather than by a fixed schema:
 *
 *   string                     mono text
 *   string[]                   a list
 *   { columns, rows }          a real table, whether given as arrays or as
 *                              the legacy comma/pipe-delimited strings
 *   nested object              recursed
 *
 * The alternative - a lookup keyed on artifact_type - means a new subject
 * renders blank, or worse, throws on an object it did not expect.
 */

type Scalar = string | number | boolean

function isScalar(v: unknown): v is Scalar {
  return (
    typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
  )
}

/** Pull a table out of a value, accepting both encodings. Returns null when
 *  the value is not table-shaped. */
function asTable(
  value: unknown,
): { caption: string; columns: string[]; rows: Scalar[][] } | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null
  }
  const record = value as Record<string, unknown>
  const { columns, rows } = record
  if (columns === undefined || rows === undefined) return null

  const caption =
    typeof record.title === 'string'
      ? record.title
      : typeof record.caption === 'string'
        ? record.caption
        : ''

  // Legacy encoding: "a,b,c" and "1,2|3,4".
  if (typeof columns === 'string' && typeof rows === 'string') {
    return {
      caption,
      columns: columns.split(','),
      rows: rows.split('|').map((r) => r.split(',')),
    }
  }
  if (Array.isArray(columns) && Array.isArray(rows)) {
    return {
      caption,
      columns: columns.map(String),
      rows: rows.map((row) =>
        Array.isArray(row) ? row.filter(isScalar) : [String(row)],
      ),
    }
  }
  return null
}

function Table({
  caption,
  columns,
  rows,
}: {
  caption: string
  columns: string[]
  rows: Scalar[][]
}) {
  return (
    <figure className="mt-4">
      {caption && (
        <figcaption className="mb-2 text-xs font-bold tracking-wide text-slate-500 uppercase">
          {caption}
        </figcaption>
      )}
      <div className="bp-scrollx bp-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-page">
              {columns.map((c) => (
                <th
                  key={c}
                  scope="col"
                  className="px-4 py-2.5 text-left font-bold text-ink"
                >
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-100 last:border-0">
                {row.map((cell, j) => (
                  <td
                    key={j}
                    className={`px-4 py-2.5 ${
                      j === 0 ? 'font-normal' : 'tabular-nums'
                    }`}
                  >
                    {String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}

/** One field of an artifact, rendered by the shape of its value. */
function ArtifactField({ name, value }: { name: string; value: unknown }) {
  const label = name.replace(/_/g, ' ')

  const table = asTable(value)
  if (table) return <Table {...table} />

  if (Array.isArray(value)) {
    return (
      <div className="px-4 py-2.5">
        <dt className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
          {label}
        </dt>
        <dd className="mt-1">
          <ul className="space-y-1">
            {value.map((item, i) => (
              <li key={i} className="flex gap-2 text-sm">
                <span aria-hidden className="text-slate-400">
                  &bull;
                </span>
                <span className="font-mono whitespace-pre-wrap">
                  {isScalar(item) ? String(item) : JSON.stringify(item)}
                </span>
              </li>
            ))}
          </ul>
        </dd>
      </div>
    )
  }

  if (typeof value === 'object' && value !== null) {
    const nested = value as Record<string, unknown>
    return (
      <div className="px-4 py-2.5">
        <dt className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
          {label}
        </dt>
        <dd className="mt-1 divide-y divide-slate-100 rounded-lg bg-page">
          {Object.entries(nested).map(([k, v]) => (
            <ArtifactField key={k} name={k} value={v} />
          ))}
        </dd>
      </div>
    )
  }

  return (
    <div className="px-4 py-2.5">
      <dt className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-sm whitespace-pre-wrap">
        {isScalar(value) ? String(value) : ''}
      </dd>
    </div>
  )
}

export function ArtifactView({
  artifact,
}: {
  artifact: Record<string, unknown>
  /** Retained for callers; rendering is driven by value shape, not by type. */
  type?: string
}) {
  // A code artifact's `language` is a one-word label; giving it a section of
  // its own cost a full row above the code. It is folded into the code label.
  const language =
    typeof artifact?.language === 'string' && typeof artifact?.code === 'string'
      ? artifact.language
      : null
  const entries = Object.entries(artifact ?? {}).filter(
    ([k]) => !(language && k === 'language'),
  )
  if (entries.length === 0) return null

  // A payload that is nothing but one table renders as that table, with no
  // wrapper - the common Data Interpretation case.
  if (entries.length === 1) {
    const only = asTable(entries[0][1])
    if (only) return <Table {...only} />
  }

  // The legacy flat encoding puts columns/rows at the top level.
  const flat = asTable(artifact)
  if (flat) return <Table {...flat} />

  return (
    <dl className="bp-card mt-3 divide-y divide-slate-100">
      {entries.map(([k, v]) => (
        <ArtifactField
          key={k}
          name={k === 'code' && language ? `code · ${language}` : k}
          value={v}
        />
      ))}
    </dl>
  )
}
