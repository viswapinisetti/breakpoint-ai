/** Step 1 - the NIAT course catalog, with Breakpoint sitting in it as one
 *  more course card.
 *
 *  Only the Breakpoint card is live. The neighbouring cards are reproduced so
 *  the page reads as the real catalog, and they are marked `aria-disabled`
 *  rather than made to look clickable: a card that opens nothing is worse than
 *  a card that says it belongs to the wider LMS.
 */

import { useState } from 'react'
import { Dashboard } from '../screens/Dashboard'
import { StatsScreen } from '../screens/StatsScreen'
import {
  IconBookmark,
  IconChevronRight,
  IconCourses,
  IconDiscussions,
  IconHome,
  IconJourney,
  IconNotebook,
  IconPlayground,
  IconSearch,
  IconSnippets,
  NiatLogo,
} from './brand'

/** Sections of the catalog frame that are actually implemented. The rest of
 *  the rail is reproduced for fidelity and marked unavailable rather than
 *  wired to a blank page. */
type Section = 'journey' | 'courses' | 'progress'

const NAV: {
  label: string
  Icon: (p: { className?: string }) => React.ReactElement
  section?: Section
  badge?: string
}[] = [
  { label: 'Home', Icon: IconHome, section: 'journey' },
  { label: 'My Journey', Icon: IconJourney, section: 'journey' },
  { label: 'Other Courses', Icon: IconCourses, section: 'courses' },
  { label: 'Bookmarks', Icon: IconBookmark },
  { label: 'My Discussions', Icon: IconDiscussions },
  { label: 'My Notebook', Icon: IconNotebook, badge: 'New' },
  { label: 'Playground', Icon: IconPlayground },
  { label: 'Code Snippets', Icon: IconSnippets },
]

interface CourseCard {
  title: string
  subtitle: string
  /** Thumbnail treatment. Breakpoint gets its own, drawn rather than stock. */
  thumb: 'breakpoint' | 'aptitude' | 'communication' | 'genai' | 'business'
  live?: boolean
}

const DEGREE_COURSES: CourseCard[] = [
  {
    title: 'NxtWave Breakpoint',
    subtitle:
      'AI Failure Lab. 116 investigations across 19 subjects — detect, challenge, test and correct AI mistakes.',
    thumb: 'breakpoint',
    live: true,
  },
  {
    title: 'Advanced Aptitude',
    subtitle: 'NIAT Advanced Aptitude',
    thumb: 'aptitude',
  },
  {
    title: 'Applied Communication',
    subtitle: 'KKH Course',
    thumb: 'communication',
  },
  {
    title: 'Generative AI',
    subtitle:
      'This course covers the fundamentals of Generative AI, including text generation, image creation, and multimodal …',
    thumb: 'genai',
  },
  {
    title: 'Business Leadership',
    subtitle:
      'This course covers the principles of leadership, applied to real organisational …',
    thumb: 'business',
  },
]

const BONUS_COURSES: CourseCard[] = [
  {
    title: 'Interview Preparation',
    subtitle: 'Mock interviews and structured feedback',
    thumb: 'communication',
  },
  {
    title: 'Competitive Programming',
    subtitle: 'Contest patterns and timed practice',
    thumb: 'aptitude',
  },
]

