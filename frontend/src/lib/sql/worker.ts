/** PostgreSQL for the Databases investigation tools, in a Web Worker.
 *
 * PGlite is the real PostgreSQL server compiled to WebAssembly, so a query
 * behaves exactly as the investigations describe - a PRIMARY KEY column
 * rejects NULL, integer division truncates - which an SQLite stand-in would
 * get wrong. It runs in the student's browser, so nothing reaches the server.
 *
 * It lives in a worker so a runaway statement (a recursive CTE with no stop)
 * cannot freeze the page: the client terminates the worker on a timeout and
 * starts a fresh one.
 */

import { PGlite } from '@electric-sql/pglite'
import {
  MAX_ROWS,
  type LoadReport,
  type Reply,
  type Request,
  type SchemaTable,
  type SqlError,
  type StatementResult,
} from './protocol'
import { quoteIdent, splitStatements } from './prepare'

// Keep these types as PostgreSQL's own text rather than JS values: a DATE
// should read 2026-01-05, not a timezone-shifted timestamp, and NUMERIC keeps
// its exact digits.
const RAW = (value: string) => value
const RAW_TEXT_TYPES = [
  20, // int8
  114, // json
  1082, // date
  1083, // time
  1114, // timestamp
  1184, // timestamptz
  1186, // interval
  1266, // timetz
  1700, // numeric
  3802, // jsonb
]
const parsers = Object.fromEntries(RAW_TEXT_TYPES.map((oid) => [oid, RAW]))

let db: PGlite | null = null
let seed: string[] = []

function display(value: unknown): string | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'number' || typeof value === 'bigint') return String(value)
  if (Array.isArray(value)) return `{${value.map((v) => display(v) ?? 'NULL').join(',')}}`
  if (value instanceof Date) return value.toISOString()
  if (value instanceof Uint8Array) {
    return `\\x${Array.from(value, (b) => b.toString(16).padStart(2, '0')).join('')}`
  }
  return JSON.stringify(value)
}

function asSqlError(e: unknown): SqlError {
  const err = e as { message?: string; code?: string; detail?: string; hint?: string }
  return {
    message: err?.message ?? String(e),
    code: err?.code,
    detail: err?.detail,
    hint: err?.hint,
  }
}

