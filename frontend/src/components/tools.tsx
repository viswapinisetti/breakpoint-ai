/** Investigation tools (PRD sections 37, 39).
 *
 * Tools are supplied per subject by the adapter, so this panel renders whatever
 * the backend sends rather than hardcoding a list.
 *
 * Implemented tools are self-contained and need no backend: scratchpad,
 * calculator, formula reference, the three Databases tools, which run a real
 * PostgreSQL in the browser (lib/sql/), and the four code tools, which run
 * real CPython or plain JavaScript in the browser (lib/code/). Tools that
 * would need something the browser cannot provide - a container, a model,
 * outbound requests - are shown as unavailable rather than faked. A fake
 * terminal in a product about verifying claims would be the wrong thing to
 * ship.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { Tool } from '../api'
import { evaluate } from '../lib/calc'
import { createCodeSession, type CodeSession } from '../lib/code/client'
import { planCode } from '../lib/code/plan'
import { createSqlSession, type SqlSession } from '../lib/sql/client'
import { planDatabase } from '../lib/sql/prepare'
import {
  CodeEditorTool,
  CodeUnavailable,
  DebuggerTool,
  TerminalTool,
  TestRunnerTool,
} from './codeTools'
import { QueryExecutor, SchemaViewer, SqlEditor } from './sqlTools'

/** Tools that work fully client-side today. */
const IMPLEMENTED = new Set([
  'scratchpad',
  'calculator',
  'formulas',
  'highlighter',
  'sql',
  'runner',
  'schema',
  'editor',
  'terminal',
  'tests',
  'debugger',
])

/** Tools backed by the shared in-browser PostgreSQL. */
const SQL_TOOLS = new Set(['sql', 'runner', 'schema'])
/** Tools backed by the shared in-browser Python / JavaScript. */
const CODE_TOOLS = new Set(['editor', 'terminal', 'tests', 'debugger'])
/** Panes that stay mounted once opened, so switching tools keeps results. */
const KEEP_MOUNTED = new Set([...SQL_TOOLS, ...CODE_TOOLS])

/** Why each unsupported tool is absent. Not rendered as a disabled control -
 *  unsupported capabilities are hidden (PRD v0.2 12.4) - but surfaced in the
 *  panel summary so the omission is explained rather than silent. */
const PENDING_REASON: Record<string, string> = {
  request: 'Needs an outbound request sandbox (post-MVP).',
  inspector: 'Needs an outbound request sandbox (post-MVP).',
  sandbox: 'Needs a container sandbox (post-MVP).',
  yaml: 'Manifest is shown in the claim panel for now.',
  logs: 'Needs a log fixture service (post-MVP).',
  prompt: 'Needs a model sandbox (post-MVP).',
  compare: 'Needs a model sandbox (post-MVP).',
  evaluator: 'Needs a model sandbox (post-MVP).',
  dataviewer: 'Data is rendered in the claim panel.',
  chart: 'Charts are rendered in the claim panel.',
  notebook: 'Needs a notebook sandbox (post-MVP).',
  rules: 'Reference material coming with the English content pack.',
}

/* ------------------------------------------------------------- scratchpad */

function Scratchpad({ attemptId }: { attemptId: number }) {
  const storageKey = `bp-scratchpad-${attemptId}`
  const [text, setText] = useState('')

  // Per-viewer convenience only: notes stay in this browser and are never
  // submitted. Wrapped because storage can throw in private windows.
  useEffect(() => {
    try {
      setText(localStorage.getItem(storageKey) ?? '')
    } catch {
      /* storage unavailable - start empty */
    }
  }, [storageKey])

  function update(value: string) {
    setText(value)
    try {
      localStorage.setItem(storageKey, value)
    } catch {
      /* not fatal */
    }
  }

  return (
    <div>
      <p className="text-xs text-slate-500">
        Working notes. Saved in this browser only — never submitted.
      </p>
      <textarea
        value={text}
        onChange={(e) => update(e.target.value)}
        rows={10}
        placeholder={'Step 3 uses base 1000…\nRecompute: 20% of 800 = 160'}
        className="mt-2 w-full resize-y rounded-xl border border-slate-200 p-3 font-mono text-sm focus:border-brand focus:outline-none"
        aria-label="Scratchpad"
      />
    </div>
  )
}

/* ------------------------------------------------------------- calculator */

