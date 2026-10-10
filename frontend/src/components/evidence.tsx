/** Evidence Board (PRD v0.2 section 6.4).
 *
 * A card is structured, not a paragraph. The fields differ per type - a
 * Calculation asks for an expression, a value and a unit; a Counterexample asks
 * for an input and two outcomes - because that is what makes evidence
 * checkable rather than merely assertive.
 *
 * The board holds 1-5 draft cards which can be added, edited, reordered and
 * removed. Submission sends them as one immutable revision.
 */

import { useState } from 'react'
import type { EvidenceCardDraft, EvidenceResult } from '../api'

export const MAX_CARDS = 5

interface FieldSpec {
  key: keyof EvidenceCardDraft
  label: string
  placeholder: string
  mono?: boolean
  wide?: boolean
}

/** Fields per card type, straight from PRD v0.2 section 6.4. */
export const CARD_SPECS: Record<
  string,
  { label: string; blurb: string; fields: FieldSpec[] }
> = {
  calculation: {
    label: 'Calculation',
    blurb: 'A numerical step that produces a different result.',
    fields: [
      { key: 'expression', label: 'Expression', placeholder: '800 * 20 / 100', mono: true },
      { key: 'value', label: 'Result', placeholder: '160', mono: true },
      { key: 'unit', label: 'Unit', placeholder: 'Rs.' },
    ],
  },
  contradiction: {
    label: 'Contradiction',
    blurb: 'Two statements in the artifact that conflict.',
    fields: [
      { key: 'reference', label: 'First reference', placeholder: 'step 2' },
      { key: 'reference_b', label: 'Second reference', placeholder: 'step 4' },
      { key: 'conflict', label: 'The conflict', placeholder: 'Step 4 reuses the rate step 2 established, after A has left.', wide: true },
    ],
  },
  counterexample: {
    label: 'Counterexample',
    blurb: 'An input allowed by the problem where the claim breaks.',
    fields: [
      { key: 'input', label: 'Input', placeholder: '[-5, -10, -2]', mono: true, wide: true },
      { key: 'expected', label: 'Claimed outcome', placeholder: '-2', mono: true },
      { key: 'observed', label: 'Actual outcome', placeholder: '0', mono: true },
    ],
  },
  test_case: {
    label: 'Test case',
    blurb: 'A condition the artifact fails.',
    fields: [
      { key: 'input', label: 'Condition', placeholder: 'empty list', wide: true },
      { key: 'expected', label: 'Expected', placeholder: 'error' },
      { key: 'observed', label: 'Observed', placeholder: '0' },
    ],
  },
  data_point: {
    label: 'Data point',
    blurb: 'An exact value from the supplied data.',
    fields: [
      { key: 'reference', label: 'Cell / row', placeholder: 'Q2 revenue' },
      { key: 'value', label: 'Value', placeholder: '2500', mono: true },
    ],
  },
  rule: {
    label: 'Rule',
    blurb: 'The principle being violated, and how.',
    fields: [
      { key: 'reference', label: 'Applies to', placeholder: 'step 3' },
      { key: 'rule', label: 'The rule and the violation', placeholder: 'A percentage is taken of the value that exists at that moment; step 3 uses the original price.', wide: true },
    ],
  },
  trace: {
    label: 'Trace',
    blurb: 'The path that reaches the failure.',
    fields: [
      { key: 'input', label: 'Path', placeholder: '1000 → 800 → 800 + 200', mono: true, wide: true },
    ],
  },
  rewrite: {
    label: 'Rewrite',
    blurb: 'The corrected statement.',
    fields: [
      { key: 'reference', label: 'Replaces', placeholder: 'step 3' },
      { key: 'replacement', label: 'Corrected text', placeholder: '20% of Rs 800 = Rs 160', wide: true },
    ],
  },
}

