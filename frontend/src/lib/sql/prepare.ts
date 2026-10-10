/** Turn an investigation's artifact into a PostgreSQL database to query.
 *
 * Databases artifacts arrive in three shapes, and all of them are loaded:
 *
 *   * data tables  - `{ columns, rows }`, with the string "NULL" meaning NULL.
 *     They become real tables. Column types are inferred from the values,
 *     because some investigations turn on them (integer division needs
 *     INTEGER columns, not NUMERIC ones).
 *   * SQL schemas  - `CREATE TABLE ...` text, run exactly as written, so its
 *     constraints (PRIMARY KEY implies NOT NULL, foreign keys, ...) apply.
 *   * shorthand    - `employees(name, dept, salary)`: tables with those
 *     columns, typed as text and empty unless a data table fills them.
 *
 * Only data tables the query or schema actually mentions are loaded, since an
 * artifact can also carry a table that is the AI's claimed *result* rather
 * than something to query.
 *
 * Pure functions with no browser dependencies, so they are testable in Node
 * (see prepare.test.mjs).
 */

export interface SeedPlan {
  /** Statements that build the starting database, in order. */
  seed: string[]
  /** The artifact's own SQL - what the Query Executor runs. */
  query: string
  /** Tables created, for the panel's summary line. */
  tables: string[]
  /** Anything that could not be loaded as given, said plainly. */
  notes: string[]
  /** False when the artifact is not SQL at all (a MongoDB snippet, a Redis
   *  config): there is nothing to run, only an empty database to explore. */
  isSql: boolean
}

interface DataTable {
  columns: string[]
  rows: unknown[][]
}

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/

export function quoteIdent(name: string): string {
  return `"${name.replace(/"/g, '""')}"`
}

function isNullLike(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim().toUpperCase() === 'NULL')
}

function asDataTable(value: unknown): DataTable | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const v = value as Record<string, unknown>
  if (!Array.isArray(v.columns) || !Array.isArray(v.rows)) return null
  if (!v.columns.every((c) => typeof c === 'string')) return null
  if (!v.rows.every((r) => Array.isArray(r))) return null
  return { columns: v.columns as string[], rows: v.rows as unknown[][] }
}