function Thumb({ kind }: { kind: CourseCard['thumb'] }) {
  if (kind === 'breakpoint') {
    return (
      <div className="relative h-[104px] overflow-hidden rounded-t-[10px] bg-[#0f1a38]">
        {/* A reasoning chain with one broken link - the product in one image. */}
        <svg viewBox="0 0 320 104" className="absolute inset-0 h-full w-full">
          <defs>
            <linearGradient id="bpg" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#1e3a8a" />
              <stop offset="100%" stopColor="#0f1a38" />
            </linearGradient>
          </defs>
          <rect width="320" height="104" fill="url(#bpg)" />
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <rect
                x={26 + i * 70}
                y={44}
                width={48}
                height={16}
                rx="3"
                fill={i === 2 ? '#f97316' : '#3b82f6'}
                opacity={i === 2 ? 1 : 0.55}
              />
              {i < 3 && (
                <path
                  d={`M${78 + i * 70} 52h${i === 1 ? 8 : 18}`}
                  stroke={i === 1 ? '#f97316' : '#3b82f6'}
                  strokeWidth="2"
                  strokeDasharray={i === 1 ? '3 4' : undefined}
                  opacity="0.8"
                />
              )}
            </g>
          ))}
          <text
            x="26"
            y="30"
            fill="#93c5fd"
            fontSize="10"
            fontWeight="700"
            letterSpacing="1.6"
            fontFamily="Roboto, sans-serif"
          >
            AI FAILURE LAB
          </text>
          <text
            x="26"
            y="82"
            fill="#e2e8f0"
            fontSize="11"
            fontWeight="700"
            fontFamily="Roboto, sans-serif"
          >
            AI says it&apos;s right. Prove it.
          </text>
        </svg>
      </div>
    )
  }

  if (kind === 'genai') {
    return (
      <div className="grid h-[104px] place-items-center rounded-t-[10px] bg-gradient-to-br from-[#0b1120] to-[#1e293b]">
        <div className="text-center">
          <div className="text-[8px] font-bold tracking-[0.18em] text-slate-400">
            INTRODUCTION TO
          </div>
          <div className="text-[19px] font-bold text-white">Generative AI</div>
        </div>
      </div>
    )
  }

  if (kind === 'aptitude') {
    return (
      <div className="relative h-[104px] overflow-hidden rounded-t-[10px] bg-[#cfd3ef]">
        <svg viewBox="0 0 320 104" className="absolute inset-0 h-full w-full">
          <text
            x="46"
            y="52"
            fill="#e0762e"
            fontSize="34"
            fontWeight="700"
            fontFamily="Roboto, sans-serif"
          >
            5
          </text>
          <text
            x="150"
            y="42"
            fill="#3b4a9c"
            fontSize="26"
            fontWeight="700"
            fontFamily="Roboto, sans-serif"
          >
            4
          </text>
          <text
            x="196"
            y="70"
            fill="#2f3d84"
            fontSize="40"
            fontWeight="700"
            fontFamily="Roboto, sans-serif"
          >
            9
          </text>
          <circle cx="112" cy="60" r="13" fill="#8b93d6" />
          <circle cx="140" cy="76" r="9" fill="#6b74bd" />
          <rect x="240" y="34" width="34" height="44" rx="3" fill="#9aa2dd" />
        </svg>
        <div className="absolute bottom-0 h-1 w-full bg-[#e0762e]" />
      </div>
    )
  }

  if (kind === 'business') {
    return (
      <div className="relative h-[104px] overflow-hidden rounded-t-[10px] bg-gradient-to-br from-[#1d4ed8] to-[#0ea5e9]">
        <span className="absolute top-4 left-4 text-[26px] leading-none font-bold text-white/95">
          Bu
          <br />
          L…
        </span>
      </div>
    )
  }

  return (
    <div className="h-[104px] rounded-t-[10px] bg-[#eef1fb]">
      <div className="h-full w-full rounded-t-[10px] bg-gradient-to-br from-[#eef1fb] to-[#dfe5f7]" />
      <div className="h-1 w-full bg-[#e0762e]" />
    </div>
  )
}

function Card({ course, onOpen }: { course: CourseCard; onOpen: () => void }) {
  const body = (
    <>
      <Thumb kind={course.thumb} />
      <div className="flex flex-1 flex-col px-4 pt-3.5 pb-4">
        <h3 className="truncate text-[15px] font-bold text-lms-ink">
          {course.title}
        </h3>
        <p className="mt-1.5 line-clamp-3 text-[13px] leading-[1.5] text-slate-500">
          {course.subtitle}
        </p>
        {course.live && (
          <span className="mt-auto pt-3 text-[13px] font-bold text-lms-link">
            Open course →
          </span>
        )}
      </div>
    </>
  )

  const frame =
    'flex w-[188px] shrink-0 flex-col overflow-hidden rounded-[10px] border border-lms-hairline bg-white text-left'

  if (!course.live) {
    return (
      <div
        className={`${frame} opacity-95`}
        aria-disabled="true"
        title="Part of the wider NIAT catalog, not this prototype"
      >
        {body}
      </div>
    )
  }

  return (
    <button
      onClick={onOpen}
      className={`${frame} cursor-pointer shadow-sm transition hover:-translate-y-0.5 hover:border-lms-link hover:shadow-md`}
    >
      {body}
    </button>
  )
}

