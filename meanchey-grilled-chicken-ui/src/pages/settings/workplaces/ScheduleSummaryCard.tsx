import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Card } from '@/components/ui'
import { paths } from '@/lib/paths'
import type { Workplace } from '@/lib/types'
import { useShiftName } from '@/pages/attendance/api'
import { useDayName, useWeekdayName, WEEKDAYS } from '@/pages/attendance/scheduling/shared'

/**
 * A workplace's current schedule, read-only: tracked weekdays, both shifts with their windows
 * and the rules. Edited in Attendance → Scheduling (the link opens this workplace's).
 */
export function ScheduleSummaryCard({ workplace: w }: { workplace: Workplace }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  const weekday = useWeekdayName()
  const formatDay = useDayName()
  const canSchedule = usePermission('attendance.scheduling')
  const canView = usePermission('attendance.view')
  const s = w.schedule
  const tracked = WEEKDAYS.filter((d) => s.weekdays.includes(d))
  const link = w.is_active && (canSchedule || canView) && (
    <Link
      to={paths.attendanceSchedulingFor(w.id)}
      className="text-sm font-medium text-brand-700 hover:underline"
    >
      {canSchedule ? t('attendance.workplace.editInScheduling') : t('attendance.workplace.viewInScheduling')}
    </Link>
  )
  const yesNo = (on: boolean) => (on ? t('common.yes') : t('common.no'))
  return (
    <Card title={t('attendance.workplace.schedule')} actions={link}>
      <div className="space-y-4 text-sm">
        <p className="text-stone-600">{t('attendance.workplace.scheduleSince', { date: formatDay(s.effective_from) })}</p>
        <div>
          <p className="font-medium text-stone-900">{t('attendance.scheduling.weekdays.title')}</p>
          <p className="text-stone-700">{tracked.map(weekday).join(', ')}</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {s.shifts.map((x) => (
            <div key={x.code} className="rounded-lg p-3 ring-1 ring-stone-200">
              <p className="font-semibold text-stone-800">
                {shiftName(x.code)} <span className="font-normal tabular-nums">{x.start_time}–{x.end_time}</span>
              </p>
              <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-stone-500">{t('attendance.shiftsPage.checkInWindow')}</dt>
                <dd className="font-medium tabular-nums">
                  {x.windows.check_in_opens}–{x.windows.check_in_until}
                </dd>
                <dt className="text-stone-500">{t('attendance.shiftsPage.absentFrom')}</dt>
                <dd className="font-medium tabular-nums">{x.windows.absent_from}</dd>
                <dt className="text-stone-500">{t('attendance.shiftsPage.checkOutWindow')}</dt>
                <dd className="font-medium tabular-nums">
                  {x.windows.check_out_opens}–{x.windows.check_out_until}
                </dd>
                <dt className="text-stone-500">{t('attendance.shiftsPage.forgotFrom')}</dt>
                <dd className="font-medium tabular-nums">{x.windows.forgot_from}</dd>
              </dl>
            </div>
          ))}
        </div>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4">
          <dt className="text-stone-500">{t('attendance.shiftsPage.reminders')}</dt>
          <dd className="font-medium">{yesNo(s.reminders_enabled)}</dd>
          <dt className="text-stone-500">{t('attendance.shiftsPage.countEarly')}</dt>
          <dd className="font-medium">{yesNo(s.count_early_checkin)}</dd>
          <dt className="text-stone-500">{t('attendance.shiftsPage.countOvertime')}</dt>
          <dd className="font-medium">{yesNo(s.count_overtime)}</dd>
        </dl>
      </div>
    </Card>
  )
}
