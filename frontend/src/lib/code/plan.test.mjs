/** Tests for the code tools' artifact planner.
 *
 * Run with:  node src/lib/code/plan.test.mjs
 */
import { looksLikeJsx, parseAssert, planCode } from './plan.ts'

let fail = 0
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  if (!ok) fail++
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`}`)
}

const py = planCode({ language: 'python', code: 'def to_minutes(seconds):\n    return seconds // 60' })
eq('python runs on the python runtime', py.runtime, 'python')
eq('its first function is found', py.entry, 'to_minutes')

const bt = planCode({
  language: 'python',
  code: 'def median(numbers):\n    return sorted(numbers)[len(numbers) // 2]',
  tests: ['assert median([1, 2, 3]) == 2', 'assert median([7]) == 7'],
})
eq("the artifact's own asserts become test rows", bt.tests, [
  { call: 'median([1, 2, 3])', expected: '2' },
  { call: 'median([7])', expected: '7' },
])
eq('assert with a string', parseAssert('assert count_words("hello world") == 2'),
  { call: 'count_words("hello world")', expected: '2' })

const js = planCode({ language: 'javascript', code: 'function isMissing(value) {\n  return value == null;\n}' })
eq('javascript runs on the javascript runtime', js.runtime, 'javascript')
eq('function declaration found', js.entry, 'isMissing')
eq('arrow function found', planCode({ language: 'javascript', code: 'const add = (a, b) => a + b' }).entry, 'add')
eq('no function is fine', planCode({ language: 'javascript', code: 'const s = [10, 1, 2]; s.sort();' }).entry, null)
eq('javascript says what it lacks', js.note.includes('no web page'), true)

for (const lang of ['jsx', 'typescript', 'css', 'html', 'bash', 'c', 'dockerfile']) {
  eq(`${lang} does not run`, planCode({ language: lang, code: 'x' }).runtime, null)
}
eq('and says why', planCode({ language: 'jsx', code: '<App />' }).note.includes('jsx, which cannot run'), true)

const component = planCode({
  language: 'javascript',
  code: 'function Counter() {\n  const [count, setCount] = useState(0)\n  return <span>{count}</span>\n}',
})
eq('"javascript" holding JSX does not run', component.runtime, null)
eq('and is called JSX', component.note.includes('contains JSX'), true)
eq('a self-closing component in a call is JSX', looksLikeJsx('render(<ProfileForm />);'), true)
eq('a comparison is not JSX', looksLikeJsx('if (a < b && c > d) { return a }'), false)
eq('a generic-free less-than is not JSX', looksLikeJsx('for (let i = 0; i<n; i++) {}'), false)
eq('HTML in a comment is not JSX',
  looksLikeJsx('// <li class="item">A</li>\nconst el = document.querySelector(".item")'), false)
eq('HTML in a template string is not JSX',
  looksLikeJsx('el.innerHTML = `<b>${text}</b>`'), false)
eq('HTML in a quoted string is not JSX', looksLikeJsx('const tag = "<div>"'), false)

const css = planCode({ language: 'css', css: '.card { color: red; }' })
eq('CSS kept under a "css" key is recognised, and does not run', [css.runtime, css.note.includes('css, which cannot run')], [null, true])
eq('HTML under "markup" likewise', planCode({ language: 'html', markup: '<p>hi</p>' }).runtime, null)

const none = planCode({ situation: 'A hash table with 1,000 buckets...' })
eq('no code: an empty Python scratch editor', [none.runtime, none.code], ['python', ''])

const prog = planCode({ language: 'python', program: 'print(1)', how_it_runs: '...' })
eq('"program" is code too', prog.code, 'print(1)')

console.log(fail ? `\n${fail} FAILURES` : '\nall code-plan cases pass')
process.exit(fail ? 1 : 0)
