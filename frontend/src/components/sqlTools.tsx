/** The Databases investigation tools: Query Executor, SQL Editor and Schema
 *  Viewer, all over one in-browser PostgreSQL loaded with the investigation's
 *  data (see lib/sql/). */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { SqlSession } from '../lib/sql/client'
import { otherDialect, splitStatements, type SeedPlan } from '../lib/sql/prepare'
import { MAX_ROWS, type LoadReport, type SchemaTable, type StatementResult } from '../lib/sql/protocol'
import { Spinner } from './ui'

type Readiness =
  | { state: 'starting' }
  | { state: 'ready'; report: LoadReport }
  | { state: 'failed'; message: string }

function useReadiness(session: SqlSession): [Readiness, () => void] {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ attempt: number; value: Readiness } | null>(null)
  useEffect(() => {
    let live = true
    session.ready().then(
      (report) => live && setResult({ attempt, value: { state: 'ready', report } }),
      (e: Error) => live && setResult({ attempt, value: { state: 'failed', message: e.message } }),
    )
    return () => {
      live = false
    }
  }, [session, attempt])
  const readiness: Readiness =
    result && result.attempt === attempt ? result.value : { state: 'starting' }
  return [readiness, () => setAttempt((a) => a + 1)]
}

/* ------------------------------------------------------------ shared bits */

function SandboxStatus({
  plan,
  readiness,
  retry,
  question,
}: {
  plan: SeedPlan
  readiness: Readiness
  retry: () => void
  question: string
}) {
  const dialect = otherDialect(`${question}\n${plan.query}`)
  if (readiness.state === 'starting') {
    return (
      <div className="rounded-lg bg-page px-3 py-2">
        <Spinner label="Starting PostgreSQL in your browser (the first time downloads a few MB)" />
      </div>
    )
  }
  if (readiness.state === 'failed') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
        The SQL sandbox could not start: {readiness.message}{' '}
        <button onClick={retry} className="font-bold underline">
          Try again
        </button>
      </div>
    )
  }
  const { report } = readiness
  return (
    <div className="space-y-1.5 text-xs text-slate-500">
      <p>
        PostgreSQL {report.version}, running in your browser. Loaded from this
        investigation:{' '}
        <span className="font-mono text-slate-700">
          {plan.tables.length ? plan.tables.join(', ') : 'no tables'}
        </span>
        . Changes stay in this tab.
      </p>
      {dialect && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-amber-900">
          This question is about {dialect}. The sandbox runs PostgreSQL, so
          some behaviour may differ from {dialect}.
        </p>
      )}
      {plan.notes.map((note) => (
        <p key={note} className="rounded-lg bg-page px-3 py-1.5 text-slate-600">
          {note}
        </p>
      ))}
      {report.failures.map((f) => (
        <p
          key={f.sql}
          className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-amber-900"
        >
          PostgreSQL did not accept part of this investigation&rsquo;s schema:{' '}
          {f.message}
        </p>
      ))}
    </div>
  )
}

function summary(r: StatementResult): string {
  if (!r.ok) return 'error'
  if (r.columns.length > 0) return `${r.rowCount} row${r.rowCount === 1 ? '' : 's'}`
  if (['INSERT', 'UPDATE', 'DELETE', 'MERGE'].includes(r.command)) {
    return `${r.command} ${r.rowCount}`
  }
  return r.command || 'OK'
}