export function emptyCard(type: string): EvidenceCardDraft {
  return {
    type,
    reference: '',
    references_step: null,
    why_supports: '',
    expression: '',
    value: '',
    unit: '',
    reference_b: '',
    conflict: '',
    input: '',
    expected: '',
    observed: '',
    rule: '',
    replacement: '',
  }
}

function CardEditor({
  card,
  index,
  total,
  stepCount,
  onChange,
  onRemove,
  onMove,
}: {
  card: EvidenceCardDraft
  index: number
  total: number
  stepCount: number
  onChange: (next: EvidenceCardDraft) => void
  onRemove: () => void
  onMove: (delta: number) => void
}) {
  const spec = CARD_SPECS[card.type]
  if (!spec) return null
  const set = (k: keyof EvidenceCardDraft, v: string | number | null) =>
    onChange({ ...card, [k]: v })

  return (
    <div className="bp-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold">
          <span className="mr-2 text-slate-400">{index + 1}.</span>
          {spec.label}
        </div>
        <div className="flex items-center gap-1">
          {/* Reorder via buttons, not drag: PRD v0.2 6.3 requires a
              non-drag interaction. */}
          <button
            onClick={() => onMove(-1)}
            disabled={index === 0}
            aria-label={`Move card ${index + 1} up`}
            className="rounded border border-slate-200 px-2 py-0.5 text-xs disabled:opacity-30"
          >
            ↑
          </button>
          <button
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            aria-label={`Move card ${index + 1} down`}
            className="rounded border border-slate-200 px-2 py-0.5 text-xs disabled:opacity-30"
          >
            ↓
          </button>
          <button
            onClick={onRemove}
            aria-label={`Remove card ${index + 1}`}
            className="rounded border border-slate-200 px-2 py-0.5 text-xs text-failure"
          >
            Remove
          </button>
        </div>
      </div>
      <p className="mt-0.5 text-xs text-ink-muted">{spec.blurb}</p>

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {spec.fields.map((f) => (
          <label key={String(f.key)} className={f.wide ? 'sm:col-span-2' : ''}>
            <span className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">
              {f.label}
            </span>
            <input
              value={(card[f.key] as string) ?? ''}
              onChange={(e) => set(f.key, e.target.value)}
              placeholder={f.placeholder}
              className={`mt-1 w-full rounded-control border border-slate-200 px-3 py-2 text-sm focus:border-brand focus:outline-none ${
                f.mono ? 'font-mono' : ''
              }`}
            />
          </label>
        ))}

        <label>
          <span className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">
            Step referenced
          </span>
          <select
            value={card.references_step ?? ''}
            onChange={(e) =>
              set('references_step', e.target.value ? Number(e.target.value) : null)
            }
            className="mt-1 w-full rounded-control border border-slate-200 px-3 py-2 text-sm"
          >
            <option value="">None</option>
            {Array.from({ length: stepCount }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                Step {n}
              </option>
            ))}
          </select>
        </label>

        <label className="sm:col-span-2">
          <span className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">
            Why this supports my judgment
          </span>
          <textarea
            value={card.why_supports}
            onChange={(e) => set('why_supports', e.target.value)}
            rows={2}
            placeholder="The second increase is applied to the reduced price of Rs 800."
            className="mt-1 w-full resize-y rounded-control border border-slate-200 px-3 py-2 text-sm focus:border-brand focus:outline-none"
          />
        </label>
      </div>
    </div>
  )
}

