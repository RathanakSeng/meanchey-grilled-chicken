import { cx } from './ui'

export interface Segment<T extends string> {
  value: T
  label: string
}

/**
 * A row of mutually exclusive buttons (radio group). `value` may match no segment (e.g. a
 * "custom" state): then none is selected. `suggested` gets a dashed outline as a hint only; the
 * user still has to click it.
 *
 * `slots` (optional) is the full, ordered list of columns shared by several controls stacked
 * under each other (e.g. every level on the Access tab). A slot this control has no segment for
 * is drawn as an empty "—" cell, so the same value sits in the same column in every row.
 *
 * Layout: phones: full width, 4 columns as 2×2; tablets: one full-width row of equal columns;
 * desktop: every column the same fixed width (fits the longest Khmer label), so stacked controls
 * line up and never clip their labels.
 */
export function SegmentedControl<T extends string>({
  segments,
  slots,
  value,
  onChange,
  disabled = false,
  suggested,
  suggestedLabel,
  unavailableLabel,
  label,
}: {
  segments: Segment<T>[]
  slots?: readonly T[]
  value: string | null
  onChange(value: T): void
  disabled?: boolean
  suggested?: T
  suggestedLabel?: string
  /** Tooltip of an empty slot, e.g. "Not available for this feature". */
  unavailableLabel?: string
  label: string
}) {
  const bySlot = new Map(segments.map((s) => [s.value, s]))
  const columns: (Segment<T> | { empty: T })[] = slots
    ? slots.map((slot) => bySlot.get(slot) ?? { empty: slot })
    : segments

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx(
        'grid w-full gap-1 rounded-xl bg-stone-100 p-1',
        columns.length > 3
          ? 'grid-cols-2 sm:auto-cols-fr sm:grid-flow-col sm:grid-cols-none'
          : 'auto-cols-fr grid-flow-col',
        'lg:w-auto lg:shrink-0 lg:auto-cols-[9.5rem]',
        disabled && 'opacity-60',
      )}
    >
      {columns.map((c) => {
        if ('empty' in c) {
          return (
            <span
              key={c.empty}
              aria-hidden
              title={unavailableLabel}
              className="flex min-h-10 items-center justify-center text-sm text-stone-300"
            >
              —
            </span>
          )
        }
        const selected = c.value === value
        const isSuggested = !selected && c.value === suggested
        return (
          <button
            key={c.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            title={isSuggested ? suggestedLabel : undefined}
            onClick={() => !selected && onChange(c.value)}
            className={cx(
              // min-h-10: thumb-friendly in the Mini App.
              'min-h-10 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
              selected
                ? 'bg-white text-brand-700 shadow-sm ring-1 ring-stone-200'
                : 'text-stone-600 hover:text-stone-900 disabled:hover:text-stone-600',
              isSuggested && 'outline-dashed outline-1 -outline-offset-2 outline-brand-400',
              disabled && 'cursor-not-allowed',
            )}
          >
            {c.label}
          </button>
        )
      })}
    </div>
  )
}
