/** One code sandbox per open investigation, shared by its code tools.
 *
 * Python keeps one worker, because Pyodide takes seconds to start and the
 * Terminal's variables live in it. JavaScript starts a fresh worker for every
 * request, which is cheap and guarantees one run's timers and globals never
 * reach the next. Either way a request running past RUN_TIMEOUT_MS is stopped
 * by terminating its worker - the only reliable way to interrupt a loop.
 */

import type { Runtime, TestCase } from './plan'
import type {
  CodeReply,
  CodeRequest,
  ReplResult,
  RunResult,
  TestsResult,
  TraceResult,
} from './protocol'

export const RUN_TIMEOUT_MS = 5_000
const LOAD_TIMEOUT_MS = 120_000

export interface CodeSession {
  runtime: Runtime
  /** Resolves once the runtime is loaded; the first Python start downloads
   *  and compiles CPython. */
  ready: () => Promise<{ version: string }>
  run: (code: string) => Promise<RunResult>
  repl: (code: string, source: string) => Promise<ReplResult>
  resetTerminal: () => Promise<void>
  tests: (code: string, cases: TestCase[]) => Promise<TestsResult>
  trace: (code: string, source: string) => Promise<TraceResult>
  dispose: () => void
}

type Payload =
  | { kind: 'load' }
  | { kind: 'run'; code: string }
  | { kind: 'repl'; code: string; source: string; history: string[] }
  | { kind: 'reset' }
  | { kind: 'tests'; code: string; cases: TestCase[] }
  | { kind: 'trace'; code: string; source: string }

function spawn(runtime: Runtime): Worker {
  return runtime === 'python'
    ? new Worker(new URL('./pyWorker.ts', import.meta.url), { type: 'module' })
    : new Worker(new URL('./jsWorker.ts', import.meta.url), { type: 'module' })
}

export function createCodeSession(runtime: Runtime): CodeSession {
  let worker: Worker | null = null
  let loading: Promise<{ version: string }> | null = null
  let nextId = 1
  const pending = new Map<
    number,
    { resolve: (d: unknown) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout>; own: Worker }
  >()
  // JavaScript Terminal state: statements to replay before each entry.
  let history: string[] = []
  let historyCode: string | null = null

  function kill(target: Worker, reason: Error) {
    target.terminate()
    if (worker === target) {
      worker = null
      loading = null
    }
    for (const [id, p] of pending) {
      if (p.own !== target) continue
      clearTimeout(p.timer)
      p.reject(reason)
      pending.delete(id)
    }
  }

  function attach(w: Worker) {
    w.addEventListener('message', (event: MessageEvent<CodeReply>) => {
      const p = pending.get(event.data.id)
      if (!p) return
      pending.delete(event.data.id)
      clearTimeout(p.timer)
      if (event.data.ok) p.resolve(event.data.data)
      else p.reject(new Error(event.data.error))
      // JavaScript workers are single-use.
      if (runtime === 'javascript') w.terminate()
    })
    w.addEventListener('error', (event) => {
      kill(w, new Error(event.message || 'The code sandbox stopped unexpectedly.'))
    })
    return w
  }

  function send<T>(payload: Payload, timeoutMs: number): Promise<T> {
    const target =
      runtime === 'python' ? (worker ??= attach(spawn(runtime))) : attach(spawn(runtime))
    const id = nextId++
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        const restarted =
          runtime === 'python'
            ? ' Python was restarted, so Terminal variables were cleared.'
            : ''
        kill(target, new Error(`Stopped after ${timeoutMs / 1000} seconds - is there an infinite loop?${restarted}`))
      }, timeoutMs)
      pending.set(id, { resolve: resolve as (d: unknown) => void, reject, timer, own: target })
      target.postMessage({ id, ...payload } as CodeRequest)
    })
  }

  function ready() {
    if (runtime === 'javascript') return Promise.resolve({ version: 'JavaScript' })
    loading ??= send<{ version: string }>({ kind: 'load' }, LOAD_TIMEOUT_MS)
    loading.catch(() => {
      loading = null
    })
    return loading
  }

  return {
    runtime,
    ready,
    async run(code) {
      await ready()
      return send<RunResult>({ kind: 'run', code }, RUN_TIMEOUT_MS)
    },
    async repl(code, source) {
      await ready()
      if (historyCode !== code) {
        history = []
        historyCode = code
      }
      const result = await send<ReplResult & { keep?: boolean }>(
        { kind: 'repl', code, source, history },
        RUN_TIMEOUT_MS,
      )
      if (result.keep) history = [...history, source]
      return result
    },
    async resetTerminal() {
      history = []
      if (runtime === 'python' && worker) {
        await send({ kind: 'reset' }, RUN_TIMEOUT_MS)
      }
    },
    async tests(code, cases) {
      await ready()
      return send<TestsResult>({ kind: 'tests', code, cases }, RUN_TIMEOUT_MS)
    },
    async trace(code, source) {
      await ready()
      return send<TraceResult>({ kind: 'trace', code, source }, RUN_TIMEOUT_MS)
    },
    dispose() {
      if (worker) kill(worker, new Error('closed'))
      for (const p of pending.values()) p.own.terminate()
    },
  }
}
