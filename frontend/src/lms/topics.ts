/** Group a subject's investigations under its registered topics.
 *
 * The backend topic registry is the curriculum: every subject lists all of its
 * topics, in order, whether or not any challenge is published under them yet.
 * So grouping starts from the registered topics and drops challenges into
 * them, rather than starting from the challenges - a topic with nothing in it
 * still appears, in its place.
 *
 * Shared by the contents rail and the subject page so both show the same
 * order.
 */

import type { ChallengeCard, Subject, SubjectTopic } from '../api'

export interface TopicGroup {
  /** The registered topic, or null for a challenge filed under a topic the
   *  registry does not have (validation prevents this for new content). */
  topic: SubjectTopic | null
  name: string
  number: number | null
  /** Loaded investigations, easiest first. Empty while still loading. */
  cards: ChallengeCard[]
  /** Loaded count once the list is in, the published count before that. */
  count: number
}

export function groupByTopic(
  subject: Subject,
  cards: ChallengeCard[] | null,
): TopicGroup[] {
  const buckets = new Map<string, ChallengeCard[]>()
  for (const card of cards ?? []) {
    const list = buckets.get(card.topic)
    if (list) list.push(card)
    else buckets.set(card.topic, [card])
  }

  const groups: TopicGroup[] = subject.topics.map((topic) => {
    const list = sortItems(buckets.get(topic.name) ?? [])
    buckets.delete(topic.name)
    return {
      topic,
      name: topic.name,
      number: topic.number,
      cards: list,
      count: cards ? list.length : topic.challenge_count,
    }
  })

  // Anything left names a topic the registry does not have. Shown at the end
  // rather than dropped: silently hiding published content would be worse
  // than an out-of-place group.
  for (const [name, list] of buckets) {
    groups.push({
      topic: null,
      name,
      number: null,
      cards: sortItems(list),
      count: list.length,
    })
  }
  return groups
}

/** Easiest first inside a topic, then by id so the order is stable. */
function sortItems(cards: ChallengeCard[]): ChallengeCard[] {
  return [...cards].sort(
    (a, b) => a.difficulty.localeCompare(b.difficulty) || a.id.localeCompare(b.id),
  )
}
