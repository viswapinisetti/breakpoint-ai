/** The in-course frame: platform header, CONTENTS rail, and our content on
 *  the right.
 *
 *  It owns the navigation state for the course (which subject is open, which
 *  item is selected) and the per-subject challenge cache, because both the
 *  rail and the right pane read from it. The investigation screens themselves
 *  are unchanged - they are rendered into the right pane exactly as before, so
 *  the whole engine is reachable through the platform chrome without any
 *  screen knowing it moved.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  STUDENT_NAME,
  type Autopsy as AutopsyData,
  type ChallengeCard,
  type Subject,
} from '../api'
import { Autopsy } from '../screens/Autopsy'
import { Challenge } from '../screens/Challenge'
import { StatsScreen } from '../screens/StatsScreen'
import { Studio } from '../screens/Studio'
import { Banner, Spinner } from '../components/ui'
import { ContentsRail } from './ContentsRail'
import { SubjectIndex } from './SubjectIndex'
import { IconChevronRight, IconSearch, IconTimer, NxtWaveWordmark } from './brand'

type Pane =
  | { name: 'subject' }
  | { name: 'challenge'; challengeId: string }
  | { name: 'autopsy'; data: AutopsyData; attemptId: number }
  | { name: 'progress' }
  | { name: 'studio' }

const TOP_NAV = [
  { key: 'home', label: 'Home' },
  { key: 'progress', label: 'Progress' },
  { key: 'studio', label: 'Studio' },
] as const

const AI_NOTICE_KEY = 'breakpoint.aiNoticeDismissed'

export function CourseShell({
  onExitCourse,
  initialChallengeId,
  account,
}: {
  onExitCourse: () => void
  /** Enter the course already on this investigation, with the rail opened to
   *  the subject that owns it. */
  initialChallengeId?: string
  /** The signed-in student, when this server has accounts. `onSignOut` is
   *  absent in header and SSO mode, where there is no session to end. */
  account?: { name: string; email: string; onSignOut?: () => void }
}) {
  const [subjects, setSubjects] = useState<Subject[] | null>(null)
  const [error, setError] = useState('')
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [pane, setPane] = useState<Pane>({ name: 'subject' })
  const [railHidden, setRailHidden] = useState(false)
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null)
  // Remembered per browser: the notice pushes every investigation down, so
  // once read it should not come back on each reload.
  const [noticeDismissed, setNoticeDismissed] = useState(() => {
    try {
      return localStorage.getItem(AI_NOTICE_KEY) === '1'
    } catch {
      return false
    }
  })
  const dismissNotice = () => {
    setNoticeDismissed(true)
    try {
      localStorage.setItem(AI_NOTICE_KEY, '1')
    } catch {
      /* storage unavailable: dismissed for this visit only */
    }
  }
  // The breadcrumb bar's action area, handed to the open investigation.
  const [actionSlot, setActionSlot] = useState<HTMLDivElement | null>(null)
  const displayName = account?.name || STUDENT_NAME

  // Challenges per subject, fetched once on first open. Held in a ref beside
  // the state so a refresh after an attempt can invalidate one subject's list
  // without re-fetching the other eighteen.
  const [cache, setCache] = useState<Record<string, ChallengeCard[]>>({})
  const inFlight = useRef<Set<string>>(new Set())

  useEffect(() => {
    api
      .subjects()
      .then((list) => {
        setSubjects(list)
        // Without a deep link, open the first subject that has content, so the
        // course never opens onto an empty rail.
        if (!initialChallengeId) {
          const first = list.find((s) => s.challenge_count > 0)
          if (first) setOpenKey(first.key)
        }
      })
      .catch((e) => setError(e.message))
    api
      .health()
      .then((h) => setAiConfigured(h.ai_configured))
      .catch(() => setAiConfigured(null))
  }, [initialChallengeId])

  // A deep link names a challenge, not a subject, so the owning subject has to
  // be resolved before the rail can show the item in context. One listing call,
  // and only when a deep link is actually present.
  useEffect(() => {
    if (!initialChallengeId) return
    let cancelled = false
    api
      .challenges({})
      .then((all) => {
        if (cancelled) return
        const card = all.find((c) => c.id === initialChallengeId)
        if (!card) {
          setError(`Challenge ${initialChallengeId} is no longer published.`)
          return
        }
        setCache((c) => ({
          ...c,
          [card.subject]: all.filter((x) => x.subject === card.subject),
        }))
        setOpenKey(card.subject)
        setPane({ name: 'challenge', challengeId: card.id })
      })
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [initialChallengeId])

  const loadSubject = useCallback(
    (key: string, force = false) => {
      if (!force && (cache[key] || inFlight.current.has(key))) return
      inFlight.current.add(key)
      api
        .challenges({ subject: key })
        .then((cards) => setCache((c) => ({ ...c, [key]: cards })))
        .catch((e) => setError(e.message))
        .finally(() => inFlight.current.delete(key))
    },
    [cache],
  )

  useEffect(() => {
    if (openKey) loadSubject(openKey)
  }, [openKey, loadSubject])

  // Navigation starts at the top. Without this, opening an item from a
  // scrolled contents rail or subject index kept the old window offset, so the
  // new content appeared already scrolled.
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [pane])

  const openSubject = subjects?.find((s) => s.key === openKey) ?? null
  const openChallenges = openKey ? (cache[openKey] ?? null) : null

  const selectedId = pane.name === 'challenge' ? pane.challengeId : null
  const selectedCard = useMemo(
    () => openChallenges?.find((c) => c.id === selectedId) ?? null,
    [openChallenges, selectedId],
  )

  function toggleSubject(key: string) {
    if (openKey === key) {
      setOpenKey(null)
    } else {
      setOpenKey(key)
      loadSubject(key)
    }
    setPane({ name: 'subject' })
  }

  function openChallenge(id: string) {
    setPane({ name: 'challenge', challengeId: id })
  }

  function startSubject() {
    const next =
      openChallenges?.find((c) => !c.completed) ?? openChallenges?.[0] ?? null
    if (next) openChallenge(next.id)
  }

  /** Back to the subject page, with its item list refreshed so the rail shows
   *  the completion that just happened. */
  function finishAndRefresh() {
    if (openKey) loadSubject(openKey, true)
    setPane({ name: 'subject' })
  }

  const breadcrumb = (() => {
    if (pane.name === 'progress') return ['Your progress']
    if (pane.name === 'studio') return ['Challenge Studio']
    if (!openSubject) return ['Contents']
    if (pane.name === 'subject')
      return [openSubject.name, `${openSubject.name} - Study material`]
    if (selectedCard)
      return [
        openSubject.name,
        selectedCard.topic,
        selectedCard.subtopic || 'Investigation',
      ]
    return [openSubject.name, 'Investigation']
  })()

  return (
    <div className="min-h-screen bg-lms-canvas">
      {/* ---------------------------------------------------- top header */}
      <header className="sticky top-0 z-30 flex h-[58px] items-center gap-4 border-b border-lms-hairline bg-lms-header px-4">
        <button
          onClick={onExitCourse}
          aria-label="Back to Other Courses"
          className="shrink-0"
        >
          <NxtWaveWordmark />
        </button>

        <div className="mx-auto hidden w-full max-w-[420px] items-center gap-2 rounded-md border border-lms-hairline bg-[#f7f8fb] px-3 py-2 sm:flex">
          <IconSearch className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="flex-1 truncate text-[13px] text-slate-400">
            Search for &lsquo;Arrays&rsquo;
          </span>
          <kbd className="rounded border border-lms-hairline bg-white px-1.5 py-0.5 text-[10px] font-bold text-slate-400">
            CTRL+K
          </kbd>
        </div>

        <span className="hidden text-lms-link sm:block" aria-hidden="true">
          <IconTimer className="h-5 w-5" />
        </span>

        <nav className="flex shrink-0 items-center gap-1">
          {TOP_NAV.map((n) => {
            const active =
              (n.key === 'home' && (pane.name === 'subject' || pane.name === 'challenge' || pane.name === 'autopsy')) ||
              n.key === pane.name
            return (
              <button
                key={n.key}
                onClick={() =>
                  n.key === 'home'
                    ? setPane({ name: 'subject' })
                    : setPane({ name: n.key } as Pane)
                }
                className={`rounded px-2.5 py-1.5 text-[13.5px] transition ${
                  active
                    ? 'font-bold text-lms-ink'
                    : 'text-slate-500 hover:text-lms-ink'
                }`}
              >
                {n.label}
              </button>
            )
          })}
        </nav>

        <div className="flex shrink-0 items-center gap-2 pl-1">
          <span className="hidden text-right text-[13.5px] text-lms-ink sm:block">
            {displayName}
            {account?.email && (
              <span className="block text-[11px] text-slate-500">{account.email}</span>
            )}
          </span>
          <span
            aria-hidden="true"
            className="grid h-8 w-8 place-items-center rounded-full bg-lms-contents text-[12px] font-bold text-white"
          >
            {initials(displayName)}
          </span>
          {account?.onSignOut && (
            <button
              onClick={account.onSignOut}
              className="rounded px-2 py-1 text-[13px] text-slate-500 hover:text-lms-ink"
            >
              Sign out
            </button>
          )}
        </div>
      </header>

      <div className="flex">
        {!railHidden && subjects && (
          <ContentsRail
            subjects={subjects}
            openKey={openKey}
            challenges={openChallenges}
            selectedId={selectedId}
            onToggleSubject={toggleSubject}
            onSelectChallenge={openChallenge}
            onCollapse={() => setRailHidden(true)}
            onBackToCatalog={onExitCourse}
          />
        )}

        {/* ------------------------------------------------- right pane */}
        <main className="min-w-0 flex-1">
          {/* breadcrumb strip. A fixed 56px and sticky under the 58px header:
              an investigation puts its actions here, and pins its question
              column just below it (Challenge.tsx relies on both heights). */}
          <div className="sticky top-[58px] z-20 flex h-[56px] items-center gap-2 border-b border-lms-hairline bg-white px-6">
            {railHidden && (
              <button
                onClick={() => setRailHidden(false)}
                className="mr-1 rounded border border-lms-hairline px-2 py-1 text-[11px] font-bold text-slate-500 hover:text-lms-ink"
              >
                Contents
              </button>
            )}
            <nav className="flex min-w-0 flex-wrap items-center gap-1.5 text-[13.5px]">
              {breadcrumb.map((crumb, i) => (
                <span key={i} className="flex items-center gap-1.5">
                  {i > 0 && (
                    <IconChevronRight
                      className="h-3 w-3 shrink-0 text-slate-300"
                      aria-hidden="true"
                    />
                  )}
                  <span
                    className={
                      i === breadcrumb.length - 1
                        ? 'text-slate-500'
                        : 'text-lms-link'
                    }
                  >
                    {crumb}
                  </span>
                </span>
              ))}
            </nav>
            <div ref={setActionSlot} className="ml-auto shrink-0" />
          </div>

          {aiConfigured === false && !noticeDismissed && (
            <div className="px-6 pt-4">
              <Banner kind="warn" onDismiss={dismissNotice}>
                No AI provider is configured. Challenges, judging, hints, replay
                and scoring all work; generation, evidence evaluation, debate
                and the live debrief need{' '}
                <code>BREAKPOINT_OPENROUTER_API_KEY</code> in{' '}
                <code>backend/.env</code>.
              </Banner>
            </div>
          )}

          <div
            className={`px-4 sm:px-6 ${pane.name === 'challenge' ? 'py-4' : 'py-6'}`}
          >
            {error && (
              <div className="mx-auto max-w-[760px]">
                <Banner kind="error">{error}</Banner>
              </div>
            )}

            {!subjects && !error && (
              <div className="py-16">
                <Spinner label="Loading contents" />
              </div>
            )}

            {pane.name === 'progress' && <StatsScreen />}
            {pane.name === 'studio' && <Studio />}

            {pane.name === 'subject' && openSubject && (
              <SubjectIndex
                subject={openSubject}
                challenges={openChallenges}
                onOpen={openChallenge}
              />
            )}

            {pane.name === 'subject' && subjects && !openSubject && (
              <div className="mx-auto max-w-[860px] px-2 py-6">
                <h1 className="text-[22px] font-bold text-lms-ink">
                  NxtWave Breakpoint
                </h1>
                <p className="mt-2 text-[14px] text-slate-500 tabular">
                  {subjects.reduce((n, s) => n + s.challenge_count, 0)}{' '}
                  investigations across {subjects.length} subjects. Choose one
                  from the contents list.
                </p>
              </div>
            )}

            {pane.name === 'challenge' && (
              <Challenge
                key={pane.challengeId}
                challengeId={pane.challengeId}
                onComplete={(data, attemptId) => {
                  if (openKey) loadSubject(openKey, true)
                  setPane({ name: 'autopsy', data, attemptId })
                }}
                onExit={finishAndRefresh}
                actionSlot={actionSlot}
              />
            )}

            {pane.name === 'autopsy' && (
              <Autopsy
                data={pane.data}
                attemptId={pane.attemptId}
                onNext={startSubject}
                onExit={finishAndRefresh}
              />
            )}
          </div>

          <footer className="border-t border-lms-hairline bg-white px-6 py-5 text-[12px] leading-relaxed text-slate-500">
            Breakpoint intentionally presents some incorrect AI outputs as
            controlled educational scenarios. Confidence values are simulated.
            Do not treat Breakpoint output as authoritative professional advice.
          </footer>
        </main>
      </div>
    </div>
  )
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || 'NL'
}
