import { useTranslation } from 'react-i18next'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Alert, Badge, PageHeader, Spinner } from '@/components/ui'
import { useErrorMessage } from '@/lib/errors'
import { paths } from '@/lib/paths'
import type { SchedulingWorkplace } from '@/lib/types'
import { useScheduling, useShiftName } from '../api'
import { SchedulingTabs, useDayName, useWeekdaysText } from './shared'

/**
 * Attendance → Scheduling (កាលវិភាគ): a card per active workplace (default first) with its
 * tracked days, shift times and the next planned change; a card opens that workplace's
 * scheduling. Viewing needs attendance.view or attendance.scheduling.
 */
export function SchedulingListPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const [params] = useSearchParams()
  const scheduling = useScheduling([])

  // Old links (`?w=id`) open that workplace.
  const legacy = (params.get('w') ?? '').split(',').filter(Boolean)
  if (legacy.length === 1) return <Navigate to={paths.attendanceSchedulingFor(legacy[0])} replace />

  const workplaces = scheduling.data?.workplaces ?? []
  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <PageHeader
        title={t('attendance.scheduling.title')}
        subtitle={t('attendance.scheduling.subtitle')}
        back={paths.attendance}
      />
      <SchedulingTabs />
      {scheduling.isError && <Alert tone="error">{errorMessage(scheduling.error)}</Alert>}
      {!scheduling.data ? (
        !scheduling.isError && (
          <div className="flex justify-center py-16 text-brand-600">
            <Spinner />
          </div>
        )
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {workplaces.map((w) => (
            <WorkplaceCard key={w.id} workplace={w} />
          ))}
        </ul>
      )}
    </div>
  )
}

function WorkplaceCard({ workplace: w }: { workplace: SchedulingWorkplace }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  const weekdaysText = useWeekdaysText()
  const formatDay = useDayName()
  const next = w.upcoming[0]
  return (
    <li>
      <Link
        to={paths.attendanceSchedulingFor(w.id)}
        className="group flex h-full items-start gap-3 rounded-2xl bg-white p-4 shadow-sm ring-1 ring-stone-200 transition hover:ring-brand-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
      >
        <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <Icon name="calendar" width={20} height={20} />
        </span>
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-stone-900">{w.name}</span>
            {w.is_default && <Badge tone="brand">{t('attendance.workplaces.default')}</Badge>}
          </span>
          <span className="block text-sm text-stone-700">{weekdaysText(w.current.weekdays)}</span>
          {w.current.shifts.map((s) => (
            <span key={s.code} className="block text-xs text-stone-500 tabular-nums">
              {shiftName(s.code)} {s.start_time}–{s.end_time}
            </span>
          ))}
          {next && (
            <span className="block text-xs font-medium text-amber-800">
              {t('attendance.scheduling.upcomingFrom', { date: formatDay(next.effective_from) })}
            </span>
          )}
        </span>
        <Icon
          name="chevronRight"
          width={18}
          height={18}
          className="mt-1 shrink-0 text-stone-400 transition group-hover:translate-x-0.5 group-hover:text-brand-600"
        />
      </Link>
    </li>
  )
}
