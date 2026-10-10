/** Regression tests for the calculator parser.
 *
 * The parser is hand-written (no eval), so it needs real coverage.
 * Run with:  npx vite-node src/lib/calc.test.mjs
 */
import { evaluate } from './calc.ts'
const cases = [
  ['2+3', 5], ['10-4', 6], ['3*4', 12], ['12/4', 3],
  ['2+3*4', 14], ['(2+3)*4', 20], ['2^3', 8], ['2^3^2', 512],
  ['20 % 800', 160], ['-5+3', -2], ['-(2+3)', -5], ['1000*0.8*1.2', 960],
  ['(3*40+2*60)/5', 48], ['100/3', 33.333333333333336],
  // Unary minus after another operator. Encoding it as "0 - x" gave -2, -1
  // and a division-by-zero error for the first three.
  ['3*-2', -6], ['2^-2', 0.25], ['10/-5', -2], ['-2^2', -4], ['2*-(1+2)', -6],
  ['--3', 3], ['5--3', 8], ['1,000+1', 1001],
]
let fail = 0
for (const [expr, want] of cases) {
  let got
  try { got = evaluate(expr) } catch (e) { got = 'ERR:' + e.message }
  const ok = typeof got === 'number' && Math.abs(got - want) < 1e-9
  if (!ok) { fail++; console.log(`  FAIL ${expr} -> ${got}, want ${want}`) }
  else console.log(`  ok   ${expr.padEnd(16)} = ${got}`)
}
console.log('\nerror handling:')
for (const bad of ['2+', '(2+3', '2)+3', '1/0', 'alert(1)', '', '2*/3', '-']) {
  try { console.log(`  ${JSON.stringify(bad).padEnd(12)} -> ${evaluate(bad)}  (should have thrown!)`); fail++ }
  catch (e) { console.log(`  ${JSON.stringify(bad).padEnd(12)} -> rejected: ${e.message}`) }
}
console.log(fail ? `\n${fail} FAILURES` : '\nall calculator cases pass')
process.exit(fail ? 1 : 0)
