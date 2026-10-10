/** Steps 2 and 3 - the in-course CONTENTS rail.
 *
 *  Collapsed, it lists all 19 subjects with a duration and a chevron. Opened,
 *  the subject's header lifts to a blue band and every one of its registered
 *  topics appears beneath it as a numbered child, in curriculum order, with
 *  that topic's investigations on a vertical timeline under it.
 *
 *  Every topic is listed, including topics with nothing published yet: the
 *  topic registry is the curriculum, and a rail that only showed topics with
 *  content would present a different course from the one being taught.
 */

import type { ChallengeCard, Subject } from '../api'
import {
  IconBreakTests,
  IconCheck,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconCollapse,
  IconCompare,
  IconInvestigate,
  IconTarget,
} from './brand'
import { formatDuration, sumMinutes } from './duration'
import { groupByTopic, type TopicGroup } from './topics'

const MODE_ICON: Record<
  string,
  (p: { className?: string }) => React.ReactElement
> = {
  trust_or_challenge: IconInvestigate,
  break_the_tests: IconBreakTests,
  which_ai_is_wrong: IconCompare,
  find_the_failure: IconTarget,
}

function Clock({ label }: { label: string }) {
  return (
    <span className="mt-0.5 flex items-center gap-1 text-[11px] text-white/45">
      <svg
        viewBox="0 0 24 24"
        aria-hidden="true"
        className="h-3 w-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7.5V12l3 2" strokeLinecap="round" />
      </svg>
      {label}
    </span>
  )
}

/** Status dot on the timeline. Completed reads green with a tick; started
 *  reads as a filled ring; untouched is hollow. No colour-only signalling -
 *  each state also differs in shape. */
function StatusDot({ card }: { card: ChallengeCard }) {
  if (card.completed) {
    return (
      <span className="z-10 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-lms-done text-white">
        <IconCheck className="h-2.5 w-2.5" />
      </span>
    )
  }
  if (card.attempted) {
    return (
      <span className="z-10 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-2 border-white bg-lms-contents">
        <span className="h-1.5 w-1.5 rounded-full bg-white" />
      </span>
    )
  }
  return (
    <span className="z-10 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-white/45 bg-lms-contents" />
  )
}

interface Props {
  subjects: Subject[]
  openKey: string | null
  /** Challenges for the open subject. `null` while they are still loading. */
  challenges: ChallengeCard[] | null
  selectedId: string | null
  onToggleSubject: (key: string) => void
  onSelectChallenge: (id: string) => void
  onCollapse: () => void
  onBackToCatalog: () => void
}

