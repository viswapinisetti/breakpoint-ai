import { createReadStream, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/** Pyodide (the code tools' in-browser Python) loads its runtime from one
 *  directory by name, so these files are served at /pyodide/ in dev and
 *  copied to dist/pyodide/ in a build, unhashed. */
const PYODIDE_DIR = fileURLToPath(new URL('./node_modules/pyodide/', import.meta.url))
const PYODIDE_FILES: Record<string, string> = {
  'pyodide.asm.mjs': 'text/javascript',
  'pyodide.asm.wasm': 'application/wasm',
  'python_stdlib.zip': 'application/zip',
  'pyodide-lock.json': 'application/json',
}

function pyodideAssets(): Plugin {
  return {
    name: 'breakpoint-pyodide-assets',
    configureServer(server) {
      server.middlewares.use('/pyodide', (req, res, next) => {
        const name = (req.url ?? '').split('?')[0].replace(/^\/+/, '')
        const type = PYODIDE_FILES[name]
        if (!type) return next()
        res.setHeader('Content-Type', type)
        createReadStream(PYODIDE_DIR + name).pipe(res)
      })
    },
    generateBundle() {
      for (const name of Object.keys(PYODIDE_FILES)) {
        this.emitFile({
          type: 'asset',
          fileName: `pyodide/${name}`,
          source: readFileSync(PYODIDE_DIR + name),
        })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), pyodideAssets()],
  // PGlite (the Databases tools' PostgreSQL) and Pyodide load their .wasm
  // files relative to themselves; pre-bundling would break those paths. Both
  // run in module workers.
  optimizeDeps: { exclude: ['@electric-sql/pglite', 'pyodide'] },
  worker: { format: 'es' },
  server: {
    port: 5173,
    proxy: {
      // The backend runs on the host. Overridable so the dev server can run
      // somewhere else than the API - in a Linux container, for instance,
      // where the host is reachable as host.docker.internal.
      '/api': {
        target: process.env.BREAKPOINT_API_PROXY ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
