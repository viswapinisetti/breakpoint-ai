/** What the code tools can do with an investigation's artifact.
 *
 * Python runs on real CPython (Pyodide) and plain JavaScript in a worker,
 * both in the student's browser. Anything else - JSX, TypeScript, CSS, bash,
 * C - is said plainly rather than half-run: a tool that executes some other
 * language's code as if it were JavaScript would produce confident nonsense,
 * which is the opposite of what this product teaches.
 *
 * Pure and dependency-free, so plan.test.mjs can run it under Node.
 */

export type Runtime = 'python' | 'javascript'

export interface TestCase {
  call: string
  expected: string
}

export interface CodePlan {
  /** null when this artifact's language cannot run here. */
  runtime: Runtime | null
  /** The artifact's language as written, for messages. */
  language: string
  code: string
  /** First function the code defines, used for starter calls. */
  entry: string | null
  /** Starting rows for the Test Runner: the artifact's own tests, if any. */
  tests: TestCase[]
  /** Why nothing runs, when runtime is null; a note otherwise. */
  note: string
}

const PYTHON = new Set(['python', 'python3', 'py'])
const JAVASCRIPT = new Set(['javascript', 'js', 'node', 'nodejs'])

function firstFunction(code: string, runtime: Runtime): string | null {
  const m =
    runtime === 'python'
      ? /^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(/m.exec(code)
      : /\bfunction\s+([A-Za-z_$][\w$]*)\s*\(|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)/.exec(code)
  if (!m) return null
  return m[1] ?? m[2] ?? null
}

/** JSX markup: an element tag where an expression starts, e.g.
 *  `return <span>{count}</span>` or `render(<ProfileForm />)`. A comparison
 *  such as `a < b` does not match, because `<` is followed by a space, and
 *  markup inside comments or strings (`// <li>A</li>`, an innerHTML template)
 *  is plain JavaScript, so those are removed before looking. */
export function looksLikeJsx(code: string): boolean {
  const bare = code
    .replace(/`(?:\\[\s\S]|[^\\`])*`/g, '""')
    .replace(/'(?:\\.|[^\\'\n])*'/g, '""')
    .replace(/"(?:\\.|[^\\"\n])*"/g, '""')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/[^\n]*/g, '')
  return /(?:^|[\s(=,:?&|]|return)<(?:[A-Za-z][\w.]*)(?:\s[^<>]*?)?\/?>/m.test(bare)
}

/** "assert median([1, 2, 3]) == 2" -> { call, expected }. */
export function parseAssert(line: string): TestCase | null {
  const m = /^\s*assert\s+(.+?)\s*==\s*(.+?)\s*$/.exec(line)
  return m ? { call: m[1], expected: m[2] } : null
}

export function planCode(artifact: Record<string, unknown>): CodePlan {
  const language =
    typeof artifact.language === 'string' ? artifact.language.trim().toLowerCase() : ''
  // Code lives under `code` or `program`; CSS and HTML artifacts put it under
  // `css` or `markup`, so with a language named, any text field will do.
  const fallback = language
    ? Object.entries(artifact).find(([k, v]) => k !== 'language' && typeof v === 'string')?.[1]
    : undefined
  const source =
    typeof artifact.code === 'string'
      ? artifact.code
      : typeof artifact.program === 'string'
        ? artifact.program
        : typeof fallback === 'string'
          ? fallback
          : ''

  if (!source.trim()) {
    return {
      runtime: 'python',
      language: 'python',
      code: '',
      entry: null,
      tests: [],
      note: 'This investigation has no code of its own, so the editor starts empty. Use it to check a claim in Python.',
    }
  }

  const runtime: Runtime | null = PYTHON.has(language)
    ? 'python'
    : JAVASCRIPT.has(language)
      ? 'javascript'
      : null

  // Content labelled "javascript" sometimes holds React components with JSX
  // markup, which is not JavaScript until a build step compiles it.
  if (runtime === 'javascript' && looksLikeJsx(source)) {
    return {
      runtime: null,
      language: 'jsx',
      code: source,
      entry: null,
      tests: [],
      note: "This investigation's code contains JSX or HTML markup, which needs a build step and a web page to render, so it cannot run in the browser sandbox. The code tools run Python and plain JavaScript.",
    }
  }

  if (!runtime) {
    const shown = language || 'this language'
    return {
      runtime: null,
      language,
      code: source,
      entry: null,
      tests: [],
      note: `This investigation's code is ${shown}, which cannot run in the browser sandbox. The code tools run Python and plain JavaScript.`,
    }
  }

  const tests = Array.isArray(artifact.tests)
    ? artifact.tests
        .filter((t): t is string => typeof t === 'string')
        .map(parseAssert)
        .filter((t): t is TestCase => t !== null)
    : []

  return {
    runtime,
    language,
    code: source,
    entry: firstFunction(source, runtime),
    tests,
    note:
      runtime === 'javascript'
        ? 'Plain JavaScript only: there is no web page (document, window), no React and no network in the sandbox.'
        : '',
  }
}