function ResultBlock({ result, index }: { result: StatementResult; index: number }) {
  return (
    <div
      className={`overflow-hidden rounded-xl border ${
        result.ok ? 'border-slate-200' : 'border-red-200'
      }`}
    >
      <div className="flex items-start gap-2 border-b border-slate-100 bg-page px-3 py-2">
        <span
          aria-label={result.ok ? 'Succeeded' : 'Failed'}
          className={`mt-px text-xs font-bold ${result.ok ? 'text-emerald-700' : 'text-red-700'}`}
        >
          {result.ok ? '✓' : '✕'} {index}
        </span>
        <pre className="max-h-24 min-w-0 flex-1 overflow-auto font-mono text-xs whitespace-pre-wrap text-slate-700">
          {result.sql}
        </pre>
        <span className="shrink-0 text-[11px] text-slate-500 tabular-nums">
          {summary(result)} · {result.ms} ms
        </span>
      </div>
      {result.error ? (
        <div className="space-y-0.5 bg-red-50 px-3 py-2 font-mono text-xs text-red-800">
          <div>
            ERROR: {result.error.message}
            {result.error.code && (
              <span className="text-red-600/80"> (SQLSTATE {result.error.code})</span>
            )}
          </div>
          {result.error.detail && <div>DETAIL: {result.error.detail}</div>}
          {result.error.hint && <div>HINT: {result.error.hint}</div>}
        </div>
      ) : result.columns.length > 0 ? (
        <>
          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="sticky top-0 bg-white">
                <tr>
                  {result.columns.map((c, i) => (
                    <th
                      key={`${c}-${i}`}
                      className="border-b border-slate-200 px-3 py-1.5 font-bold text-slate-600"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className="border-b border-slate-100 last:border-0">
                    {row.map((v, j) => (
                      <td key={j} className="px-3 py-1 whitespace-pre">
                        {v === null ? <span className="text-slate-400 italic">NULL</span> : v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.rows.length === 0 && (
            <p className="px-3 py-2 text-xs text-slate-500">No rows.</p>
          )}
          {result.truncated && (
            <p className="border-t border-slate-100 px-3 py-1.5 text-xs text-slate-500">
              Showing the first {MAX_ROWS} rows.
            </p>
          )}
        </>
      ) : null}
    </div>
  )
}

function ResultList({ results }: { results: StatementResult[] }) {
  const failed = results.filter((r) => !r.ok).length
  // The tools sit at the foot of a scrolling column; bring fresh results
  // into view rather than leaving them below the fold.
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [results])
  return (
    <div ref={ref} className="mt-3 space-y-2">
      <p className="text-xs font-bold text-slate-600">
        {results.length} statement{results.length === 1 ? '' : 's'} run
        {failed > 0 ? `, ${failed} failed` : ', all succeeded'}
      </p>
      {results.map((r, i) => (
        <ResultBlock key={i} result={r} index={i + 1} />
      ))}
    </div>
  )
}

function ErrorLine({ message }: { message: string }) {
  return message ? (
    <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {message}
    </p>
  ) : null
}

/* -------------------------------------------------------- query executor */

export function QueryExecutor({
  plan,
  session,
  question,
}: {
  plan: SeedPlan
  session: SqlSession
  question: string
}) {
  const [readiness, retry] = useReadiness(session)
  const statements = useMemo(() => splitStatements(plan.query), [plan.query])
  const [results, setResults] = useState<StatementResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run() {
    setBusy(true)
    setError('')
    try {
      // Always from the investigation's own data, so a second run of an
      // INSERT does not collide with the first.
      await session.reset()
      setResults(await session.run(plan.query))
    } catch (e) {
      setResults(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <SandboxStatus plan={plan} readiness={readiness} retry={retry} question={question} />
      {!plan.isSql ? (
        <p className="text-sm text-slate-600">
          This investigation&rsquo;s artifact is not SQL, so there is nothing to
          run. The SQL Editor still gives you an empty PostgreSQL database to
          experiment in.
        </p>
      ) : statements.length === 0 ? (
        <p className="text-sm text-slate-600">
          This artifact has a schema but no query. Query it in the SQL Editor,
          or inspect it in the Schema Viewer.
        </p>
      ) : (
        <>
          <p className="text-sm text-slate-600">
            Runs the SQL exactly as shown in the investigation, one statement
            at a time, on a fresh copy of its data. What PostgreSQL does is
            evidence; whether the AI&rsquo;s claim holds is still your call.
          </p>
          <ol className="space-y-1">
            {statements.map((s, i) => (
              <li key={i} className="flex gap-2 rounded-lg bg-page px-3 py-1.5">
                <span className="text-xs font-bold text-slate-400 tabular-nums">{i + 1}</span>
                <pre className="min-w-0 flex-1 overflow-x-auto font-mono text-xs whitespace-pre-wrap">
                  {s}
                </pre>
              </li>
            ))}
          </ol>
          <button
            onClick={run}
            disabled={busy || readiness.state !== 'ready'}
            className="bp-btn bp-btn-primary"
          >
            {busy ? 'Running…' : results ? 'Run again' : "Run the AI's SQL"}
          </button>
          <ErrorLine message={error} />
          {results && <ResultList results={results} />}
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------ SQL editor */

export function SqlEditor({
  plan,
  session,
  attemptId,
  question,
}: {
  plan: SeedPlan
  session: SqlSession
  attemptId: number
  question: string
}) {
  const [readiness, retry] = useReadiness(session)
  const storageKey = `bp-sql-${attemptId}`
  const [text, setText] = useState(() => {
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved !== null) return saved
    } catch {
      /* storage unavailable - use the default */
    }
    if (plan.query.trim()) return plan.query.trim()
    return plan.tables[0] ? `SELECT * FROM ${plan.tables[0]};` : 'SELECT version();'
  })
  const [results, setResults] = useState<StatementResult[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)

  function update(value: string) {
    setText(value)
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      /* not fatal */
    }
  }

  async function run() {
    const el = area.current
    const selected = el ? el.value.slice(el.selectionStart, el.selectionEnd) : ''
    const sql = selected.trim() || text
    if (!sql.trim()) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      setResults(await session.run(sql))
    } catch (e) {
      setResults(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function reset() {
    setBusy(true)
    setError('')
    try {
      await session.reset()
      setResults(null)
      setNotice("Back to this investigation's original data.")
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <SandboxStatus plan={plan} readiness={readiness} retry={retry} question={question} />
      <textarea
        ref={area}
        value={text}
        onChange={(e) => update(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            void run()
          } else if (e.key === 'Tab' && !e.shiftKey) {
            e.preventDefault()
            const el = e.currentTarget
            const { selectionStart: s, selectionEnd: end } = el
            update(`${text.slice(0, s)}  ${text.slice(end)}`)
            requestAnimationFrame(() => el.setSelectionRange(s + 2, s + 2))
          }
        }}
        rows={8}
        spellCheck={false}
        aria-label="SQL editor"
        className="w-full resize-y rounded-xl border border-slate-200 p-3 font-mono text-sm focus:border-brand focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={run}
          disabled={busy || readiness.state !== 'ready'}
          className="bp-btn bp-btn-primary"
        >
          {busy ? 'Running…' : 'Run'}
        </button>
        <button
          onClick={reset}
          disabled={busy || readiness.state !== 'ready'}
          className="bp-btn bp-btn-ghost"
        >
          Reset data
        </button>
        <span className="text-xs text-slate-500">
          Ctrl+Enter runs; with text selected, only the selection runs.
        </span>
      </div>
      {notice && <p className="text-xs text-slate-600">{notice}</p>}
      <ErrorLine message={error} />
      {results && <ResultList results={results} />}
    </div>
  )
}

/* ---------------------------------------------------------- schema viewer */

export function SchemaViewer({
  plan,
  session,
  question,
}: {
  plan: SeedPlan
  session: SqlSession
  question: string
}) {
  const [readiness, retry] = useReadiness(session)
  const [tick, setTick] = useState(0)
  const [loaded, setLoaded] = useState<{
    tick: number
    tables: SchemaTable[]
    error: string
  } | null>(null)

  useEffect(() => {
    if (readiness.state !== 'ready') return
    let live = true
    session.schema().then(
      (tables) => live && setLoaded({ tick, tables, error: '' }),
      (e: Error) => live && setLoaded({ tick, tables: [], error: e.message }),
    )
    return () => {
      live = false
    }
  }, [session, readiness.state, tick])

  const current = loaded && loaded.tick === tick ? loaded : null

  return (
    <div className="space-y-3">
      <SandboxStatus plan={plan} readiness={readiness} retry={retry} question={question} />
      {readiness.state === 'ready' && (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-slate-500">
            The database as it is now, including anything created or changed in
            the SQL Editor.
          </p>
          <button
            onClick={() => setTick((t) => t + 1)}
            disabled={!current}
            className="bp-btn bp-btn-ghost shrink-0"
          >
            Refresh
          </button>
        </div>
      )}
      {readiness.state === 'ready' && !current && <Spinner label="Reading the schema" />}
      {current?.error && <ErrorLine message={current.error} />}
      {current && !current.error && current.tables.length === 0 && (
        <p className="text-sm text-slate-600">No tables yet.</p>
      )}
      {current?.tables.map((table) => (
        <div key={table.name} className="overflow-hidden rounded-xl border border-slate-200">
          <div className="flex items-baseline justify-between gap-2 border-b border-slate-100 bg-page px-3 py-2">
            <span className="font-mono text-sm font-bold">{table.name}</span>
            <span className="text-[11px] text-slate-500 tabular-nums">
              {table.rowCount} row{table.rowCount === 1 ? '' : 's'}
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-500">
                  <th className="px-3 py-1.5 font-bold">Column</th>
                  <th className="px-3 py-1.5 font-bold">Type</th>
                  <th className="px-3 py-1.5 font-bold">NULL allowed</th>
                  <th className="px-3 py-1.5 font-bold">Keys</th>
                  <th className="px-3 py-1.5 font-bold">Default</th>
                </tr>
              </thead>
              <tbody>
                {table.columns.map((c) => (
                  <tr key={c.name} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 font-mono font-bold">{c.name}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-700">{c.type}</td>
                    <td className="px-3 py-1.5">{c.nullable ? 'yes' : 'no'}</td>
                    <td className="px-3 py-1.5">
                      <span className="flex flex-wrap gap-1">
                        {c.keys.map((k) => (
                          <span
                            key={k}
                            className="rounded bg-brand-soft px-1.5 py-0.5 font-mono text-[10.5px] font-bold text-brand-hover"
                          >
                            {k}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-slate-500">{c.default ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {table.indexes.length > 0 && (
            <ul className="space-y-0.5 border-t border-slate-100 px-3 py-2 font-mono text-[11px] text-slate-600">
              {table.indexes.map((ix) => (
                <li key={ix}>{ix}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}
