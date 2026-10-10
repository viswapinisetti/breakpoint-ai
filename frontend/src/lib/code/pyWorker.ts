/** Python for the code tools: Pyodide (CPython compiled to WebAssembly) in a
 *  Web Worker. The tool logic itself is harness.py, loaded as text.
 *
 *  A worker, so an infinite loop cannot freeze the page: the client
 *  terminates it on a timeout and the next request starts a fresh one. */

import { loadPyodide, type PyodideAPI } from 'pyodide'
import harness from './harness.py?raw'
import type { CodeReply, CodeRequest } from './protocol'

let ready: Promise<PyodideAPI> | null = null

function start(): Promise<PyodideAPI> {
  ready ??= (async () => {
    // Served from /pyodide/ by the pyodide-assets plugin in vite.config.ts.
    const indexURL = new URL(`${import.meta.env.BASE_URL}pyodide/`, self.location.origin).href
    const py = await loadPyodide({ indexURL })
    py.runPython(harness)
    return py
  })()
  return ready
}

function call(py: PyodideAPI, name: string, ...args: string[]): unknown {
  const fn = py.globals.get(name)
  try {
    return JSON.parse(fn(...args) as string)
  } finally {
    fn.destroy?.()
  }
}

function reply(message: CodeReply) {
  self.postMessage(message)
}

self.addEventListener('message', async (event: MessageEvent<CodeRequest>) => {
  const req = event.data
  try {
    const py = await start()
    let data: unknown
    switch (req.kind) {
      case 'load':
        data = { version: py.runPython('import sys; sys.version.split()[0]') }
        break
      case 'run':
        data = call(py, 'bp_run', req.code)
        break
      case 'repl':
        data = call(py, 'bp_repl', req.code, req.source)
        break
      case 'reset':
        data = call(py, 'bp_reset')
        break
      case 'tests':
        data = call(py, 'bp_tests', req.code, JSON.stringify(req.cases))
        break
      case 'trace':
        data = call(py, 'bp_trace', req.code, req.source)
        break
    }
    reply({ id: req.id, ok: true, data })
  } catch (e) {
    reply({ id: req.id, ok: false, error: (e as Error)?.message ?? String(e) })
  }
})
