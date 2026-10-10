/** Evaluate an arithmetic expression without `eval`.
 *
 * A shunting-yard parser over a fixed token set. Using `eval` here would let
 * page script run from a text field for no benefit — the grammar needed is
 * four operators, exponentiation, parentheses, unary minus and percent.
 *
 * Mirrors backend/app/engine/arithmetic.py, which grades the evidence this
 * calculator helps students write, so the two must agree on every expression.
 */

// Internal marker for unary minus. Its precedence sits between the
// multiplicative operators and exponentiation, matching the backend (and
// Python): -2^2 is -(2^2), while 2^-2 is 2^(-2). Encoding unary minus as
// "0 - x" instead let a preceding operator grab the 0, so 3*-2 gave -2.
const UNARY_MINUS = '~'
const PRECEDENCE: Record<string, number> = {
  '+': 1,
  '-': 1,
  '*': 2,
  '/': 2,
  '%': 2,
  [UNARY_MINUS]: 3,
  '^': 4,
}
const RIGHT_ASSOCIATIVE = new Set(['^', UNARY_MINUS])

export function evaluate(expression: string): number {
  // Commas are thousands separators ("1,000"), as the backend reads them.
  const compact = expression.replace(/[\s,]+/g, '')
  const tokens = compact.match(/(\d+\.?\d*|[-+*/^()%])/g)
  if (!tokens) throw new Error('nothing to evaluate')
  if (tokens.join('') !== compact) {
    throw new Error('unsupported characters')
  }

  const output: (number | string)[] = []
  const operators: string[] = []
  let previous: string | null = null

  for (const token of tokens) {
    if (/^\d/.test(token)) {
      output.push(Number(token))
    } else if (token === '(') {
      operators.push(token)
    } else if (token === ')') {
      while (operators.length && operators[operators.length - 1] !== '(') {
        output.push(operators.pop() as string)
      }
      if (!operators.length) throw new Error('unbalanced parentheses')
      operators.pop()
    } else if (
      token === '-' &&
      (previous === null || previous === '(' || previous in PRECEDENCE)
    ) {
      // Prefix minus. A prefix operator pops nothing: whatever is on the stack
      // binds looser than the operand it is about to consume.
      operators.push(UNARY_MINUS)
    } else {
      if (previous !== null && previous in PRECEDENCE) {
        throw new Error(`two operators in a row near "${token}"`)
      }
      while (operators.length && operators[operators.length - 1] !== '(') {
        const top = operators[operators.length - 1]
        const binds =
          PRECEDENCE[top] > PRECEDENCE[token] ||
          (PRECEDENCE[top] === PRECEDENCE[token] && !RIGHT_ASSOCIATIVE.has(token))
        if (!binds) break
        output.push(operators.pop() as string)
      }
      operators.push(token)
    }
    previous = token
  }
  while (operators.length) {
    const op = operators.pop() as string
    if (op === '(') throw new Error('unbalanced parentheses')
    output.push(op)
  }

  const stack: number[] = []
  for (const item of output) {
    if (typeof item === 'number') {
      stack.push(item)
      continue
    }
    if (item === UNARY_MINUS) {
      const a = stack.pop()
      if (a === undefined) throw new Error('malformed expression')
      stack.push(-a)
      continue
    }
    const b = stack.pop()
    const a = stack.pop()
    if (a === undefined || b === undefined) throw new Error('malformed expression')
    switch (item) {
      case '+':
        stack.push(a + b)
        break
      case '-':
        stack.push(a - b)
        break
      case '*':
        stack.push(a * b)
        break
      case '/':
        if (b === 0) throw new Error('division by zero')
        stack.push(a / b)
        break
      case '%':
        stack.push((a / 100) * b)
        break
      case '^':
        stack.push(a ** b)
        break
      default:
        throw new Error(`unknown operator ${item}`)
    }
  }
  if (stack.length !== 1) throw new Error('malformed expression')
  return stack[0]
}