function Calculator() {
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<{ expr: string; value: string }[]>([])
  const [error, setError] = useState('')

  function run() {
    if (!input.trim()) return
    try {
      const value = evaluate(input)
      const shown = Number.isInteger(value)
        ? String(value)
        : String(Number(value.toFixed(6)))
      setHistory((h) => [{ expr: input, value: shown }, ...h].slice(0, 12))
      setError('')
      setInput('')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div>
      <p className="text-xs text-slate-500">
        Supports + − × ÷ ^ ( ) and <code>a % b</code> for “a percent of b”.
      </p>
      <div className="mt-2 flex gap-2">
        <input
          value={input}
          onChange={(e) => {
            setInput(e.target.value)
            setError('')
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') run()
          }}
          placeholder="20 % 800"
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm focus:border-brand focus:outline-none"
          aria-label="Calculator expression"
        />
        <button onClick={run} className="bp-btn bp-btn-primary">
          =
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
      {history.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200">
          {history.map((h, i) => (
            <li key={i} className="flex justify-between gap-3 px-3 py-1.5 text-sm">
              <span className="font-mono text-slate-500">{h.expr}</span>
              <span className="font-mono font-bold">{h.value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- formulas */

const FORMULAS: { group: string; items: [string, string][] }[] = [
  {
    group: 'Percentages',
    items: [
      ['Successive change', 'final = base × (1 + a) × (1 + b) — never additive'],
      ['Reverse percentage', 'base = final ÷ (1 + change)'],
      ['Percentage change', '(new − old) ÷ old × 100'],
      ['Profit on cost vs on SP', 'CP × (1+p) = SP  vs  SP × (1−p) = CP'],
    ],
  },
  {
    group: 'Time and Work',
    items: [
      ['Rate', 'work per day = 1 ÷ days'],
      ['Combined rate', 'valid only while both are working'],
      ['Remaining work', 'remaining ÷ current rate — recompute after any change'],
    ],
  },
  {
    group: 'Speed and Distance',
    items: [
      ['Same direction', 'relative speed = |a − b|'],
      ['Opposite direction', 'relative speed = a + b'],
      ['km/h → m/s', '× 1000 ÷ 3600  (i.e. × 5/18)'],
      ['Crossing', 'time = total length ÷ relative speed'],
    ],
  },
  {
    group: 'Counting and Probability',
    items: [
      ['Union', '|A ∪ B| = |A| + |B| − |A ∩ B|'],
      ['Disjoint only', 'add directly only when A ∩ B = ∅'],
      ['Complement', 'P(not A) = 1 − P(A)'],
    ],
  },
  {
    group: 'Averages and Ratios',
    items: [
      ['Average', 'sum ÷ count — adjust both when an element is removed'],
      ['Weighted average', '(w₁x₁ + w₂x₂) ÷ (w₁ + w₂), not the plain mean'],
    ],
  },
]

function FormulaReference() {
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return FORMULAS
    return FORMULAS.map((g) => ({
      group: g.group,
      items: g.items.filter(
        ([k, v]) =>
          k.toLowerCase().includes(q) ||
          v.toLowerCase().includes(q) ||
          g.group.toLowerCase().includes(q),
      ),
    })).filter((g) => g.items.length > 0)
  }, [query])

  return (
    <div>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search formulas…"
        className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-brand focus:outline-none"
        aria-label="Search formulas"
      />
      <div className="mt-3 space-y-4">
        {filtered.map((g) => (
          <div key={g.group}>
            <h4 className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
              {g.group}
            </h4>
            <dl className="mt-1.5 space-y-1">
              {g.items.map(([k, v]) => (
                <div key={k} className="rounded-lg bg-page px-3 py-1.5">
                  <dt className="text-xs font-bold">{k}</dt>
                  <dd className="font-mono text-xs text-slate-600">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-sm text-slate-500">No formula matches that search.</p>
        )}
      </div>
    </div>
  )
}

/* ----------------------------------------------------------------- panel */

export function ToolsPanel({
  tools,
  attemptId,
  selectedStep,
  artifact,
  question,
}: {
  tools: Tool[]
  attemptId: number
  selectedStep: number | null
  /** The investigation's artifact: the SQL tools load it as a database, the
   *  code tools as the code to run. */
  artifact: Record<string, unknown>
  question: string
}) {
  // Unsupported capabilities are hidden rather than shown as if functional
  // (PRD v0.2 sections 12.4 and AC-18).
  const available = tools.filter((t) => IMPLEMENTED.has(t.key))
  const [open, setOpen] = useState<string | null>(null)
  // Sandbox panes stay mounted once opened, so switching between tools keeps
  // each one's results.
  const [opened, setOpened] = useState<string[]>([])

  const plan = useMemo(() => planDatabase(artifact), [artifact])
  const codePlan = useMemo(() => planCode(artifact), [artifact])

  // The code every code tool works on: the Editor's, starting from the
  // artifact's and remembered in this browser per attempt.
  const codeKey = `bp-code-${attemptId}`
  const [code, setCodeState] = useState(() => {
    try {
      return localStorage.getItem(codeKey) ?? codePlan.code
    } catch {
      return codePlan.code
    }
  })
  const setCode = (next: string) => {
    setCodeState(next)
    try {
      localStorage.setItem(codeKey, next)
    } catch {
      /* not fatal */
    }
  }
  const shared = { code, setCode, original: codePlan.code }

  // One PostgreSQL and one code runtime per investigation, each started the
  // first time one of its tools opens and shut down when the investigation
  // closes.
  const sqlRef = useRef<SqlSession | null>(null)
  const codeRef = useRef<CodeSession | null>(null)
  const [sqlSession, setSqlSession] = useState<SqlSession | null>(null)
  const [codeSession, setCodeSession] = useState<CodeSession | null>(null)
  useEffect(
    () => () => {
      sqlRef.current?.dispose()
      sqlRef.current = null
      codeRef.current?.dispose()
      codeRef.current = null
    },
    [],
  )

  function toggle(key: string) {
    const next = open === key ? null : key
    setOpen(next)
    if (!next || !KEEP_MOUNTED.has(next)) return
    if (SQL_TOOLS.has(next) && !sqlRef.current) {
      sqlRef.current = createSqlSession(plan.seed)
      setSqlSession(sqlRef.current)
    }
    if (CODE_TOOLS.has(next) && codePlan.runtime && !codeRef.current) {
      codeRef.current = createCodeSession(codePlan.runtime)
      setCodeSession(codeRef.current)
    }
    setOpened((keys) => (keys.includes(next) ? keys : [...keys, next]))
  }

  function codePane(key: string) {
    if (!codePlan.runtime) return <CodeUnavailable plan={codePlan} />
    if (!codeSession) return null
    const props = { plan: codePlan, session: codeSession, shared }
    if (key === 'editor') return <CodeEditorTool {...props} />
    if (key === 'terminal') return <TerminalTool {...props} />
    if (key === 'tests') return <TestRunnerTool {...props} attemptId={attemptId} />
    return <DebuggerTool {...props} />
  }

  if (tools.length === 0) return null

  return (
    <section className="bp-card mt-6 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-page px-4 py-2.5">
        <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
          Investigation tools
        </span>
        {available.map((t) => {
          const active = open === t.key
          return (
            <button
              key={t.key}
              onClick={() => toggle(t.key)}
              title={t.label}
              className={`rounded-lg border px-2.5 py-1 text-xs font-bold transition ${
                active
                  ? 'border-brand bg-brand-soft text-brand-hover'
                  : 'border-slate-200 bg-white text-slate-700 hover:border-brand'
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      {opened.map((key) => (
        <div key={key} className="p-4" hidden={open !== key}>
          {sqlSession && key === 'runner' && (
            <QueryExecutor plan={plan} session={sqlSession} question={question} />
          )}
          {sqlSession && key === 'sql' && (
            <SqlEditor
              plan={plan}
              session={sqlSession}
              attemptId={attemptId}
              question={question}
            />
          )}
          {sqlSession && key === 'schema' && (
            <SchemaViewer plan={plan} session={sqlSession} question={question} />
          )}
          {CODE_TOOLS.has(key) && codePane(key)}
        </div>
      ))}

      {open && !KEEP_MOUNTED.has(open) && (
        <div className="p-4">
          {open === 'scratchpad' && <Scratchpad attemptId={attemptId} />}
          {open === 'calculator' && <Calculator />}
          {open === 'formulas' && <FormulaReference />}
          {open === 'highlighter' && (
            <p className="text-sm text-slate-600">
              Click any reasoning step in the AI Claim panel to mark it as the
              first failure.{' '}
              {selectedStep
                ? `Step ${selectedStep} is currently marked.`
                : 'No step is marked yet.'}
            </p>
          )}
        </div>
      )}

      {available.length < tools.length && !open && (
        <p className="px-4 py-2 text-xs text-slate-500">
          {tools.length - available.length} tool
          {tools.length - available.length === 1 ? '' : 's'} for this subject
          are not part of this release and are therefore not shown:{' '}
          {tools
            .filter((t) => !IMPLEMENTED.has(t.key))
            .map((t) => `${t.label} (${PENDING_REASON[t.key] ?? 'post-MVP'})`)
            .join('; ')}
        </p>
      )}
    </section>
  )
}
