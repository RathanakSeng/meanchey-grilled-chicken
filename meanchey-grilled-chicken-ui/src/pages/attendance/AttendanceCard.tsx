import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Badge, Button } from '@/components/ui'
import { getError, useErrorMessage } from '@/lib/errors'
import { useCalendarNames, useFormatDay } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { AttendanceToday, ShiftDay } from '@/lib/types'
import {
  businessDate,
  clockTime,
  statusTone,
  useAttendanceToday,
  useDayOffText,
  useShiftName,
  useStatusText,
} from './api'

/** Whether `next_action` opens a window later today (the header button then says "opens …"). */
function opensLaterToday(today: AttendanceToday): boolean {
  const na = today.next_action
  return Boolean(
    na.action === 'none' && na.next_action && na.next_opens_at && businessDate(na.next_opens_at, today.timezone) === today.work_date,
  )
}

/**
 * The only attendance action (Home card, My attendance header): **Check in** / **Check out** while that
 * window is open (opens the check screen); otherwise disabled with the upcoming action and
 * *opens 12:30*, *Day off* on a day that isn't tracked, or *Done for today* when nothing else
 * opens today. `next_action` decides.
 */
export function CheckButton({ today }: { today: AttendanceToday }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const na = today.next_action
  const tz = today.timezone
  const formatDay = useFormatDay()
  const label = (action: 'check_in' | 'check_out') => t(`attendance.checkButton.${action}`)
  if (na.action !== 'none') {
    return (
      <Button className="shrink-0 whitespace-nowrap px-3" onClick={() => navigate(paths.attendanceCheck)}>
        <Icon name="mapPin" width={16} height={16} />
        {label(na.action)}
      </Button>
    )
  }
  const later = opensLaterToday(today)
  if (today.starts_on) {
    return (
      <Button disabled className="shrink-0 whitespace-nowrap px-3 py-1.5">
        <Icon name="mapPin" width={16} height={16} />
        <span className="flex flex-col items-start leading-tight">
          <span>{label('check_in')}</span>
          <span className="text-[11px] font-normal">
            {t('attendance.checkButton.starts', { date: formatDay(today.starts_on) })}
          </span>
        </span>
      </Button>
    )
  }
  return (
    // Two short lines (label, then "opens 12:30") keep it narrow enough for the title row.
    <Button disabled className="shrink-0 whitespace-nowrap px-3 py-1.5">
      <Icon name="mapPin" width={16} height={16} />
      <span className="flex flex-col items-start leading-tight">
        <span>{later ? label(na.next_action!) : label('check_in')}</span>
        <span className="text-[11px] font-normal">
          {later
            ? t('attendance.checkButton.opens', { time: clockTime(na.next_opens_at, tz) })
            : today.day_off
              ? t('attendance.checkButton.dayOff')
              : t('attendance.checkButton.done')}
        </span>
      </span>
    </Button>
  )
}

/**
 * A shift's state in one row: name and times; the badge (the open window while it still needs
 * the employee, else the record's status, else the phase) with the window's end under it; the
 * recorded check-in / check-out.
 */
