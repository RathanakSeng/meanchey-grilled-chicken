import { cx } from './ui'

/**
 * A labelled checkbox in a list's filter area, sized like the other filter controls. Used for
 * "Show deactivated" / "Show cancelled": removed records stay out of lists unless it's ticked.
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
        'flex min-h-[38px] cursor-pointer select-none items-center gap-2 whitespace-nowrap rounded-lg bg-white px-3 py-2 text-sm shadow-sm ring-1 ring-inset transition',
        checked ? 'text-brand-700 ring-brand-400' : 'text-stone-700 ring-stone-300 hover:bg-stone-50',
      )}
    >
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-stone-300 text-brand-600 accent-brand-600 focus:ring-brand-500"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}
