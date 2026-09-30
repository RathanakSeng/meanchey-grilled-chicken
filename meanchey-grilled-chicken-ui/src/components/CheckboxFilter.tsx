import { cx } from './ui'

/**
 * A labelled checkbox in a list's filter area, sized like the other filter controls. Used for
 * "Show deactivated" / "Show cancelled": removed records stay out of lists unless it's ticked.
 * On phones the label wraps inside the box (it may share a row with a sort dropdown), so a long
 * Khmer label never overflows the screen; from sm up it stays on one line.
 */
export function CheckboxFilter({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange(checked: boolean): void
}) {
  return (
    <label
      className={cx(
        'flex min-h-[38px] min-w-0 cursor-pointer select-none items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm leading-snug shadow-sm ring-1 ring-inset transition sm:whitespace-nowrap',
        checked ? 'text-brand-700 ring-brand-400' : 'text-stone-700 ring-stone-300 hover:bg-stone-50',
      )}
    >
      <input
        type="checkbox"
        className="h-4 w-4 shrink-0 rounded border-stone-300 text-brand-600 accent-brand-600 focus:ring-brand-500"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0 [overflow-wrap:anywhere]">{label}</span>
    </label>
  )
}