export function ShiftSummary({ shift, timezone }: { shift: ShiftDay; timezone: string }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  const statusText = useStatusText()
  const r = shift.record
  const awaitingCheckIn = shift.phase === 'check_in_open' && !r
  const awaitingCheckOut = shift.phase === 'check_out_open' && !!r?.check_in_at && r.status !== 'absent' && !r.checkout_status
  const open = awaitingCheckIn || awaitingCheckOut
  const recorded: string[] = []
  if (r?.check_in_at) {
    recorded.push(t('attendance.summary.in', { time: clockTime(r.check_in_at, timezone) }))
    // While the badge shows the open window, lateness goes with the check-in time.
    if (open && r.late_minutes) recorded.push(t('attendance.summary.late', { count: r.late_minutes }))
  }
  if (r?.checkout_status === 'forgot_checkout') recorded.push(t('attendance.status.forgot_checkout'))
  else if (r?.check_out_at) recorded.push(t('attendance.summary.out', { time: clockTime(r.check_out_at, timezone) }))
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 py-2">
      <div className="min-w-0">
        <p className="font-medium text-stone-900">{shiftName(shift.code)}</p>
        <p className="text-xs text-stone-500">
          {clockTime(shift.start, timezone)}–{clockTime(shift.end, timezone)}
        </p>
      </div>
      <div className="flex flex-col items-end gap-1 text-right">
        {open ? (
          <Badge tone="brand">{t(`attendance.phase.${shift.phase}`)}</Badge>
        ) : r ? (
          <Badge tone={statusTone(r)}>{statusText(r)}</Badge>
        ) : (
          <Badge>{t(`attendance.phase.${shift.phase}`)}</Badge>
        )}
        {awaitingCheckIn && (
          <span className="text-xs font-medium text-brand-700">
            {t('attendance.summary.until', { time: clockTime(shift.check_in_until, timezone) })}
          </span>
        )}
        {awaitingCheckOut && (
          <span className="text-xs font-medium text-brand-700">
            {t('attendance.summary.checkOutUntil', { time: clockTime(shift.check_out_until, timezone) })}
          </span>
        )}
        {recorded.length > 0 && <span className="text-xs text-stone-500">{recorded.join(' · ')}</span>}
      </div>
    </div>
  )
}

/** "Today is a holiday: Pchum Ben" / "Today is a day off", with when attendance resumes. */
export function DayOffNotice({ today }: { today: AttendanceToday }) {
  const { t } = useTranslation()
  const dayOffText = useDayOffText()
  const names = useCalendarNames()
  const off = today.day_off
  if (!off) return null
  const next = today.next_action.next_opens_at
  return (
    <div className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-950 ring-1 ring-amber-300">
      <p className="font-medium">{t('attendance.dayOff.today', { what: dayOffText(off) })}</p>
      {next && (
        <p className="text-xs text-amber-900">
          {t('attendance.dayOff.resumes', { date: names.day(businessDate(next, today.timezone)), time: clockTime(next, today.timezone) })}
        </p>
      )}
    </div>
  )
}

/** "Your attendance starts on 20 Oct 2026" (before the start date), or "Attendance isn't
 *  required for you" (a supervisor switched off). Null when attendance applies today. */
export function TrackingNotice({ today }: { today: AttendanceToday }) {
  const { t } = useTranslation()
  const formatDay = useFormatDay()
  if (today.starts_on) {
    return (
      <div className="rounded-xl bg-sky-50 px-3 py-2 text-sm font-medium text-sky-950 ring-1 ring-sky-200">
        {t('attendance.tracking.startsOn', { date: formatDay(today.starts_on) })}
      </div>
    )
  }
  if (!today.tracked) {
    return (
      <div className="rounded-xl bg-stone-50 px-3 py-2 text-sm text-stone-700 ring-1 ring-stone-200">
        {t('attendance.tracking.notRequired')}
      </div>
    )
  }
  return null
}

/** Home: the first card for tracked employees: the header button and today's two shifts (or
 *  the day off). */
export function AttendanceHomeCard() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const today = useAttendanceToday()
  const data = today.data
  return (
    <section className="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-stone-200 sm:p-5">
      {/* One row: the title and the compact button at the right (the card's only action). */}
      <header className="mb-2 flex items-center justify-between gap-2">
        <h2 className="flex min-w-0 flex-1 items-center gap-2 text-base font-semibold text-stone-900">
          <Icon name="clock" className="shrink-0 text-brand-600" />
          {t('nav.attendance')}
        </h2>
        {data && <CheckButton today={data} />}
      </header>
      {today.isLoading ? (
        <div className="h-16 animate-pulse rounded-xl bg-stone-100" />
      ) : data && (data.starts_on || !data.tracked) ? (
        <TrackingNotice today={data} />
      ) : data?.day_off ? (
        <DayOffNotice today={data} />
      ) : data ? (
        <div className="divide-y divide-stone-100">
          {data.shifts.map((s) => (
            <ShiftSummary key={s.code} shift={s} timezone={data.timezone} />
          ))}
        </div>
      ) : (
        <p className="text-sm text-red-700" role="alert">
          {getError(today.error).code === 'ATTENDANCE_NOT_REQUIRED'
            ? t('attendance.notRequired')
            : errorMessage(today.error)}
        </p>
      )}
    </section>
  )
}
