/** Tests for the SQL sandbox's artifact loader and statement splitter.
 *
 * Run with:  node src/lib/sql/prepare.test.mjs
 */
import { inferType, planDatabase, splitStatements } from './prepare.ts'

let fail = 0
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fail++
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`}`)
}

console.log('splitting statements')
eq('two statements', splitStatements('SELECT 1; SELECT 2;'), ['SELECT 1', 'SELECT 2'])
eq('semicolon in a string', splitStatements("SELECT 'a;b'; SELECT 2"), ["SELECT 'a;b'", 'SELECT 2'])
eq('escaped quote', splitStatements("SELECT 'it''s; fine'"), ["SELECT 'it''s; fine'"])
eq('quoted identifier', splitStatements('SELECT "a;b" FROM t'), ['SELECT "a;b" FROM t'])
eq('line comment kept with its statement, not split',
  splitStatements('SELECT 1 -- a; b\n; SELECT 2'), ['SELECT 1 -- a; b', 'SELECT 2'])
eq('trailing comment-only fragment dropped',
  splitStatements('SELECT passed / total FROM results;   -- INTEGER columns'),
  ['SELECT passed / total FROM results'])
eq('block comment', splitStatements('SELECT /* ; */ 1'), ['SELECT /* ; */ 1'])
eq('dollar-quoted body', splitStatements('CREATE FUNCTION f() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql; SELECT f()'),
  ['CREATE FUNCTION f() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql', 'SELECT f()'])

console.log('\ninferring column types')
eq('integers', inferType([1, 2, 3]), 'INTEGER')
eq('integers with NULL', inferType([5, 'NULL', 7]), 'INTEGER')
eq('decimals', inferType([1.5, 2]), 'NUMERIC')
eq('dates', inferType(['2026-01-05', '2026-02-10']), 'DATE')
eq('text', inferType(['Asha', 'Ben']), 'TEXT')
eq('mixed falls back to text', inferType([1, 'two']), 'TEXT')
eq('all NULL is text', inferType(['NULL']), 'TEXT')

console.log('\nplanning databases from real artifact shapes')
const pk = planDatabase({
  schema: 'CREATE TABLE users (\n  email VARCHAR(255) PRIMARY KEY,\n  name  VARCHAR(100)\n);',
  query: "INSERT INTO users (email, name) VALUES (NULL, 'Asha');\nINSERT INTO users (email, name) VALUES (NULL, 'Ben');",
})
eq('SQL schema runs as written', pk.seed.length, 1)
eq('its table is listed', pk.tables, ['users'])
eq('the query is kept for the executor', splitStatements(pk.query).length, 2)

const nulls = planDatabase({
  t: { title: 't', columns: ['x'], rows: [[5], [3], ['NULL'], [7]] },
  query: 'SELECT COUNT(*) FROM t\nWHERE x <> 5;',
})
eq('data table becomes an INTEGER column', nulls.seed[0].includes('"x" INTEGER'), true)
eq('"NULL" is loaded as NULL', nulls.seed[1].includes('(NULL)'), true)

const claimedResult = planDatabase({
  schema: 'customers(id, name)\norders(id, customer_id, amount)',
  result: { title: 'result', columns: ['name', 'total'], rows: [['Asha Rao', 900]] },
  query: 'SELECT c.name, SUM(o.amount) AS total\nFROM customers c\nJOIN orders o ON o.customer_id = c.id\nGROUP BY c.name;',
})
eq("the AI's claimed result is not loaded as data", claimedResult.tables.includes('result'), false)
eq('shorthand schema becomes empty tables', claimedResult.tables, ['customers', 'orders'])
eq('and says so', claimedResult.notes.length, 2)

const results = planDatabase({
  results: { title: 'results', columns: ['subject', 'total', 'passed'], rows: [['Maths', 4, 3]] },
  query: 'SELECT subject, passed / total * 100 AS pass_pct\nFROM results;   -- total and passed are INTEGER columns',
})
eq('a table named "results" that the query reads is loaded', results.tables, ['results'])
eq('with INTEGER columns, so integer division applies',
  /"total" INTEGER[\s\S]*"passed" INTEGER/.test(results.seed[0]), true)

const mongo = planDatabase({ language: 'javascript', code: 'db.collection("users").find({})' })
eq('a MongoDB snippet is not SQL', mongo.isSql, false)

const sqlCode = planDatabase({ language: 'sql', code: 'SELECT 1;' })
eq('code in SQL is the query', sqlCode.query, 'SELECT 1;')

const odd = planDatabase({
  documents: { title: 'embeddings (not normalised)', columns: ['doc', 'vector'], rows: [['A', '[3, 3]']] },
})
eq('with no query, every usable table loads', odd.tables, ['documents'])

console.log(fail ? `\n${fail} FAILURES` : '\nall SQL sandbox preparation cases pass')
process.exit(fail ? 1 : 0)
