/** NxtWave / NIAT brand marks and LMS icon set.
 *
 * These are typographic reconstructions drawn from platform screenshots, not
 * the official brand files. They are deliberately built as inline SVG with a
 * single `title` each, so dropping in the real assets is a one-file change:
 * replace the SVG body, keep the component name and box size.
 */

export function NiatLogo({ className = '' }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <svg
        viewBox="0 0 40 44"
        className="h-9 w-8 shrink-0"
        role="img"
        aria-label="NIAT"
      >
        {/* Crest outline: flat shoulders, tapered point. */}
        <path
          d="M2 2h36v26c0 6.5-7.2 11.4-18 14C9.2 39.4 2 34.5 2 28V2z"
          fill="#ffffff"
          stroke="#0f1a38"
          strokeWidth="2.5"
        />
        <path
          d="M6.5 6.5h27v21c0 4.7-5.4 8.4-13.5 10.5C11.9 35.9 6.5 32.2 6.5 27.5v-21z"
          fill="none"
          stroke="#0f1a38"
          strokeWidth="1"
        />
        <text
          x="20"
          y="23"
          textAnchor="middle"
          fontSize="11.5"
          fontWeight="700"
          letterSpacing="0.6"
          fill="#0f1a38"
          fontFamily="Roboto, sans-serif"
        >
          NIAT
        </text>
      </svg>
      <span className="text-[12px] leading-[1.25] font-bold text-white">
        NxtWave Institute of
        <br />
        Advanced Technologies
      </span>
    </div>
  )
}

/** The stacked NXT / WAVE lockup used in the in-course header. */
export function NxtWaveWordmark({ className = '' }: { className?: string }) {
  return (
    <div
      className={`flex items-start gap-1 leading-none select-none ${className}`}
      role="img"
      aria-label="NxtWave"
    >
      <span className="font-bold tracking-[0.02em] text-lms-ink">
        <span className="block text-[17px]">NXT</span>
        <span className="block text-[17px]">
          WAV
          <span className="relative">
            E
            <svg
              viewBox="0 0 18 6"
              aria-hidden="true"
              className="absolute -right-0.5 -bottom-1 h-1.5 w-4"
            >
              <path
                d="M0 4 Q4.5 0 9 4 T18 4"
                fill="none"
                stroke="#12203c"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </span>
        </span>
      </span>
      <span className="mt-0.5 text-[7px] font-bold text-lms-ink/60">™</span>
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Icons. One stroke weight, one 24-box, so they sit on a shared baseline in
 * the rail instead of each carrying its own optical size.
 * ------------------------------------------------------------------------ */

type IconProps = { className?: string }

function Svg({
  children,
  className = 'h-4 w-4',
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {children}
    </svg>
  )
}

export const IconHome = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5.5 9.5V21h13V9.5" />
  </Svg>
)

export const IconJourney = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V8l5-4v16" />
    <path d="M9 20V9l5 3v8" />
    <path d="M14 20v-6l5 2.5V20" />
  </Svg>
)

export const IconCourses = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="7" height="16" rx="1.2" />
    <rect x="14" y="4" width="7" height="9" rx="1.2" />
    <path d="M14 17h7" />
  </Svg>
)

export const IconBookmark = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3.5h12v17l-6-4.2-6 4.2z" />
  </Svg>
)

export const IconDiscussions = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5h16v10H9l-5 4z" />
  </Svg>
)

export const IconNotebook = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3h12v18H7z" />
    <path d="M7 3H5v18h2" />
    <path d="M10.5 8h5M10.5 12h5" />
  </Svg>
)

export const IconPlayground = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M10 8.5l5 3.5-5 3.5z" />
  </Svg>
)

export const IconSnippets = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6.5 4.5 12 9 17.5" />
    <path d="M15 6.5 19.5 12 15 17.5" />
  </Svg>
)

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="10.5" cy="10.5" r="6.5" />
    <path d="M15.5 15.5 21 21" />
  </Svg>
)

export const IconTimer = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="13" r="8" />
    <path d="M12 13V9" />
    <path d="M9.5 2.5h5" />
  </Svg>
)

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 5l7 7-7 7" />
  </Svg>
)

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 9l7 7 7-7" />
  </Svg>
)

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 5l-7 7 7 7" />
  </Svg>
)

export const IconCollapse = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 5l-6 7 6 7" />
    <path d="M19 4v16" />
  </Svg>
)

/* --- item-type icons: one per challenge mode ---------------------------- */

/** Trust or Challenge: the default investigation. */
export const IconInvestigate = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M15.8 15.8 21 21" />
    <path d="M11 8v3.5l2.5 1.5" />
  </Svg>
)

/** Break the Tests: a suite with a gap in it. */
export const IconBreakTests = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 4.5h14" />
    <path d="M9 4.5v5L5 19.5h14L15 9.5v-5" />
    <path d="M9.5 14.5h5" />
  </Svg>
)

/** Which AI Is Wrong: two claims weighed against each other. */
export const IconCompare = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5v17" />
    <path d="M4 8h16" />
    <path d="M4 8 1.8 13h4.4z" />
    <path d="M20 8 17.8 13h4.4z" />
  </Svg>
)

/** Find the Failure: the located step. */
export const IconTarget = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <circle cx="12" cy="12" r="3.5" />
  </Svg>
)

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5 9.5 17 19 7.5" />
  </Svg>
)
