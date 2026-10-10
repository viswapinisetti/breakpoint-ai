/** Messages between the SQL tools and the PostgreSQL worker. */

export interface SqlError {
  message: string
  /** SQLSTATE, e.g. 23502 for a NOT NULL violation. */
  code?: string
  detail?: string
  hint?: string
}

export interface StatementResult {
  sql: string
  ok: boolean
  /** Command tag, e.g. SELECT, INSERT, CREATE. */
  command: string
  columns: string[]
  /** Values as PostgreSQL prints them; null is SQL NULL. */
  rows: (string | null)[][]
  /** Rows returned (SELECT) or changed (INSERT/UPDATE/DELETE). */
  rowCount: number
  /** More rows came back than are sent to the page. */
  truncated: boolean
  error?: SqlError
  ms: number
}

export interface SchemaColumn {
  name: string
  type: string
  nullable: boolean
  default: string | null
  keys: string[]
}

export interface SchemaTable {
  name: string
  rowCount: number
  columns: SchemaColumn[]
  indexes: string[]
}

export interface LoadReport {
  version: string
  /** Seed statements PostgreSQL refused, with its reason. */
  failures: { sql: string; message: string }[]
}

export type Request =
  | { id: number; kind: 'load'; seed: string[] }
  | { id: number; kind: 'reset' }
  | { id: number; kind: 'run'; sql: string }
  | { id: number; kind: 'schema' }

export type Reply =
  | { id: number; ok: true; kind: 'load'; report: LoadReport }
  | { id: number; ok: true; kind: 'run'; results: StatementResult[] }
  | { id: number; ok: true; kind: 'schema'; tables: SchemaTable[] }
  | { id: number; ok: false; error: string }

/** Rows sent back per statement; the page is not a data export tool. */
export const MAX_ROWS = 200
