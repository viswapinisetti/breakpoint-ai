/** Plain JavaScript for the code tools, in a Web Worker.
 *
 * The client starts a fresh worker for every request, so timers and globals
 * from one run can never leak into the next, and terminates it if a run goes
 * past its timeout. The Terminal keeps state by replaying the program and the
 * earlier entries silently before each new entry.
 *
 * `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` and `importScripts`
 * are shadowed with stubs that explain themselves: investigations are about
 * reasoning over the code shown, not reaching the network. This is a guard
 * against accidents, not a security boundary - it is the student's own
 * browser running code they chose to run.
 */

import type { CodeError, CodeReply, CodeRequest, RunResult, TestResult } from './protocol'

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor as new (
  ...args: string[]
) => (...args: unknown[]) => Promise<unknown>

const SHADOWED = ['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'importScripts']
const noNetwork = (name: string) =>
  function blocked() {
    throw new Error(`${name} is not available in the sandbox: there is no network here.`)
  }

// --- console and timers ------------------------------------------------------

let quiet = false
const out: string[] = []
const err: string[] = []
let outLength = 0
const MAX_OUTPUT = 20_000

function inspect(value: unknown, depth = 0, seen = new Set<unknown>()): string {
  if (typeof value === 'string') return depth === 0 ? value : JSON.stringify(value)
  if (value === undefined) return 'undefined'
  if (value === null) return 'null'
  if (typeof value === 'number' || typeof value === 'boolean') return Object.is(value, -0) ? '-0' : String(value)
  if (typeof value === 'bigint') return `${value}n`
  if (typeof value === 'symbol') return value.toString()
  if (typeof value === 'function') return `[Function: ${value.name || 'anonymous'}]`
  if (value instanceof Error) return `${value.name}: ${value.message}`
  if (value instanceof Promise) return 'Promise { <pending> }'
  if (seen.has(value)) return '[Circular]'
  if (depth > 3) return Array.isArray(value) ? '[Array]' : '[Object]'
  seen.add(value)
  try {
    if (Array.isArray(value)) {
      return `[ ${value.map((v) => inspect(v, depth + 1, seen)).join(', ')} ]`.replace('[  ]', '[]')
    }
    if (value instanceof Map) {
      return `Map(${value.size}) { ${[...value].map(([k, v]) => `${inspect(k, depth + 1, seen)} => ${inspect(v, depth + 1, seen)}`).join(', ')} }`
    }
    if (value instanceof Set) {
      return `Set(${value.size}) { ${[...value].map((v) => inspect(v, depth + 1, seen)).join(', ')} }`
    }
    if (value instanceof Date) return value.toISOString()
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return '{}'
    return `{ ${entries
      .map(([k, v]) => `${/^[A-Za-z_$][\w$]*$/.test(k) ? k : JSON.stringify(k)}: ${inspect(v, depth + 1, seen)}`)
      .join(', ')} }`
  } finally {
    seen.delete(value)
  }
}

function write(target: string[], args: unknown[]) {
  if (quiet || outLength > MAX_OUTPUT) return
  const line = args.map((a) => inspect(a)).join(' ')
  outLength += line.length
  target.push(outLength > MAX_OUTPUT ? '... output truncated ...' : line)
}

const sandboxConsole = {
  log: (...a: unknown[]) => write(out, a),
  info: (...a: unknown[]) => write(out, a),
  debug: (...a: unknown[]) => write(out, a),
  table: (...a: unknown[]) => write(out, a),
  warn: (...a: unknown[]) => write(err, a),
  error: (...a: unknown[]) => write(err, a),
}

let pendingTimers = 0
const nativeSetTimeout = self.setTimeout.bind(self)
const nativeClearTimeout = self.clearTimeout.bind(self)
const liveTimers = new Set<number>()

function sandboxSetTimeout(fn: (...args: unknown[]) => void, ms?: number, ...args: unknown[]) {
  pendingTimers++
  const handle: number = nativeSetTimeout(() => {
    liveTimers.delete(handle)
    pendingTimers--
    try {
      fn(...args)
    } catch (e) {
      uncaught.push(e)
    }
  }, ms)
  liveTimers.add(handle)
  return handle
}
function sandboxClearTimeout(handle: number) {
  if (liveTimers.delete(handle)) pendingTimers--
  nativeClearTimeout(handle)
}
// Intervals are repeating timeouts, so they count as pending too; the settle
// wait below caps how long a never-cleared interval can keep a run open.
let nextInterval = 1
const intervals = new Map<number, number>()
function sandboxSetInterval(fn: (...args: unknown[]) => void, ms?: number, ...args: unknown[]) {
  const id = nextInterval++
  const tick = () => {
    intervals.set(
      id,
      sandboxSetTimeout(() => {
        fn(...args)
        if (intervals.has(id)) tick()
      }, ms),
    )
  }
  tick()
  return id
}
function sandboxClearInterval(id: number) {
  const handle = intervals.get(id)
  intervals.delete(id)
  if (handle !== undefined) sandboxClearTimeout(handle)
}

const uncaught: unknown[] = []
self.addEventListener('unhandledrejection', (event) => {
  uncaught.push((event as PromiseRejectionEvent).reason)
  event.preventDefault()
})

/** Wait until no timers are pending (up to capMs), so output from callbacks
 *  - the whole point of a setTimeout-ordering question - is collected. */
async function settle(capMs = 2_000): Promise<boolean> {
  const started = performance.now()
  for (;;) {
    await new Promise((r) => nativeSetTimeout(r, 0))
    if (pendingTimers === 0) return true
    if (performance.now() - started > capMs) return false
    await new Promise((r) => nativeSetTimeout(r, 10))
  }
}

// --- running -----------------------------------------------------------------

const DOM_HINT =
  /\b(document|window|localStorage|sessionStorage|navigator|location|useState|useEffect|React|render|screen|describe|test|expect)\b is not defined/

function asError(e: unknown): CodeError {
  const error = e instanceof Error ? e : new Error(String(e))
  const stack = (error.stack ?? '')
    .split('\n')
    .filter((l) => !/jsWorker|AsyncFunction|^\s*at (async )?(run|evaluate|compile|self\.addEventListener)/.test(l))
    .join('\n')
  const hint = DOM_HINT.test(error.message)
    ? 'This code needs a web page, React or a test framework, which the sandbox does not provide. It runs plain JavaScript only.'
    : error.name === 'SyntaxError' && /Unexpected token '<'/.test(error.message)
      ? 'That looks like JSX or HTML markup, which is not plain JavaScript and cannot run here.'
      : undefined
  return { type: error.name, message: error.message, traceback: stack || `${error.name}: ${error.message}`, hint }
}

const GLOBALS = ['console', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', ...SHADOWED]
const globalValues = () => [
  sandboxConsole,
  sandboxSetTimeout,
  sandboxClearTimeout,
  sandboxSetInterval,
  sandboxClearInterval,
  ...SHADOWED.map(noNetwork),
]

function compile(body: string) {
  return new AsyncFunction(...GLOBALS, body)
}

function execute(fn: (...args: unknown[]) => Promise<unknown>) {
  return fn(...globalValues())
}

function isExpression(source: string): boolean {
  try {
    compile(`return (${source}\n)`)
    return true
  } catch {
    return false
  }
}

function defined(code: string): string[] {
  const names = new Set<string>()
  for (const m of code.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)|\bclass\s+([A-Za-z_$][\w$]*)|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)/g)) {
    names.add(m[1] ?? m[2] ?? m[3])
  }
  return [...names]
}

