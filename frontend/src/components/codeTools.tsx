/** The code investigation tools: Editor, Terminal, Test Runner, Debugger.
 *
 *  All four work on one shared copy of the code - the Editor's - so a student
 *  can change the AI's code and test the change. Python runs on real CPython
 *  (Pyodide) and plain JavaScript in a worker, both in the browser; see
 *  lib/code/. */

import { useEffect, useRef, useState } from 'react'
import type { CodeSession } from '../lib/code/client'
import type { CodePlan, TestCase } from '../lib/code/plan'
import type {
  CodeError,
  ReplResult,
  RunResult,
  TestsResult,
  TraceResult,
} from '../lib/code/protocol'
import { Spinner } from './ui'

export interface SharedCode {
  code: string
  setCode: (code: string) => void
  original: string
}

/* --------------------------------------------------------------- status */

type Readiness =
  | { state: 'starting' }
  | { state: 'ready'; version: string }
  | { state: 'failed'; message: string }

function useReadiness(session: CodeSession): [Readiness, () => void] {
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ attempt: number; value: Readiness } | null>(null)
  useEffect(() => {
    let live = true
    session.ready().then(
      (r) => live && setResult({ attempt, value: { state: 'ready', version: r.version } }),
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

function CodeStatus({
  plan,
  readiness,
  retry,
  shared,
}: {
  plan: CodePlan
  readiness: Readiness
  retry: () => void
  shared: SharedCode
}) {
  if (readiness.state === 'starting') {
    return (
      <div className="rounded-lg bg-page px-3 py-2">
        <Spinner
          label={
            plan.runtime === 'python'
              ? 'Starting Python in your browser (the first time downloads about 12 MB)'
              : 'Starting'
          }
        />
      </div>
    )
  }
  if (readiness.state === 'failed') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
        The code sandbox could not start: {readiness.message}{' '}
        <button onClick={retry} className="font-bold underline">
          Try again
        </button>
      </div>
    )
  }
  const edited = shared.code !== shared.original
  return (
    <div className="space-y-1.5 text-xs text-slate-500">
      <p>
        {plan.runtime === 'python'
          ? `Python ${readiness.version}, running in your browser.`
          : 'JavaScript, running in a worker in your browser.'}{' '}
        Nothing is sent to the server.
        {edited && ' Using your edited code from the Editor.'}
      </p>
      {plan.note && <p className="rounded-lg bg-page px-3 py-1.5 text-slate-600">{plan.note}</p>}
    </div>
  )
}

/** Shown in every code tool when the artifact's language cannot run. */
export function CodeUnavailable({ plan }: { plan: CodePlan }) {
  return <p className="text-sm text-slate-600">{plan.note}</p>
}

/* --------------------------------------------------------------- pieces */

function ErrorBlock({ error }: { error: CodeError }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2">
      <pre className="overflow-x-auto font-mono text-xs whitespace-pre-wrap text-red-800">
        {error.traceback || `${error.type}: ${error.message}`}
      </pre>
      {error.hint && <p className="mt-1.5 text-xs text-red-900">{error.hint}</p>}
    </div>
  )
}

function Output({ stdout, stderr }: { stdout: string; stderr: string }) {
  return (
    <>
      {stdout && (
        <pre className="max-h-64 overflow-auto rounded-lg bg-page px-3 py-2 font-mono text-xs whitespace-pre-wrap text-ink">
          {stdout}
        </pre>
      )}
      {stderr && (
        <pre className="max-h-40 overflow-auto rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 font-mono text-xs whitespace-pre-wrap text-amber-900">
          {stderr}
        </pre>
      )}
    </>
  )
}

function useBusy(): [boolean, string, <T>(work: () => Promise<T>) => Promise<T | undefined>] {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function guard<T>(work: () => Promise<T>) {
    setBusy(true)
    setError('')
    try {
      return await work()
    } catch (e) {
      setError((e as Error).message)
      return undefined
    } finally {
      setBusy(false)
    }
  }
  return [busy, error, guard]
}