function commandOf(sql: string): string {
  const stripped = sql.replace(/--[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '').trim()
  return (stripped.split(/\s+/)[0] ?? '').toUpperCase()
}

async function runOne(target: PGlite, sql: string): Promise<StatementResult> {
  const started = performance.now()
  try {
    const results = await target.exec(sql, { rowMode: 'array', parsers })
    const last = results[results.length - 1]
    const rows = ((last?.rows ?? []) as unknown[][]).map((r) => r.map(display))
    const returnsRows = (last?.fields.length ?? 0) > 0
    return {
      sql,
      ok: true,
      command: last?.command ?? commandOf(sql),
      columns: last?.fields.map((f) => f.name) ?? [],
      rows: rows.slice(0, MAX_ROWS),
      rowCount: returnsRows ? rows.length : (last?.affectedRows ?? 0),
      truncated: rows.length > MAX_ROWS,
      ms: Math.round(performance.now() - started),
    }
  } catch (e) {
    return {
      sql,
      ok: false,
      command: commandOf(sql),
      columns: [],
      rows: [],
      rowCount: 0,
      truncated: false,
      error: asSqlError(e),
      ms: Math.round(performance.now() - started),
    }
  }
}

async function applySeed(target: PGlite): Promise<LoadReport['failures']> {
  const failures: LoadReport['failures'] = []
  for (const statement of seed) {
    const r = await runOne(target, statement)
    if (!r.ok) failures.push({ sql: statement, message: r.error?.message ?? 'failed' })
  }
  return failures
}

async function load(statements: string[]): Promise<LoadReport> {
  seed = statements
  if (db) await db.close().catch(() => {})
  db = await PGlite.create()
  const version =
    (await db.query<{ v: string }>("SELECT current_setting('server_version') AS v")).rows[0]?.v ?? ''
  return { version, failures: await applySeed(db) }
}

/** Back to the investigation's own data, in milliseconds rather than the
 *  seconds a fresh PGlite takes to start. */
async function reset(target: PGlite): Promise<void> {
  await target.exec('ROLLBACK').catch(() => {})
  await target.exec('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
  await applySeed(target)
}

async function schema(target: PGlite): Promise<SchemaTable[]> {
  const columns = await target.query<{
    table_name: string
    column_name: string
    type: string
    is_nullable: string
    column_default: string | null
  }>(`
    SELECT c.table_name, c.column_name,
           format_type(a.atttypid, a.atttypmod) AS type,
           c.is_nullable, c.column_default
    FROM information_schema.columns c
    JOIN pg_attribute a
      ON a.attrelid = format('%I.%I', c.table_schema, c.table_name)::regclass
     AND a.attname = c.column_name
    WHERE c.table_schema = 'public'
    ORDER BY c.table_name, c.ordinal_position`)
  const keys = await target.query<{
    table_name: string
    column_name: string
    constraint_type: string
    ref_table: string | null
    ref_column: string | null
  }>(`
    SELECT tc.table_name, kcu.column_name, tc.constraint_type,
           ccu.table_name AS ref_table, ccu.column_name AS ref_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name
     AND kcu.table_schema = tc.table_schema
    LEFT JOIN information_schema.constraint_column_usage ccu
      ON tc.constraint_type = 'FOREIGN KEY'
     AND ccu.constraint_name = tc.constraint_name
     AND ccu.table_schema = tc.table_schema
    WHERE tc.table_schema = 'public'`)
  const indexes = await target.query<{ tablename: string; indexdef: string }>(
    `SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY indexname`,
  )

  const tables = new Map<string, SchemaTable>()
  for (const c of columns.rows) {
    const table = tables.get(c.table_name) ?? {
      name: c.table_name,
      rowCount: 0,
      columns: [],
      indexes: [],
    }
    table.columns.push({
      name: c.column_name,
      type: c.type,
      nullable: c.is_nullable === 'YES',
      default: c.column_default,
      keys: [],
    })
    tables.set(c.table_name, table)
  }
  for (const k of keys.rows) {
    const column = tables.get(k.table_name)?.columns.find((c) => c.name === k.column_name)
    if (!column) continue
    column.keys.push(
      k.constraint_type === 'PRIMARY KEY'
        ? 'PK'
        : k.constraint_type === 'FOREIGN KEY'
          ? `FK → ${k.ref_table}.${k.ref_column}`
          : k.constraint_type === 'UNIQUE'
            ? 'UNIQUE'
            : k.constraint_type,
    )
  }
  for (const ix of indexes.rows) tables.get(ix.tablename)?.indexes.push(ix.indexdef)
  for (const table of tables.values()) {
    const count = await target.query<{ n: number }>(
      `SELECT count(*)::int AS n FROM ${quoteIdent(table.name)}`,
    )
    table.rowCount = count.rows[0]?.n ?? 0
  }
  return [...tables.values()]
}

function reply(message: Reply) {
  self.postMessage(message)
}

self.addEventListener('message', async (event: MessageEvent<Request>) => {
  const req = event.data
  try {
    if (req.kind === 'load') {
      reply({ id: req.id, ok: true, kind: 'load', report: await load(req.seed) })
      return
    }
    if (!db) throw new Error('The database is not loaded yet.')
    if (req.kind === 'reset') {
      await reset(db)
      reply({ id: req.id, ok: true, kind: 'run', results: [] })
    } else if (req.kind === 'run') {
      const results: StatementResult[] = []
      for (const statement of splitStatements(req.sql)) {
        results.push(await runOne(db, statement))
      }
      reply({ id: req.id, ok: true, kind: 'run', results })
    } else if (req.kind === 'schema') {
      reply({ id: req.id, ok: true, kind: 'schema', tables: await schema(db) })
    }
  } catch (e) {
    reply({ id: req.id, ok: false, error: asSqlError(e).message })
  }
})