async function run(code: string): Promise<RunResult> {
  const started = performance.now()
  let error: CodeError | null = null
  try {
    await execute(compile(code))
  } catch (e) {
    error = asError(e)
  }
  const settled = await settle()
  if (!error && uncaught.length) error = asError(uncaught[0])
  if (!settled) err.push('Stopped waiting for timers after 2 seconds; some are still scheduled.')
  return {
    ok: error === null,
    stdout: out.join('\n') + (out.length ? '\n' : ''),
    stderr: err.join('\n') + (err.length ? '\n' : ''),
    error,
    defined: defined(code),
    ms: Math.round(performance.now() - started),
  }
}

async function repl(code: string, history: string[], source: string) {
  const started = performance.now()
  // Replay the program and earlier statements silently, then evaluate this
  // entry with output on: state carries over without repeating its output.
  const prelude = `__bp_quiet(true);\n${code}\n;\n${history.join('\n;\n')}\n;__bp_quiet(false);\n`
  const expression = isExpression(source)
  const body = expression ? `${prelude}return (${source}\n);` : `${prelude}${source}\n;return undefined;`
  let value: string | null = null
  let error: CodeError | null = null
  let loadFailed = false
  try {
    const fn = new AsyncFunction('__bp_quiet', ...GLOBALS, body)
    const result = await fn((q: boolean) => {
      quiet = q
    }, ...globalValues())
    if (expression && result !== undefined) value = inspect(result, 1)
  } catch (e) {
    error = asError(e)
    // Output was still muted: the failure is in the program, not the entry.
    loadFailed = quiet
  }
  quiet = false
  await settle(1_000)
  return {
    ok: error === null,
    stdout: out.join('\n') + (out.length ? '\n' : ''),
    stderr: err.join('\n') + (err.length ? '\n' : ''),
    value,
    error,
    loadFailed,
    // Tell the client whether to keep this entry for replay.
    keep: error === null && !expression,
    ms: Math.round(performance.now() - started),
  }
}

