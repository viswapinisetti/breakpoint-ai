/** The right pane when a subject is open but no investigation is selected.
 *
 *  Strictly an index of what is in the subject - real rows from the API, no
 *  written material. Breakpoint has no study text to teach from: the content
 *  *is* the investigations, and a page of prose explaining them would be
 *  something we invented rather than something the learner works on.
 *
 *  Every registered topic is listed, numbered and in curriculum order, with
 *  its investigations beneath it. A topic with nothing published says so in
 *  place rather than disappearing, so the page always shows the whole course.
 *
 *  It also deliberately does not auto-open the first investigation. Starting
 *  one creates an attempt and touches the verification streak, so clicking
 *  through subjects to look around would quietly manufacture attempts and
 *  corrupt the very trust metrics the product reports.
 */

import type { ChallengeCard, Subject } from '../api'
import {
  IconBreakTests,
  IconCheck,
  IconCompare,
  IconInvestigate,
  IconTarget,
} from './brand'
import { formatDuration, sumMinutes } from './duration'
import { groupByTopic } from './topics'

const MODE_ICON: Record<
  string,
  (p: { className?: string }) => React.ReactElement
> = {
  trust_or_challenge: IconInvestigate,
  break_the_tests: IconBreakTests,
  which_ai_is_wrong: IconCompare,
  find_the_failure: IconTarget,
}

const MODE_LABEL: Record<string, string> = {
  trust_or_challenge: 'Trust or Challenge',
  break_the_tests: 'Break the Tests',
  which_ai_is_wrong: 'Which AI Is Wrong',
  find_the_failure: 'Find the Failure',
}

const DIFFICULTY_LABEL: Record<string, string> = {
  '1': 'Visible failure',
  '2': 'One step hidden',
  '3': 'Plausible',
  '4': 'Expert trap',
  '5': 'Adversarial',
}

export function SubjectIndex({
  subject,
  challenges,
  onOpen,
}: {
  subject: Subject
  challenges: ChallengeCard[] | null
  onOpen: (challengeId: string) => void
}) {
  if (challenges === null) {
    return (
      <p className="mx-auto max-w-[860px] px-2 text-[14px] text-slate-500">
        Loading investigations…
      </p>
    )
  }

  const done = challenges.filter((c) => c.completed).length
  const groups = groupByTopic(subject, challenges)
  const withContent = groups.filter((g) => g.cards.length > 0).length

  return (
    <div className="mx-auto max-w-[860px]">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-[22px] font-bold text-lms-ink">{subject.name}</h1>
        <p className="text-[13px] text-slate-500 tabular">
          {subject.topics.length} topics · {challenges.length}{' '}
          {challenges.length === 1 ? 'investigation' : 'investigations'} in{' '}
          {withContent} of them · {formatDuration(sumMinutes(challenges))} ·{' '}
          {done} completed
        </p>
      </header>

      <div className="mt-5 space-y-6">
        {groups.map((group) => (
          <section key={group.name}>
            <h2 className="flex items-baseline gap-2 text-[14px] font-bold text-lms-ink">
              <span className="text-[12px] font-bold text-slate-400 tabular">
                {group.number !== null ? `${group.number}.` : '·'}
              </span>
              {group.name}
              <span className="ml-auto text-[12px] font-normal text-slate-400 tabular">
                {group.cards.length > 0
                  ? `${group.cards.length} ${
                      group.cards.length === 1 ? 'investigation' : 'investigations'
                    } · ${formatDuration(sumMinutes(group.cards))}`
                  : ''}
              </span>
            </h2>
            {group.cards.length === 0 ? (
              <p className="mt-2 rounded-[10px] border border-dashed border-lms-hairline bg-white/60 px-4 py-3 text-[13px] text-slate-400">
                No investigations published in this topic yet.
              </p>
            ) : (
            <ul className="mt-2 overflow-hidden rounded-[10px] border border-lms-hairline bg-white">
              {group.cards.map((card) => {
                const Icon = MODE_ICON[card.challenge_mode] ?? IconInvestigate
                return (
                  <li
                    key={card.id}
                    className="border-b border-lms-hairline last:border-0"
                  >
                    <button
                      onClick={() => onOpen(card.id)}
                      className="flex w-full items-start gap-3.5 px-4 py-3.5 text-left transition hover:bg-[#f7f9fd]"
                    >
                      {card.completed ? (
                        <span className="mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full bg-lms-done text-white">
                          <IconCheck className="h-2.5 w-2.5" />
                        </span>
                      ) : card.attempted ? (
                        <span className="mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-2 border-lms-link">
                          <span className="h-1.5 w-1.5 rounded-full bg-lms-link" />
                        </span>
                      ) : (
                        <span className="mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-slate-300" />
                      )}

                      <span className="min-w-0 flex-1">
                        <span className="block text-[14.5px] font-normal text-lms-ink">
                          {card.subtopic || firstSentence(card.question)}
                        </span>
                        <span className="mt-0.5 block text-[12.5px] text-slate-500 tabular">
                          {MODE_LABEL[card.challenge_mode] ?? card.challenge_mode}
                          {' · '}
                          {DIFFICULTY_LABEL[card.difficulty] ??
                            `Level ${card.difficulty}`}
                          {' · '}
                          {formatDuration(card.estimated_minutes)}
                          {card.attempted && !card.completed && ' · in progress'}
                        </span>
                      </span>

                      <Icon className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
                    </button>
                  </li>
                )
              })}
            </ul>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}

function firstSentence(question: string): string {
  const first = question.split(/(?<=[.?])\s/)[0] ?? question
  return first.length > 96 ? `${first.slice(0, 93)}…` : first
}