function Failure({ message }: { message: string }) {
  return message ? (
    <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {message}
    </p>
  ) : null
}

/** A textarea with a line-number gutter; Tab indents, Ctrl+Enter runs. */
function CodeArea({
  value,
  onChange,
  onRun,
  indent,
  label,
}: {
  value: string
  onChange: (v: string) => void
  onRun: () => void
  indent: string
  label: string
}) {
  const gutter = useRef<HTMLDivElement>(null)
  const count = Math.max(value.split('\n').length, 1)
  const rows = Math.min(Math.max(count, 6), 18)
  return (
    <div className="flex overflow-hidden rounded-xl border border-slate-200 focus-within:border-brand">
      <div
        ref={gutter}
        aria-hidden="true"
        className="overflow-hidden bg-page py-3 pr-2 pl-3 text-right font-mono text-sm leading-6 text-slate-400 select-none"
        style={{ height: `${rows * 1.5 + 1.5}rem` }}
      >
        {Array.from({ length: count }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onScroll={(e) => {
          if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault()
            onRun()
          } else if (e.key === 'Tab' && !e.shiftKey) {
            e.preventDefault()
            const el = e.currentTarget
            const { selectionStart: s, selectionEnd: end } = el
            onChange(`${value.slice(0, s)}${indent}${value.slice(end)}`)
            requestAnimationFrame(() => el.setSelectionRange(s + indent.length, s + indent.length))
          }
        }}
        wrap="off"
        spellCheck={false}
        aria-label={label}
        className="min-w-0 flex-1 resize-none overflow-auto bg-white p-3 font-mono text-sm leading-6 focus:outline-none"
        style={{ height: `${rows * 1.5 + 1.5}rem` }}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- editor */

export function CodeEditorTool({
  plan,
  session,
  shared,
}: {
  plan: CodePlan
  session: CodeSession
  shared: SharedCode
}) {
  const [readiness, retry] = useReadiness(session)
  const [result, setResult] = useState<RunResult | null>(null)
  const [busy, error, guard] = useBusy()

  async function run() {
    const r = await guard(() => session.run(shared.code))
    setResult(r ?? null)
  }

  const edited = shared.code !== shared.original
  return (
    <div className="space-y-3">
      <CodeStatus plan={plan} readiness={readiness} retry={retry} shared={shared} />
      <CodeArea
        value={shared.code}
        onChange={shared.setCode}
        onRun={run}
        indent={plan.runtime === 'python' ? '    ' : '  '}
        label="Code editor"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={run}
          disabled={busy || readiness.state !== 'ready'}
          className="bp-btn bp-btn-primary"
        >
          {busy ? 'Running…' : 'Run'}
        </button>
        {edited && (
          <button
            onClick={() => {
              shared.setCode(shared.original)
              setResult(null)
            }}
            className="bp-btn bp-btn-ghost"
          >
            Restore original
          </button>
        )}
        <span className="text-xs text-slate-500">
          Ctrl+Enter runs. The Terminal, Test Runner and Debugger use this code.
        </span>
      </div>
      <Failure message={error} />
      {result && (
        <div className="space-y-2">
          <p className="text-xs text-slate-500 tabular-nums">
            {result.ok ? 'Ran' : 'Stopped with an error'} in {result.ms} ms
            {result.defined.length > 0 && (
              <>
                {' '}
                · defines{' '}
                <span className="font-mono text-slate-700">{result.defined.join(', ')}</span>
              </>
            )}
          </p>
          <Output stdout={result.stdout} stderr={result.stderr} />
          {result.error && <ErrorBlock error={result.error} />}
          {result.ok && !result.stdout && !result.stderr && (
            <p className="text-sm text-slate-600">
              No output. {result.defined.length > 0
                ? 'The code only defines functions; call them in the Terminal or the Test Runner.'
                : ''}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- terminal */

interface TerminalEntry {
  source: string
  result: ReplResult | null
  failure: string
}

export function TerminalTool({
  plan,
  session,
  shared,
}: {
  plan: CodePlan
  session: CodeSession
  shared: SharedCode
}) {
  const [readiness, retry] = useReadiness(session)
  const [entries, setEntries] = useState<TerminalEntry[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [cursor, setCursor] = useState<number | null>(null)
  const log = useRef<HTMLDivElement>(null)
  const prompt = plan.runtime === 'python' ? '>>>' : '>'

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [entries])

  async function submit() {
    const source = input.trimEnd()
    if (!source.trim() || busy) return
    setInput('')
    setCursor(null)
    setBusy(true)
    try {
      const result = await session.repl(shared.code, source)
      setEntries((e) => [...e, { source, result, failure: '' }])
    } catch (e) {
      setEntries((prev) => [...prev, { source, result: null, failure: (e as Error).message }])
    } finally {
      setBusy(false)
    }
  }

  const sources = entries.map((e) => e.source)
  const starter = plan.entry
    ? `${plan.entry}(…)`
    : plan.runtime === 'python'
      ? '2 ** 10'
      : '[10, 1, 2].sort()'

  return (
    <div className="space-y-3">
      <CodeStatus plan={plan} readiness={readiness} retry={retry} shared={shared} />
      <p className="text-xs text-slate-500">
        {plan.runtime === 'python'
          ? 'The code is loaded, so its functions are ready to call. Variables persist until you restart or change the code.'
          : 'Each entry first replays the code and your earlier statements silently, so they behave as if still defined.'}
      </p>
      <div
        ref={log}
        className="max-h-80 min-h-24 overflow-y-auto rounded-xl bg-slate-900 px-3 py-2 font-mono text-xs leading-5 text-slate-100"
        aria-live="polite"
      >
        {entries.length === 0 && (
          <p className="text-slate-400">Try: {starter}</p>
        )}
        {entries.map((entry, i) => (
          <div key={i} className="mb-1.5">
            {entry.source.split('\n').map((line, j) => (
              <div key={j} className="whitespace-pre-wrap">
                <span className="text-sky-300">{j === 0 ? prompt : '...'} </span>
                {line}
              </div>
            ))}
            {entry.result?.stdout && (
              <div className="whitespace-pre-wrap text-slate-200">{entry.result.stdout.replace(/\n$/, '')}</div>
            )}
            {entry.result?.stderr && (
              <div className="whitespace-pre-wrap text-amber-300">{entry.result.stderr.replace(/\n$/, '')}</div>
            )}
            {entry.result?.value !== null && entry.result?.value !== undefined && (
              <div className="whitespace-pre-wrap text-emerald-300">{entry.result.value}</div>
            )}
            {entry.result?.error && (
              <div className="whitespace-pre-wrap text-red-300">
                {entry.result.loadFailed && 'The code itself fails to load:\n'}
                {entry.result.error.traceback || `${entry.result.error.type}: ${entry.result.error.message}`}
                {entry.result.error.hint && `\n${entry.result.error.hint}`}
              </div>
            )}
            {entry.failure && <div className="whitespace-pre-wrap text-red-300">{entry.failure}</div>}
          </div>
        ))}
        {busy && <div className="text-slate-400">running…</div>}
      </div>
      <div className="flex items-start gap-2">
        <span className="pt-2.5 font-mono text-sm text-slate-500">{prompt}</span>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void submit()
            } else if (e.key === 'ArrowUp' && !input.includes('\n') && sources.length) {
              e.preventDefault()
              const next = cursor === null ? sources.length - 1 : Math.max(0, cursor - 1)
              setCursor(next)
              setInput(sources[next])
            } else if (e.key === 'ArrowDown' && cursor !== null && !input.includes('\n')) {
              e.preventDefault()
              const next = cursor + 1
              if (next >= sources.length) {
                setCursor(null)
                setInput('')
              } else {
                setCursor(next)
                setInput(sources[next])
              }
            }
          }}
          rows={Math.min(Math.max(input.split('\n').length, 1), 6)}
          spellCheck={false}
          disabled={readiness.state !== 'ready'}
          placeholder={starter}
          aria-label="Terminal input"
          className="min-w-0 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none disabled:bg-slate-50"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => void submit()}
          disabled={busy || readiness.state !== 'ready' || !input.trim()}
          className="bp-btn bp-btn-primary"
        >
          Run
        </button>
        <button
          onClick={async () => {
            setEntries([])
            await session.resetTerminal().catch(() => {})
          }}
          disabled={busy}
          className="bp-btn bp-btn-ghost"
        >
          Restart
        </button>
        <span className="text-xs text-slate-500">
          Enter runs, Shift+Enter adds a line, ↑ ↓ recall earlier entries.
        </span>
      </div>
    </div>
  )
}

/* ----------------------------------------------------------- test runner */

export function TestRunnerTool({
  plan,
  session,
  shared,
  attemptId,
}: {
  plan: CodePlan
  session: CodeSession
  shared: SharedCode
  attemptId: number
}) {
  const [readiness, retry] = useReadiness(session)
  const storageKey = `bp-tests-${attemptId}`
  const [cases, setCases] = useState<TestCase[]>(() => {
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) return JSON.parse(saved) as TestCase[]
    } catch {
      /* storage unavailable or unreadable - start fresh */
    }
    return plan.tests.length ? plan.tests : [{ call: '', expected: '' }]
  })
  const [outcome, setOutcome] = useState<TestsResult | null>(null)
  const [busy, error, guard] = useBusy()

  function update(next: TestCase[]) {
    setCases(next)
    setOutcome(null)
    try {
      localStorage.setItem(storageKey, JSON.stringify(next))
    } catch {
      /* not fatal */
    }
  }

  async function runAll() {
    const r = await guard(() => session.tests(shared.code, cases))
    setOutcome(r ?? null)
  }

  // Results come back for non-empty rows only, in order.
  const resultFor = new Map<number, TestsResult['results'][number]>()
  if (outcome) {
    let k = 0
    cases.forEach((c, i) => {
      if (c.call.trim()) resultFor.set(i, outcome.results[k++])
    })
  }
  const passed = outcome?.results.filter((r) => r.passed).length ?? 0
  const callHint = plan.entry ? `${plan.entry}(…)` : plan.runtime === 'python' ? 'len([1, 2])' : '[1, 2].length'

  return (
    <div className="space-y-3">
      <CodeStatus plan={plan} readiness={readiness} retry={retry} shared={shared} />
      <p className="text-xs text-slate-500">
        Each case calls the code and compares the result with what you expect.
        Cases run in order in one fresh copy of the code, as a test file does,
        so state the code keeps between calls carries over. Expected can be a
        value or <code className="font-mono">raises ValueError</code>.
      </p>
      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="w-full text-left text-xs">
          <thead className="bg-page text-slate-500">
            <tr>
              <th className="px-3 py-1.5 font-bold">Call</th>
              <th className="px-3 py-1.5 font-bold">Expected</th>
              <th className="px-3 py-1.5 font-bold">Result</th>
              <th className="w-8" />
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => {
              const r = resultFor.get(i)
              return (
                <tr key={i} className="border-t border-slate-100 align-top">
                  <td className="px-2 py-1.5">
                    <input
                      value={c.call}
                      onChange={(e) => update(cases.map((x, j) => (j === i ? { ...x, call: e.target.value } : x)))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void runAll()
                      }}
                      placeholder={callHint}
                      spellCheck={false}
                      aria-label={`Case ${i + 1} call`}
                      className="w-full min-w-40 rounded-md border border-slate-200 px-2 py-1.5 font-mono text-xs focus:border-brand focus:outline-none"
                    />
                  </td>
                  <td className="px-2 py-1.5">
                    <input
                      value={c.expected}
                      onChange={(e) => update(cases.map((x, j) => (j === i ? { ...x, expected: e.target.value } : x)))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void runAll()
                      }}
                      placeholder="expected value"
                      spellCheck={false}
                      aria-label={`Case ${i + 1} expected`}
                      className="w-full min-w-28 rounded-md border border-slate-200 px-2 py-1.5 font-mono text-xs focus:border-brand focus:outline-none"
                    />
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {!r ? (
                      <span className="text-slate-300">—</span>
                    ) : r.passed ? (
                      <span className="font-bold text-emerald-700">✓ pass</span>
                    ) : (
                      <span className="text-red-700">
                        <span className="font-bold">✕ fail</span>
                        {r.error
                          ? ` · ${r.error.type ? `${r.error.type}: ` : ''}${r.error.message}`
                          : ` · got ${r.actual}`}
                      </span>
                    )}
                    {r?.stdout && (
                      <pre className="mt-1 max-h-20 overflow-auto whitespace-pre-wrap text-slate-500">{r.stdout}</pre>
                    )}
                  </td>
                  <td className="px-1 py-1.5">
                    <button
                      onClick={() => update(cases.filter((_, j) => j !== i))}
                      disabled={cases.length === 1}
                      aria-label={`Remove case ${i + 1}`}
                      className="grid h-8 w-8 place-items-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-red-700 disabled:opacity-30"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={runAll}
          disabled={busy || readiness.state !== 'ready' || !cases.some((c) => c.call.trim())}
          className="bp-btn bp-btn-primary"
        >
          {busy ? 'Running…' : 'Run all'}
        </button>
        <button
          onClick={() => update([...cases, { call: '', expected: '' }])}
          className="bp-btn bp-btn-ghost"
        >
          + Add case
        </button>
        {outcome && !outcome.loadError && (
          <span
            className={`text-sm font-bold tabular-nums ${
              passed === outcome.results.length ? 'text-emerald-700' : 'text-red-700'
            }`}
          >
            {passed} passed, {outcome.results.length - passed} failed
          </span>
        )}
      </div>
      <Failure message={error} />
      {outcome?.loadError && (
        <>
          <p className="text-sm text-slate-600">The code fails to load, so no case could run:</p>
          <ErrorBlock error={outcome.loadError} />
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- debugger */

export function DebuggerTool({
  plan,
  session,
  shared,
}: {
  plan: CodePlan
  session: CodeSession
  shared: SharedCode
}) {
  const [readiness, retry] = useReadiness(session)
  const [source, setSource] = useState(() => plan.tests[0]?.call ?? '')
  const [trace, setTrace] = useState<{ result: TraceResult; code: string } | null>(null)
  const [index, setIndex] = useState(0)
  const [busy, error, guard] = useBusy()

  if (plan.runtime !== 'python') {
    return (
      <p className="text-sm text-slate-600">
        The step-through debugger traces Python code. For JavaScript, use the
        Terminal to call functions and inspect values.
      </p>
    )
  }

  async function run() {
    if (!source.trim()) return
    const code = shared.code
    const r = await guard(() => session.trace(code, source))
    setTrace(r ? { result: r, code } : null)
    setIndex(0)
  }

  const steps = trace?.result.steps ?? []
  const step = steps[index]
  const previous = index > 0 ? steps[index - 1] : undefined
  const lines = (trace?.code ?? shared.code).split('\n')
  const hint = plan.entry ? `${plan.entry}(…)` : 'a call into the code'

  return (
    <div className="space-y-3">
      <CodeStatus plan={plan} readiness={readiness} retry={retry} shared={shared} />
      <p className="text-xs text-slate-500">
        Records every line the code runs for one call, with its variables, then
        lets you step through it. Several statements are fine, e.g. two calls
        in a row.
      </p>
      <div className="flex flex-wrap items-start gap-2">
        <textarea
          value={source}
          onChange={(e) => setSource(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void run()
            }
          }}
          rows={Math.min(Math.max(source.split('\n').length, 1), 4)}
          spellCheck={false}
          placeholder={hint}
          aria-label="Call to trace"
          className="min-w-0 flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none"
        />
        <button
          onClick={run}
          disabled={busy || readiness.state !== 'ready' || !source.trim()}
          className="bp-btn bp-btn-primary"
        >
          {busy ? 'Tracing…' : 'Trace'}
        </button>
      </div>
      <Failure message={error} />
      {trace?.result.loadError && <ErrorBlock error={trace.result.loadError} />}
      {trace && !trace.result.loadError && steps.length === 0 && (
        <p className="text-sm text-slate-600">
          That did not run any line of the investigation&rsquo;s code. Call one of its functions.
        </p>
      )}
      {step && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setIndex(0)} disabled={index === 0} className="bp-btn bp-btn-ghost" aria-label="First step">
              ⏮
            </button>
            <button onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0} className="bp-btn bp-btn-ghost">
              ← Back
            </button>
            <button
              onClick={() => setIndex((i) => Math.min(steps.length - 1, i + 1))}
              disabled={index >= steps.length - 1}
              className="bp-btn bp-btn-primary"
            >
              Step →
            </button>
            <button
              onClick={() => setIndex(steps.length - 1)}
              disabled={index >= steps.length - 1}
              className="bp-btn bp-btn-ghost"
              aria-label="Last step"
            >
              ⏭
            </button>
            <span className="text-xs text-slate-600 tabular-nums">
              Step {index + 1} of {steps.length}
              {trace?.result.truncated && ' (recording stopped at the limit)'}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={steps.length - 1}
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
            aria-label="Trace position"
            className="w-full accent-brand"
          />
          <div className="grid gap-2 md:grid-cols-[1.4fr_1fr]">
            <pre className="max-h-72 overflow-auto rounded-xl border border-slate-200 bg-white py-2 font-mono text-xs leading-5">
              {lines.map((line, i) => {
                const current = i + 1 === step.line
                return (
                  <div
                    key={i}
                    className={`flex gap-3 px-3 ${
                      current
                        ? step.event === 'exception'
                          ? 'bg-red-100'
                          : 'bg-brand-soft'
                        : ''
                    }`}
                  >
                    <span className="w-5 shrink-0 text-right text-slate-400 select-none">{i + 1}</span>
                    <span className="whitespace-pre">{line || ' '}</span>
                  </div>
                )
              })}
            </pre>
            <div className="space-y-2 text-xs">
              <p>
                <span
                  className={`rounded px-1.5 py-0.5 font-bold uppercase ${
                    step.event === 'exception'
                      ? 'bg-red-100 text-red-800'
                      : step.event === 'return'
                        ? 'bg-emerald-100 text-emerald-800'
                        : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  {step.event}
                </span>{' '}
                line {step.line} in <span className="font-mono">{step.func}</span>
              </p>
              {(step.event === 'return' || step.event === 'exception') && (
                <p className="font-mono">
                  {step.event === 'return' ? 'returns ' : ''}
                  <span className="font-bold">{step.value}</span>
                </p>
              )}
              <table className="w-full rounded-lg border border-slate-200 font-mono">
                <tbody>
                  {Object.entries(step.locals).map(([name, value]) => {
                    const changed = previous !== undefined && previous.func === step.func && previous.locals[name] !== value
                    return (
                      <tr key={name} className="border-t border-slate-100 first:border-0">
                        <td className="px-2 py-1 text-slate-500">{name}</td>
                        <td className={`px-2 py-1 break-all ${changed ? 'bg-amber-50 font-bold text-amber-900' : ''}`}>
                          {value}
                        </td>
                      </tr>
                    )
                  })}
                  {Object.keys(step.locals).length === 0 && (
                    <tr>
                      <td className="px-2 py-1 text-slate-400">no local variables</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          {trace && index === steps.length - 1 && (
            <div className="space-y-2">
              {trace.result.value !== null && (
                <p className="text-sm">
                  Result: <span className="font-mono font-bold">{trace.result.value}</span>
                </p>
              )}
              {trace.result.error && <ErrorBlock error={trace.result.error} />}
            </div>
          )}
          <Output stdout={trace?.result.stdout ?? ''} stderr="" />
        </div>
      )}
    </div>
  )
}
