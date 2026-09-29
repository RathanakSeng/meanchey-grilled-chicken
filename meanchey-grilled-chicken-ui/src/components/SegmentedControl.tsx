import { cx } from './ui'

export interface Segment<T extends string> {
  value: T
  label: string
}

/**
 * A row of mutually exclusive buttons (radio group). `value` may match no segment (e.g. a
 * "custom" state): then none is selected. `suggested` gets a dashed outline as a hint only; the
 * user still has to click it. With more than 3 segments it wraps to a 2×2 grid on narrow screens.
 */
export function SegmentedControl<T extends string>({
  segments,
  value,
  onChange,
  disabled = false,
  suggested,
  suggestedLabel,
  label,
}: {
  segments: Segment<T>[]
  value: string | null
  onChange(value: T): void
  disabled?: boolean
  suggested?: T
  suggestedLabel?: string
  label: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx(
        'grid w-full gap-1 rounded-xl bg-stone-100 p-1',
        // Phones: full width, 4 segments as 2×2. Tablets: one full-width row of equal segments.
        segments.length > 3
          ? 'grid-cols-2 sm:auto-cols-fr sm:grid-flow-col sm:grid-cols-none'
          : 'auto-cols-fr grid-flow-col',
        // Desktop: every segment the same fixed width (fits the longest Khmer label), so
        // controls with 3 or 4 levels line up and never clip their labels.
        'lg:w-auto lg:shrink-0 lg:auto-cols-[9.5rem]',
        disabled && 'opacity-60',
      )}
    >
      {segments.map((s) => {
        const selected = s.value === value
        const isSuggested = !selected && s.value === suggested
        return (
          <button
            key={s.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            title={isSuggested ? suggestedLabel : undefined}
            onClick={() => !selected && onChange(s.value)}
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
            {s.label}
          </button>
        )
      })}
    </div>
  )
}
