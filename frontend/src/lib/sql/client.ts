/** One PostgreSQL sandbox per open investigation, shared by its SQL tools.
 *
 * The worker starts only when a SQL tool is first opened, so nothing is
 * downloaded for students who never use one. A statement that runs past
 * RUN_TIMEOUT_MS is stopped by terminating the worker - the only reliable way
 * to interrupt WebAssembly - and the next request starts a fresh one with the
 * investigation's data reloaded.
 */

import type { LoadReport, Reply, Request, SchemaTable, StatementResult } from './protocol'

export const RUN_TIMEOUT_MS = 5_000
// The first start downloads and compiles PostgreSQL (several MB).
const LOAD_TIMEOUT_MS = 90_000

export class SqlTimeoutError extends Error {}

type Pending = {
  resolve: (reply: Reply) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}

export interface SqlSession {
  /** Resolves once PostgreSQL is running with the investigation's data. */
  ready: () => Promise<LoadReport>
  run: (sql: string) => Promise<StatementResult[]>
  /** Back to the investigation's original data. */
  reset: () => Promise<void>
  schema: () => Promise<SchemaTable[]>
  dispose: () => void
}

type Payload =
  | { kind: 'load'; seed: string[] }
  | { kind: 'reset' }
  | { kind: 'run'; sql: string }
  | { kind: 'schema' }

export function createSqlSession(seed: string[]): SqlSession {
  let worker: Worker | null = null
  let loading: Promise<LoadReport> | null = null
  let nextId = 1
  const pending = new Map<number, Pending>()

  function stop(reason: Error) {
    worker?.terminate()
    worker = null
    loading = null
    for (const p of pending.values()) {
      clearTimeout(p.timer)
      p.reject(reason)
    }
    pending.clear()
  }

  function start(): Worker {
    const w = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
    w.addEventListener('message', (event: MessageEvent<Reply>) => {
      const p = pending.get(event.data.id)
      if (!p) return
      pending.delete(event.data.id)
      clearTimeout(p.timer)
      p.resolve(event.data)
    })
    w.addEventListener('error', (event) => {
      stop(new Error(event.message || 'The SQL sandbox stopped unexpectedly.'))
    })
    return w
  }

  function send(payload: Payload, timeoutMs: number): Promise<Reply> {
    worker ??= start()
    const target = worker
    const id = nextId++
    return new Promise<Reply>((resolve, reject) => {
      const timer = setTimeout(() => {
        stop(
          new SqlTimeoutError(
            `Stopped after ${timeoutMs / 1000} seconds. The database was reset to this investigation's data.`,
          ),
        )
      }, timeoutMs)
      pending.set(id, { resolve, reject, timer })
      target.postMessage({ id, ...payload } satisfies Request)
    })
  }

  function unwrap(reply: Reply): Extract<Reply, { ok: true }> {
    if (!reply.ok) throw new Error(reply.error)
    return reply
  }

  function ready(): Promise<LoadReport> {
    loading ??= send({ kind: 'load', seed }, LOAD_TIMEOUT_MS).then((r) => {
      const ok = unwrap(r)
      if (ok.kind !== 'load') throw new Error('unexpected reply')
      return ok.report
    })
    // A failed start must not be cached, or the tools could never retry.
    loading.catch(() => {
      loading = null
    })
    return loading
  }

  return {
    ready,
    async run(sql) {
      await ready()
      const r = unwrap(await send({ kind: 'run', sql }, RUN_TIMEOUT_MS))
      return r.kind === 'run' ? r.results : []
    },
    async reset() {
      await ready()
      unwrap(await send({ kind: 'reset' }, RUN_TIMEOUT_MS))
    },
    async schema() {
      await ready()
      const r = unwrap(await send({ kind: 'schema' }, RUN_TIMEOUT_MS))
      return r.kind === 'schema' ? r.tables : []
    },
    dispose() {
      stop(new Error('closed'))
    },
  }
}