/** The narrowest PostgreSQL type that holds every non-NULL value. */
export function inferType(values: unknown[]): string {
  const present = values.filter((v) => !isNullLike(v))
  if (present.length === 0) return 'TEXT'
  if (present.every((v) => typeof v === 'boolean')) return 'BOOLEAN'
  if (present.every((v) => typeof v === 'number' && Number.isFinite(v))) {
    const nums = present as number[]
    if (nums.every(Number.isInteger)) {
      return nums.every((n) => Math.abs(n) <= 2_147_483_647) ? 'INTEGER' : 'BIGINT'
    }
    return 'NUMERIC'
  }
  if (present.every((v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v))) return 'DATE'
  if (
    present.every(
      (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(v),
    )
  ) {
    return 'TIMESTAMP'
  }
  return 'TEXT'
}

export function literal(v: unknown): string {
  if (isNullLike(v)) return 'NULL'
  if (typeof v === 'number' && Number.isFinite(v)) return String(v)
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE'
  const text = typeof v === 'string' ? v : JSON.stringify(v)
  return `'${text.replace(/'/g, "''")}'`
}

function tableStatements(name: string, table: DataTable): string[] {
  const types = table.columns.map((_, i) => inferType(table.rows.map((r) => r[i])))
  const cols = table.columns.map((c, i) => `  ${quoteIdent(c)} ${types[i]}`).join(',\n')
  const out = [`CREATE TABLE IF NOT EXISTS ${quoteIdent(name)} (\n${cols}\n)`]
  if (table.rows.length > 0) {
    const values = table.rows
      .map((r) => `  (${table.columns.map((_, i) => literal(r[i])).join(', ')})`)
      .join(',\n')
    out.push(
      `INSERT INTO ${quoteIdent(name)} (${table.columns.map(quoteIdent).join(', ')}) VALUES\n${values}`,
    )
  }
  return out
}

function mentions(text: string, name: string): boolean {
  return new RegExp(`\\b${name}\\b`, 'i').test(text)
}

const SHORTHAND = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(([^()]*)\)\s*;?\s*$/

export function planDatabase(artifact: Record<string, unknown>): SeedPlan {
  const notes: string[] = []
  const seed: string[] = []
  const tables: string[] = []

  const code =
    typeof artifact.code === 'string' &&
    typeof artifact.language === 'string' &&
    /sql|postgres/i.test(artifact.language)
      ? artifact.code
      : ''
  const query = typeof artifact.query === 'string' ? artifact.query : code
  const schema = typeof artifact.schema === 'string' ? artifact.schema : ''

  // --- schema --------------------------------------------------------------
  const shorthand = new Map<string, string[]>()
  if (schema.trim()) {
    if (/\bcreate\s+(table|index|unique|view|type|sequence)\b/i.test(schema)) {
      seed.push(...splitStatements(schema))
      for (const m of schema.matchAll(/create\s+table\s+(?:if\s+not\s+exists\s+)?"?([A-Za-z_][A-Za-z0-9_]*)/gi)) {
        tables.push(m[1])
      }
    } else {
      const lines = schema.split('\n').filter((l) => l.trim())
      const parsed = lines.map((l) => SHORTHAND.exec(l))
      if (parsed.length > 0 && parsed.every(Boolean)) {
        for (const m of parsed as RegExpExecArray[]) {
          shorthand.set(
            m[1],
            m[2].split(',').map((c) => c.trim()).filter((c) => IDENT.test(c)),
          )
        }
      } else {
        notes.push('The schema is described in words rather than SQL, so it was not loaded.')
      }
    }
  }

  // --- data tables -----------------------------------------------------------
  const referenceText = `${query}\n${schema}`
  const data = Object.entries(artifact)
    .map(([key, value]) => [key, asDataTable(value)] as const)
    .filter((entry): entry is readonly [string, DataTable] => entry[1] !== null)
  for (const [name, table] of data) {
    if (!IDENT.test(name)) {
      notes.push(`"${name}" is not a usable table name, so that table was not loaded.`)
      continue
    }
    // With a query, load only what it can refer to: an artifact may also show
    // the AI's claimed result as a table, and that is not data to query.
    if (query && !mentions(referenceText, name)) continue
    seed.push(...tableStatements(name, table))
    if (!tables.includes(name)) tables.push(name)
    shorthand.delete(name)
  }

  // Shorthand tables that no data table filled: columns known, types not.
  for (const [name, columns] of shorthand) {
    if (columns.length === 0) continue
    seed.push(
      `CREATE TABLE IF NOT EXISTS ${quoteIdent(name)} (\n${columns
        .map((c) => `  ${quoteIdent(c)} TEXT`)
        .join(',\n')}\n)`,
    )
    tables.push(name)
    notes.push(
      `${name} is described only by its columns, so it starts empty with text columns. Insert rows in the SQL Editor to try the query.`,
    )
  }

  const isSql = Boolean(query.trim() || seed.length > 0)
  return { seed, query, tables, notes, isSql }
}

/** Split SQL into statements on top-level semicolons.
 *
 * Semicolons inside '...' strings, "..." identifiers, $tag$ ... $tag$ bodies
 * and comments do not split. Empty statements and comment-only fragments are
 * dropped. Each statement is returned trimmed, without its semicolon.
 */
export function splitStatements(sql: string): string[] {
  const out: string[] = []
  let current = ''
  let i = 0
  const n = sql.length
  while (i < n) {
    const ch = sql[i]
    const next = sql[i + 1]
    if (ch === '-' && next === '-') {
      const end = sql.indexOf('\n', i)
      const stop = end === -1 ? n : end
      current += sql.slice(i, stop)
      i = stop
      continue
    }
    if (ch === '/' && next === '*') {
      const end = sql.indexOf('*/', i + 2)
      const stop = end === -1 ? n : end + 2
      current += sql.slice(i, stop)
      i = stop
      continue
    }
    if (ch === "'" || ch === '"') {
      let j = i + 1
      while (j < n) {
        if (sql[j] === ch) {
          if (sql[j + 1] === ch) {
            j += 2 // doubled quote is an escaped quote
            continue
          }
          break
        }
        j++
      }
      current += sql.slice(i, Math.min(j + 1, n))
      i = j + 1
      continue
    }
    if (ch === '$') {
      const tag = /^\$[A-Za-z_]?[A-Za-z0-9_]*\$/.exec(sql.slice(i))
      if (tag) {
        const end = sql.indexOf(tag[0], i + tag[0].length)
        const stop = end === -1 ? n : end + tag[0].length
        current += sql.slice(i, stop)
        i = stop
        continue
      }
    }
    if (ch === ';') {
      push(out, current)
      current = ''
      i++
      continue
    }
    current += ch
    i++
  }
  push(out, current)
  return out
}

function push(out: string[], statement: string) {
  const trimmed = statement.trim()
  // Drop fragments that are only comments, e.g. a trailing "-- note".
  const withoutComments = trimmed
    .replace(/--[^\n]*/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .trim()
  if (withoutComments) out.push(trimmed)
}

/** Databases the question may be about that are not PostgreSQL. */
export function otherDialect(text: string): string | null {
  const m = /\b(MySQL|MariaDB|SQLite|SQL Server|T-SQL|Oracle)\b/i.exec(text)
  return m ? m[1] : null
}
