/** Breakpoint inside the NxtWave LMS shell.
 *
 * Two levels, matching the platform:
 *
 *   catalog  the NIAT rail - My Journey, Other Courses, progress - where
 *            Breakpoint is one course card among the others
 *   course   the in-course frame: CONTENTS rail of all 19 subjects, each
 *            subject's topics and investigations beneath it, our content on
 *            the right
 *
 * Navigation state lives here rather than in a router because there are only
 * two levels and one of them is a course the learner enters and leaves. The
 * investigation screens are untouched - `CourseShell` renders them into the
 * right pane, so no screen knows it moved.
 *
 * Identity is asked for once, here: the server says whether sign-in is
 * required (accounts mode) or not (header, SSO), and the app renders the
 * sign-in screen only when it is. Nothing below this component knows which
 * mode is in use.
 */

import { useCallback, useEffect, useState } from 'react'
import { auth, type AuthProfile, type AuthProviders } from './api'
import { Banner, Spinner } from './components/ui'
import { CoursesHome } from './lms/CoursesHome'
import { CourseShell } from './lms/CourseShell'
import { SignIn } from './screens/SignIn'

type Route =
  | { name: 'catalog' }
  | { name: 'course'; challengeId?: string }

export default function App() {
  const [route, setRoute] = useState<Route>({ name: 'catalog' })
  const [providers, setProviders] = useState<AuthProviders | null>(null)
  const [profile, setProfile] = useState<AuthProfile | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([auth.providers(), auth.me()])
      .then(([p, me]) => {
        setProviders(p)
        setProfile(me)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  const signOut = useCallback(async () => {
    await auth.signOut().catch(() => {})
    setProfile({ signed_in: false, name: '', email: '', provider: '', external_id: '' })
    setRoute({ name: 'catalog' })
  }, [])

  if (error) {
    return (
      <div className="mx-auto max-w-xl px-6 py-16">
        <Banner kind="error">{error}</Banner>
      </div>
    )
  }
  if (!providers || !profile) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label="Loading Breakpoint" />
      </div>
    )
  }

  if (providers.sign_in_required && !profile.signed_in) {
    return <SignIn providers={providers} onSignedIn={setProfile} />
  }

  const account = {
    name: profile.name,
    email: profile.email,
    // Header and SSO modes have no session to end, so no control is offered.
    onSignOut: providers.sign_in_required ? signOut : undefined,
  }

  if (route.name === 'course') {
    return (
      <CourseShell
        initialChallengeId={route.challengeId}
        onExitCourse={() => setRoute({ name: 'catalog' })}
        account={account}
      />
    )
  }

  return (
    <CoursesHome
      onOpenCourse={(challengeId) => setRoute({ name: 'course', challengeId })}
    />
  )
}
