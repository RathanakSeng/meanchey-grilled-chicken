import type { InputHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Input, cx } from '@/components/ui'
import { useCalendarNames } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { AttendanceRules, ShiftCode, ShiftTime } from '@/lib/types'

/** ISO weekdays, Monday first (Monday = 1 … Sunday = 7). */
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const

/** Short weekday name for an ISO weekday ("Mon" / "ច័ន្ទ"). */
export function useWeekdayName() {
  const { t } = useTranslation()
  return (iso: number) => t(`common.weekdaysShort.${iso % 7}`)
}

/** "Tue 13 Oct 2026" / "អង្គារ 13 តុលា 2026" from our own names (browsers often lack Khmer
 *  date data). */
export function useDayName() {
  const names = useCalendarNames()
  return (iso: string) => `${names.day(iso)} ${iso.slice(0, 4)}`
}

/** Tracked weekdays as short text, runs joined: "Mon–Sat", "Mon–Wed, Fri". */
export function useWeekdaysText() {
  const weekday = useWeekdayName()
  return (days: number[]) => {
    const sorted = WEEKDAYS.filter((d) => days.includes(d))
    const runs: number[][] = []
    for (const d of sorted) {
      const run = runs[runs.length - 1]
      if (run && run[run.length - 1] === d - 1) run.push(d)
      else runs.push([d])
    }
    return runs
      .map((r) => (r.length > 2 ? `${weekday(r[0])}–${weekday(r[r.length - 1])}` : r.map(weekday).join(', ')))
      .join(', ')
  }
}

/** "Apply to all workplaces" next to a Save button; hidden when there is only one workplace. */
export function ApplyToAll({
  checked,
  onChange,
  others,
  disabled,
}: {
  checked: boolean
  onChange(checked: boolean): void
  /** How many other active workplaces there are. */
  others: number
  disabled?: boolean
}) {
  const { t } = useTranslation()
  if (others < 1) return null
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-stone-800">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-stone-300 accent-brand-600"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {t('attendance.scheduling.applyToAll')}
    </label>
  )
}

/** "Applies from" date (today by default, never the past). */
export function AppliesFrom({
  value,
  min,
  onChange,
  disabled,
}: {
  value: string
  min: string
  onChange(value: string): void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-stone-700">{t('attendance.scheduling.appliesFrom')}</span>
      <input
        type="date"
        className="block w-full rounded-lg border-0 px-3 py-2 text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-brand-500 sm:w-48"
        value={value}
        min={min}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value || min)}
      />
      <span className="mt-1 block text-xs text-stone-500">
        {value === min ? t('attendance.scheduling.fromToday') : t('attendance.scheduling.fromLater')}
      </span>
    </label>
  )
}

/** Add `days` to a YYYY-MM-DD date. */
export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** ISO weekday (Monday = 1) of a YYYY-MM-DD date. */
export function isoWeekday(iso: string): number {
  return ((new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7) + 1
}

/** "Mon–Sat · Morning only 07:30–12:00" / "Every day · Morning 07:00–12:00, Afternoon 13:00–15:00". */
export function useScheduleText() {
  const { t } = useTranslation()
  const weekdaysText = useWeekdaysText()
  return (weekdays: number[], shifts: (ShiftTime & { code: ShiftCode })[]) => {
    const days = weekdays.length === 7 ? t('attendance.employeeSchedules.everyDay') : weekdaysText(weekdays)
    const times =
      shifts.length === 1
        ? t('attendance.employeeSchedules.only', {
            shift: t(`attendance.shiftsShort.${shifts[0].code}`),
            from: shifts[0].start_time,
            to: shifts[0].end_time,
          })
        : shifts.map((s) => `${t(`attendance.shiftsShort.${s.code}`)} ${s.start_time}–${s.end_time}`).join(', ')
    return `${days} · ${times}`
  }
}

function minutes(hm: string): number {
  const [h, m] = hm.split(':').map(Number)
  return h * 60 + m
}

function hm(total: number): string {
  const t = ((total % 1440) + 1440) % 1440
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`
}

/** A shift's windows from its times and the workplace's rules (as the API derives them). */
export function windowsOf(start: string, end: string, rules: AttendanceRules) {
  const s = minutes(start)
  const e = minutes(end)
  return {
    check_in_opens: hm(s - rules.open_before_min),
    check_in_until: hm(s + rules.absent_after_min - 1),
    absent_from: hm(s + rules.absent_after_min),
    check_out_opens: hm(e),
    check_out_until: hm(e + rules.checkout_window_min),
    forgot_from: hm(e + rules.checkout_window_min + 1),
  }
}

/** Scheduling's two tabs: Workplaces and (attendance.scheduling) Employees. */
export function SchedulingTabs() {
  const { t } = useTranslation()
  const canSchedule = usePermission('attendance.scheduling')
  if (!canSchedule) return null
  const tab = ({ isActive }: { isActive: boolean }) =>
    cx(
      'inline-flex min-h-9 items-center justify-center whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500',
      isActive ? 'bg-white text-stone-900 shadow-sm ring-1 ring-stone-200' : 'text-stone-600 hover:text-stone-900',
    )
  return (
    <nav aria-label={t('attendance.scheduling.title')} className="mb-4">
      <div className="grid grid-cols-2 gap-1 rounded-full bg-stone-100 p-1 sm:inline-grid sm:auto-cols-auto sm:grid-flow-col">
        <NavLink to={paths.attendanceScheduling} end className={tab}>
          {t('attendance.employeeSchedules.tabWorkplaces')}
        </NavLink>
        <NavLink to={paths.attendanceSchedulingEmployees} className={tab}>
          {t('attendance.employeeSchedules.tabEmployees')}
        </NavLink>
      </div>
    </nav>
  )
}

/** A compact "HH:MM" input (the shared Input is full width). */
export function TimeInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <span className="w-28 shrink-0">
      <Input type="time" {...props} />
    </span>
  )
}