export function ContentsRail({
  subjects,
  openKey,
  challenges,
  selectedId,
  onToggleSubject,
  onSelectChallenge,
  onCollapse,
  onBackToCatalog,
}: Props) {
  const open = subjects.find((s) => s.key === openKey) ?? null

  return (
    // Pinned below the 58px top header, not under it: pinned at top-0, the
    // header covered the rail's own subject heading once the page scrolled.
    <aside className="lms-scroll sticky top-[58px] flex h-[calc(100vh-58px)] w-[248px] shrink-0 flex-col overflow-y-auto bg-lms-contents">
      {/* --- header ---------------------------------------------------- */}
      {open ? (
        <button
          onClick={() => onToggleSubject(open.key)}
          className="sticky top-0 z-20 flex w-full items-start gap-2 bg-lms-contents-open px-4 py-3 text-left"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-bold text-white">
              {open.name}
            </span>
            <Clock label={formatDuration(open.estimated_minutes)} />
          </span>
          <IconChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-white/85" />
        </button>
      ) : (
        <div className="sticky top-0 z-20 flex items-center gap-2 bg-lms-contents px-4 py-3.5">
          <button
            onClick={onBackToCatalog}
            aria-label="Back to Other Courses"
            className="text-white/70 hover:text-white"
          >
            <IconChevronLeft className="h-4 w-4" />
          </button>
          <span className="flex-1 border-b-2 border-lms-contents-open pb-1 text-[12px] font-bold tracking-[0.1em] text-white uppercase">
            Contents
          </span>
          <button
            onClick={onCollapse}
            aria-label="Collapse contents"
            className="text-white/70 hover:text-white"
          >
            <IconCollapse className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* --- open subject: every registered topic, then its challenges --- */}
      {open && (
        <div className="pb-6">
          {challenges === null && (
            <p className="px-4 pt-3 text-[11px] text-lms-contents-text">
              Loading investigations…
            </p>
          )}
          {groupByTopic(open, challenges).map((group) => (
            <section
              key={group.name}
              aria-label={
                group.number ? `Topic ${group.number}: ${group.name}` : group.name
              }
            >
              {/* Topic row: the numbered child of the open subject. */}
              <div className="flex items-start gap-2 px-4 pt-3.5 pb-1.5">
                <span className="mt-px w-[18px] shrink-0 text-center text-[11px] font-bold text-white/45 tabular">
                  {group.number ?? '·'}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-[12px] leading-snug font-bold ${
                      group.count > 0 ? 'text-white/90' : 'text-white/50'
                    }`}
                  >
                    {group.name}
                  </span>
                  <span className="mt-0.5 block text-[10.5px] text-white/40 tabular">
                    {topicMeta(group)}
                  </span>
                </span>
              </div>

              {group.cards.length > 0 && (
                <ul className="relative">
                  {/* One continuous rail behind the dots. */}
                  <span
                    aria-hidden="true"
                    className="absolute top-4 bottom-4 left-[23px] w-px bg-lms-contents-line"
                  />
                  {group.cards.map((card) => {
                    const Icon = MODE_ICON[card.challenge_mode] ?? IconInvestigate
                    const active = card.id === selectedId
                    return (
                      <li key={card.id}>
                        <button
                          onClick={() => onSelectChallenge(card.id)}
                          aria-current={active ? 'true' : undefined}
                          className={`flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition ${
                            active
                              ? 'bg-lms-contents-hover'
                              : 'hover:bg-lms-contents-hover/60'
                          }`}
                        >
                          <StatusDot card={card} />
                          <span className="min-w-0 flex-1">
                            <span
                              className={`block text-[12.5px] leading-snug ${
                                active
                                  ? 'font-bold text-white'
                                  : 'text-lms-contents-text'
                              }`}
                            >
                              {itemLabel(card)}
                            </span>
                            <Clock label={formatDuration(card.estimated_minutes)} />
                          </span>
                          <Icon
                            className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                              active ? 'text-white' : 'text-white/40'
                            }`}
                          />
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}

      {/* --- collapsed: every subject ---------------------------------- */}
      {/* Every subject opens, even with nothing published: its topics are the
          curriculum and are worth seeing on their own. */}
      {!open && (
        <ul className="pb-8">
          {subjects.map((subject) => (
            <li key={subject.key}>
              <button
                onClick={() => onToggleSubject(subject.key)}
                className="flex w-full items-start gap-2 border-b border-white/[0.06] px-4 py-3.5 text-left transition hover:bg-lms-contents-hover"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] leading-snug text-white">
                    {subject.name}
                  </span>
                  <Clock label={formatDuration(subject.estimated_minutes)} />
                </span>
                <IconChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-white/45" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}

/** "3 investigations · 42 mins", or a plain note for an empty topic. Before
 *  the items load, the topic's own total from the subject listing is used, so
 *  the number is there immediately and does not change when they arrive. */
function topicMeta(group: TopicGroup): string {
  const { count, cards } = group
  if (count === 0) return 'No investigations yet'
  const noun = count === 1 ? 'investigation' : 'investigations'
  const minutes =
    cards.length > 0 ? sumMinutes(cards) : (group.topic?.estimated_minutes ?? 0)
  return minutes > 0 ? `${count} ${noun} · ${formatDuration(minutes)}` : `${count} ${noun}`
}

function itemLabel(card: ChallengeCard): string {
  if (card.subtopic) return card.subtopic
  const first = card.question.split(/(?<=[.?])\s/)[0] ?? card.question
  return first.length > 64 ? `${first.slice(0, 61)}…` : first
}
