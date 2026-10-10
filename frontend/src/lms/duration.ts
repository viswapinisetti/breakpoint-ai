/** Durations for the contents rail and the subject page.
 *
 * The estimates themselves come from the backend (`app/engine/duration.py`):
 * each investigation's from its difficulty and mode, each topic's and
 * subject's as the sum of its investigations. So a duration grows with the
 * number of questions and with how hard they are, and every view shows the
 * same number. This module only formats them.
 */

/** "45 mins", "2 hours, 5 mins" - the platform's own phrasing. */
export function formatDuration(totalMinutes: number): string {
  const minutes = Math.max(1, Math.round(totalMinutes))
  if (minutes < 60) return `${minutes} min${minutes === 1 ? '' : 's'}`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  const hourPart = `${hours} hour${hours === 1 ? '' : 's'}`
  if (rest === 0) return hourPart
  return `${hourPart}, ${rest} min${rest === 1 ? '' : 's'}`
}

export function sumMinutes(cards: { estimated_minutes: number }[]): number {
  return cards.reduce((total, c) => total + c.estimated_minutes, 0)
}
