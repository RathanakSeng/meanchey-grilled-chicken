import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Icon } from '@/components/icons'
import { Alert, Badge, Button, Card, EmptyState, PageHeader, Spinner } from '@/components/ui'
import { useErrorMessage } from '@/lib/errors'
import { paths } from '@/lib/paths'
import type { Workplace } from '@/lib/types'
import { useShiftName, useWorkplaces } from '@/pages/attendance/api'
import { DeadlineCard } from '@/pages/attendance/requests/DeadlineCard'

/**
 * Settings → Workplaces: every workplace (default first) with its employee count, whether its
 * location is set and its shift times; archived ones behind a toggle (?archived=1). New
 * workplace with attendance.workplace_manage.
 */
export function WorkplacesPage() {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const canManage = usePermission('attendance.workplace_manage')
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const archived = params.get('archived') === '1'
  const workplaces = useWorkplaces(archived)

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={t('attendance.workplaces.title')}
        subtitle={t('attendance.workplaces.subtitle')}
        back={paths.settings}
        actions={
          canManage && (
            <Button onClick={() => navigate(paths.newAttendanceWorkplace)}>
              <Icon name="plus" width={18} height={18} />
              {t('attendance.workplaces.new')}
            </Button>
          )
        }
      />
      <label className="mb-3 flex items-center gap-2 text-sm text-stone-700">
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
          checked={archived}
          onChange={(e) => setParams(e.target.checked ? { archived: '1' } : {}, { replace: true })}
        />
        {t('attendance.workplaces.showArchived')}
      </label>
      {workplaces.isError && <Alert tone="error">{errorMessage(workplaces.error)}</Alert>}
      <Card>
        {workplaces.isLoading ? (
          <div className="flex justify-center py-10 text-brand-600">
            <Spinner />
          </div>
        ) : !workplaces.data?.length ? (
          <EmptyState>{t('attendance.workplaces.empty')}</EmptyState>
        ) : (
          <ul className="-my-2 divide-y divide-stone-100">
            {workplaces.data.map((w) => (
              <WorkplaceRow key={w.id} workplace={w} />
            ))}
          </ul>
        )}
      </Card>
      <div className="mt-4">
        <DeadlineCard />
      </div>
    </div>
  )
}

function WorkplaceRow({ workplace: w }: { workplace: Workplace }) {
  const { t } = useTranslation()
  const shiftName = useShiftName()
  return (
    <li>
      <Link
        to={paths.attendanceWorkplace(w.id)}
        className="-mx-2 flex items-start gap-3 rounded-lg px-2 py-3 hover:bg-stone-50"
      >
        <span className="mt-0.5 text-brand-600">
          <Icon name="mapPin" width={20} height={20} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-stone-900">{w.name}</span>
            {w.is_default && <Badge tone="brand">{t('attendance.workplaces.default')}</Badge>}
            {!w.is_active && <Badge tone="neutral">{t('attendance.workplaces.archived')}</Badge>}
            {w.is_active && !w.has_coordinates && <Badge tone="amber">{t('attendance.workplaces.noLocation')}</Badge>}
          </span>
          {w.address && <span className="block truncate text-sm text-stone-500">{w.address}</span>}
          <span className="mt-1 block text-xs text-stone-500 tabular-nums">
            {t('attendance.workplaces.employees', { count: w.employee_count })}
            {w.schedule.shifts.map((s) => ` · ${shiftName(s.code)} ${s.start_time}–${s.end_time}`).join('')}
          </span>
        </span>
        <Icon name="chevronRight" width={18} height={18} className="mt-1 text-stone-400" />
      </Link>
    </li>
  )
}
