/** Sign in or create an account (accounts mode).
 *
 * Rendered instead of the app when the server says sign-in is required. What
 * it offers comes from `/api/auth/providers` rather than from constants here,
 * so a Google button appears only on a server where Google actually works -
 * and when it does not, the reason is shown rather than the button hidden
 * without explanation.
 */

import { useEffect, useState } from 'react'
import { auth, ApiError, type AuthProfile, type AuthProviders } from '../api'
import { Banner, Spinner } from '../components/ui'
import { NxtWaveWordmark } from '../lms/brand'

type Mode = 'signin' | 'signup'

export function SignIn({
  providers,
  onSignedIn,
}: {
  providers: AuthProviders
  onSignedIn: (profile: AuthProfile) => void
}) {
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  // Google sends the browser back here with ?auth_error=... when its leg
  // fails; the redirect is the only channel it has to explain itself. Read
  // once as the initial value, then tidied out of the address bar so a
  // reload does not resurrect a stale complaint.
  const [error, setError] = useState(
    () => new URLSearchParams(window.location.search).get('auth_error') ?? '',
  )
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('auth_error')) return
    url.searchParams.delete('auth_error')
    window.history.replaceState({}, '', url.toString())
  }, [])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const profile =
        mode === 'signup'
          ? await auth.signUp(email, password, name)
          : await auth.signIn(email, password)
      onSignedIn(profile)
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : 'Something went wrong. Try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  const signUp = mode === 'signup'

  return (
    <div className="grid min-h-screen place-items-center bg-lms-canvas px-4 py-10">
      <div className="w-full max-w-[420px]">
        <div className="flex justify-center">
          <NxtWaveWordmark />
        </div>
        <h1 className="mt-6 text-center text-[22px] font-bold text-lms-ink">
          {signUp ? 'Create your account' : 'Sign in to Breakpoint'}
        </h1>
        <p className="mt-1 text-center text-[14px] text-slate-500">
          AI says it&rsquo;s right. Prove it.
        </p>

        <div className="bp-card mt-6 p-5">
          {error && (
            <div className="mb-4">
              <Banner kind="error" onDismiss={() => setError('')}>
                {error}
              </Banner>
            </div>
          )}

          {providers.google ? (
            <>
              <a
                href={auth.googleUrl}
                className="flex w-full items-center justify-center gap-3 rounded-control border border-slate-200 px-4 py-2.5 text-sm font-bold text-ink transition hover:border-brand"
              >
                <GoogleMark />
                Continue with Google
              </a>
              <div className="my-4 flex items-center gap-3 text-[11px] font-bold tracking-wider text-slate-400 uppercase">
                <span className="h-px flex-1 bg-slate-200" />
                or
                <span className="h-px flex-1 bg-slate-200" />
              </div>
            </>
          ) : (
            providers.google_unavailable && (
              <p className="mb-4 rounded-control bg-page px-3 py-2 text-xs text-slate-500">
                {providers.google_unavailable}
              </p>
            )
          )}

          <form onSubmit={submit} className="space-y-3">
            {signUp && (
              <Field
                label="Your name"
                value={name}
                onChange={setName}
                type="text"
                autoComplete="name"
                placeholder="Asha Rao"
              />
            )}
            <Field
              label="Email"
              value={email}
              onChange={setEmail}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
            />
            <Field
              label="Password"
              value={password}
              onChange={setPassword}
              type="password"
              autoComplete={signUp ? 'new-password' : 'current-password'}
              placeholder={signUp ? 'At least 10 characters' : ''}
              hint={
                signUp
                  ? 'Length beats punctuation. Three unrelated words are easy to remember and hard to guess.'
                  : ''
              }
            />
            <button
              type="submit"
              disabled={busy || !email || !password || (signUp && !name)}
              className="bp-btn bp-btn-primary w-full"
            >
              {signUp ? 'Create account' : 'Sign in'}
            </button>
            {busy && <Spinner label={signUp ? 'Creating your account' : 'Signing in'} />}
          </form>
        </div>

        <p className="mt-4 text-center text-sm text-slate-600">
          {signUp ? 'Already have an account?' : 'New here?'}{' '}
          <button
            onClick={() => {
              setMode(signUp ? 'signin' : 'signup')
              setError('')
            }}
            className="font-bold text-lms-link hover:underline"
          >
            {signUp ? 'Sign in' : 'Create one'}
          </button>
        </p>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  type,
  autoComplete,
  placeholder,
  hint,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type: string
  autoComplete: string
  placeholder?: string
  hint?: string
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-bold tracking-wider text-slate-500 uppercase">
        {label}
      </span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        type={type}
        autoComplete={autoComplete}
        placeholder={placeholder}
        required
        className="mt-1 w-full rounded-control border border-slate-200 px-3 py-2.5 text-sm focus:border-brand focus:outline-none"
      />
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  )
}

/** Google's mark, drawn rather than loaded: the sign-in page must render
 *  before any third-party request, and offline. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" aria-hidden="true" className="h-[18px] w-[18px]">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"
      />
    </svg>
  )
}