export function EvidenceBoard({
  cards,
  setCards,
  allowedTypes,
  stepCount,
  disabled,
}: {
  cards: EvidenceCardDraft[]
  setCards: (next: EvidenceCardDraft[]) => void
  allowedTypes: string[]
  stepCount: number
  disabled: boolean
}) {
  const [adding, setAdding] = useState(allowedTypes[0] ?? 'calculation')

  function add() {
    if (cards.length >= MAX_CARDS) return
    setCards([...cards, emptyCard(adding)])
  }

  function move(index: number, delta: number) {
    const target = index + delta
    if (target < 0 || target >= cards.length) return
    const next = [...cards]
    ;[next[index], next[target]] = [next[target], next[index]]
    setCards(next)
  }

  return (
    <div className="space-y-3">
      {cards.map((card, i) => (
        <CardEditor
          key={i}
          card={card}
          index={i}
          total={cards.length}
          stepCount={stepCount}
          onChange={(next) =>
            setCards(cards.map((c, j) => (j === i ? next : c)))
          }
          onRemove={() => setCards(cards.filter((_, j) => j !== i))}
          onMove={(d) => move(i, d)}
        />
      ))}

      {cards.length === 0 && (
        <p className="rounded-card bg-page px-4 py-5 text-center text-sm text-ink-muted">
          Add a card to begin. Selecting “wrong” is not evidence — show the
          mechanism.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <select
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
          disabled={disabled || cards.length >= MAX_CARDS}
          className="rounded-control border border-slate-200 px-3 py-2 text-sm"
          aria-label="Card type to add"
        >
          {allowedTypes.map((t) => (
            <option key={t} value={t}>
              {CARD_SPECS[t]?.label ?? t}
            </option>
          ))}
        </select>
        <button
          onClick={add}
          disabled={disabled || cards.length >= MAX_CARDS}
          className="bp-btn bp-btn-ghost"
        >
          + Add card
        </button>
        <span className="text-xs text-ink-muted">
          {cards.length}/{MAX_CARDS} cards
        </span>
      </div>
    </div>
  )
}

/** Result of one submission.
 *
 * PRD v0.2 section 6.4: "The UI distinguishes 'Calculation checked' from
 * 'Evidence supports your claim'." Those are two different statements and are
 * rendered as two different lines here.
 */
export function EvidenceResultCard({ result }: { result: EvidenceResult }) {
  const ran = result.checks.filter((c) => c.status !== 'not_applicable')
  const tone =
    result.status === 'supported'
      ? 'border-emerald-200 bg-emerald-50'
      : result.status === 'review_pending'
        ? 'border-blue-200 bg-brand-soft'
        : 'border-amber-200 bg-amber-50'

  return (
    <div className={`rounded-card border p-4 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-bold">
          Revision {result.revision}
          {result.replayed && (
            <span className="ml-2 text-xs font-normal text-ink-muted">
              (already submitted)
            </span>
          )}
        </span>
        <span className="text-sm font-bold tabular-nums">
          {result.strength > 0 ? `${result.strength.toFixed(1)}/10` : ''}
        </span>
      </div>

      {/* Two distinct statements, never collapsed into one. */}
      {ran.length > 0 && (
        <div className="mt-2 text-sm">
          <span className="font-bold">
            {result.checks_passed ? 'Checks passed' : 'Checks failed'}:
          </span>{' '}
          <span className="text-ink-muted">
            {ran.map((c) => c.detail).join(' ')}
          </span>
        </div>
      )}
      <div className="mt-1 text-sm">
        <span className="font-bold">
          {result.status === 'supported'
            ? 'Evidence supports your claim'
            : result.status === 'review_pending'
              ? 'Sent for review'
              : 'Evidence does not yet support your claim'}
        </span>
      </div>

      {result.feedback && (
        <p className="mt-2 text-sm text-slate-700">{result.feedback}</p>
      )}
      {result.missing && (
        <p className="mt-1.5 text-sm text-needs-evidence">
          <span className="font-bold">To strengthen:</span> {result.missing}
        </p>
      )}

      {Object.keys(result.dimensions).length > 0 && (
        <dl className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
          {Object.entries(result.dimensions).map(([k, v]) => (
            <div key={k} className="rounded bg-white/70 px-2 py-1.5">
              <dt className="text-ink-muted capitalize">{k.replace(/_/g, ' ')}</dt>
              <dd className="font-bold tabular-nums">{String(v)}/10</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
