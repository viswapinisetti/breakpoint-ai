/** Messages between the code tools and their workers. Result shapes match
 *  what harness.py returns, and the JavaScript worker produces the same. */

import type { TestCase } from './plan'

export interface CodeError {
  type: string
  message: string
  /** Traceback limited to the student's code. */
  traceback: string
  /** A plain-language pointer, e.g. that the DOM is not available. */
  hint?: string
}

export interface RunResult {
  ok: boolean
  stdout: string
  stderr: string
  error: CodeError | null
  /** Functions and classes the program defined. */
  defined: string[]
  ms: number
}

export interface ReplResult {
  ok: boolean
  stdout: string
  stderr: string
  /** repr of the entry's value; null when there is none to show. */
  value: string | null
  error: CodeError | null
  /** The program itself failed to load, so nothing could be evaluated. */
  loadFailed?: boolean
  ms: number
}

export interface TestResult {
  call: string
  expected: string
  passed: boolean
  actual: string | null
  expectedValue?: string
  error: CodeError | null
  stdout: string
}

export interface TestsResult {
  loadError: CodeError | null
  results: TestResult[]
}

export interface TraceStep {
  event: 'call' | 'line' | 'return' | 'exception'
  func: string
  line: number
  source: string
  locals: Record<string, string>
  depth: number
  value?: string
}

export interface TraceResult {
  loadError: CodeError | null
  steps: TraceStep[]
  truncated: boolean
  value: string | null
  error: CodeError | null
  stdout: string
}

export type CodeRequest =
  | { id: number; kind: 'load' }
  | { id: number; kind: 'run'; code: string }
  | { id: number; kind: 'repl'; code: string; source: string; history: string[] }
  | { id: number; kind: 'reset' }
  | { id: number; kind: 'tests'; code: string; cases: TestCase[] }
  | { id: number; kind: 'trace'; code: string; source: string }

export type CodeReply =
  | { id: number; ok: true; data: unknown }
  | { id: number; ok: false; error: string }