function Shelf({
  heading,
  courses,
  onOpen,
}: {
  heading: string
  courses: CourseCard[]
  onOpen: () => void
}) {
  return (
    <section className="mt-6 rounded-[10px] bg-white/70 px-5 pt-5 pb-6">
      <h2 className="text-[13px] font-bold tracking-[0.06em] text-lms-link uppercase">
        {heading}
      </h2>
      <div className="relative mt-4">
        <div className="bp-scrollx flex gap-4 pb-1">
          {courses.map((c) => (
            <Card key={c.title} course={c} onOpen={onOpen} />
          ))}
        </div>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 -right-1 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full bg-white text-lms-ink shadow-md"
        >
          <IconChevronRight className="h-4 w-4" />
        </span>
      </div>
    </section>
  )
}

export function CoursesHome({
  onOpenCourse,
  initialSection = 'courses',
}: {
  /** Opens the course. With a challenge id, the course opens straight onto
   *  that investigation - which is what Today's Breakpoint links to. */
  onOpenCourse: (challengeId?: string) => void
  initialSection?: Section
}) {
  const [section, setSection] = useState<Section>(initialSection)

  return (
    <div className="flex min-h-screen bg-lms-canvas">
      {/* --- rail ---------------------------------------------------- */}
      <aside className="sticky top-0 flex h-screen w-[176px] shrink-0 flex-col bg-lms-rail py-4">
        <div className="px-3.5">
          <NiatLogo />
        </div>

        <div className="mt-5 px-3">
          <div className="flex items-center gap-2 rounded-md bg-white/10 px-2.5 py-2">
            <IconSearch className="h-3.5 w-3.5 shrink-0 text-lms-rail-text" />
            <span className="truncate text-[12px] text-lms-rail-text">
              Search for &lsquo;Arrays&rsquo;
            </span>
          </div>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5 px-2">
          {NAV.map(({ label, Icon, section: target, badge }) => {
            const active = target === section
            const wired = target !== undefined
            return (
              <button
                key={label}
                onClick={() => target && setSection(target)}
                aria-current={active ? 'page' : undefined}
                aria-disabled={wired ? undefined : true}
                title={wired ? undefined : 'Part of the wider NIAT platform'}
                className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px] transition ${
                  active
                    ? 'bg-lms-rail-active font-bold text-white'
                    : wired
                      ? 'text-lms-rail-text hover:bg-lms-rail-hover'
                      : 'text-lms-rail-text/55'
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{label}</span>
                {badge && (
                  <span className="ml-auto rounded-full bg-[#f59e0b] px-1.5 py-px text-[9px] font-bold text-[#3b2500]">
                    {badge}
                  </span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="mt-6 px-4 text-[10px] font-bold tracking-[0.14em] text-white/35 uppercase">
          Apps
        </div>
      </aside>

      {/* --- main ---------------------------------------------------- */}
      <main className="min-w-0 flex-1 px-7 py-6">
        {section === 'courses' && (
          <>
            <h1 className="text-[22px] font-bold text-lms-ink">
              Other Courses
            </h1>
            <Shelf
              heading="Degree Assistive Courses"
              courses={DEGREE_COURSES}
              onOpen={() => onOpenCourse()}
            />
            <Shelf
              heading="Bonus Courses"
              courses={BONUS_COURSES}
              onOpen={() => onOpenCourse()}
            />
          </>
        )}

        {section === 'journey' && (
          <Dashboard
            onInvestigate={(challengeId) => onOpenCourse(challengeId)}
            onExplore={() => setSection('courses')}
            onStats={() => setSection('progress')}
          />
        )}

        {section === 'progress' && <StatsScreen />}
      </main>
    </div>
  )
}