function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b) || a === b) return true
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false
  if (Array.isArray(a) !== Array.isArray(b)) return false
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => deepEqual(v, b[i]))
  }
  const ka = Object.keys(a as object)
  const kb = Object.keys(b as object)
  return (
    ka.length === kb.length &&
    ka.every((k) => deepEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]))
  )
}

async function tests(code: string, cases: { call: string; expected: string }[]) {
  const usable = cases.filter((c) => c.call.trim())
  const thunks = usable
    .map((c) => {
      const raises = c.expected.trim().startsWith('raises ')
      const expected = raises || !c.expected.trim() ? 'undefined' : `(${c.expected}\n)`
      return `[async () => (${c.call}\n), async () => ${expected}]`
    })
    .join(',\n')
  let pairs: [() => Promise<unknown>, () => Promise<unknown>][]
  try {
    // One module for all cases, as a test file would have.
    pairs = (await execute(compile(`${code}\n;return [\n${thunks}\n];`))) as typeof pairs
  } catch (e) {
    return { loadError: asError(e), results: [] }
  }
  const results: TestResult[] = []
  for (const [i, c] of usable.entries()) {
    const raises = c.expected.trim().startsWith('raises ')
    out.length = 0
    outLength = 0
    const result: TestResult = {
      call: c.call,
      expected: c.expected,
      passed: false,
      actual: null,
      error: null,
      stdout: '',
    }
    try {
      const actual = await pairs[i][0]()
      result.actual = inspect(actual, 1)
      if (raises) {
        result.error = { type: '', message: 'no exception was thrown', traceback: '' }
      } else if (c.expected.trim()) {
        const expected = await pairs[i][1]()
        result.expectedValue = inspect(expected, 1)
        result.passed = deepEqual(actual, expected)
      }
    } catch (e) {
      result.error = asError(e)
      if (raises) {
        const wanted = c.expected.trim().slice('raises '.length).trim()
        result.passed = result.error.type === wanted
      }
    }
    result.stdout = out.join('\n')
    results.push(result)
  }
  return { loadError: null, results }
}

self.addEventListener('message', async (event: MessageEvent<CodeRequest>) => {
  const req = event.data
  const reply = (message: CodeReply) => self.postMessage(message)
  try {
    let data: unknown
    if (req.kind === 'load' || req.kind === 'reset') data = { version: 'JavaScript' }
    else if (req.kind === 'run') data = await run(req.code)
    else if (req.kind === 'repl') data = await repl(req.code, req.history, req.source)
    else if (req.kind === 'tests') data = await tests(req.code, req.cases)
    else data = { loadError: { type: 'Error', message: 'The step-through debugger is available for Python code.', traceback: '' }, steps: [] }
    reply({ id: req.id, ok: true, data })
  } catch (e) {
    reply({ id: req.id, ok: false, error: (e as Error)?.message ?? String(e) })
  }
})
