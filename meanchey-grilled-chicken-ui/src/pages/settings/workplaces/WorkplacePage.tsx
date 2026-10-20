import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { Alert, Badge, Button, Card, ConfirmDialog, EmptyState, PageHeader, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import type { Workplace } from '@/lib/types'
import { invalidateWorkplaces, useWorkplace, useWorkplaces } from '@/pages/attendance/api'
import { LocationCard } from './LocationCard'
import { ScheduleSummaryCard } from './ScheduleSummaryCard'

/**
 * Settings → Workplaces → one workplace: Location (edited with workplace_update; Make default,
 * Delete / archive and Restore with workplace_manage), its current schedule (read-only, with **Edit in Scheduling**) and
 * the employees assigned. Without an id (`/new`): the Location form only; the schedule is copied
 * from the default workplace's current one.
 */
export function WorkplacePage() {
  const { id } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const canManage = usePermission('attendance.workplace_manage')
  const canUpdate = usePermission('attendance.workplace_update')
  const query = useWorkplace(id)
  const active = useWorkplaces(false)
  const fallback = active.data?.find((w) => w.is_default && w.has_coordinates)
  const fallbackCenter =
    fallback && fallback.latitude !== null && fallback.longitude !== null
      ? { latitude: fallback.latitude, longitude: fallback.longitude }
      : undefined

  if (!id) {
    return (
      <div className="mx-auto max-w-3xl space-y-4">
        <PageHeader title={t('attendance.workplaces.new')} back={paths.attendanceWorkplaces} />
        <Alert tone="info">{t('attendance.workplaces.newHint')}</Alert>
        <LocationCard
          workplace={null}
          canEdit={canManage}
          fallbackCenter={fallbackCenter}
          onSaved={(w) => navigate(paths.attendanceWorkplace(w.id), { replace: true })}
        />
      </div>
    )
  }

  const w = query.data
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <PageHeader
        title={w?.name ?? t('attendance.workplaces.title')}
        subtitle={
          w && (
            <span className="flex flex-wrap items-center gap-2">
              {w.is_default && <Badge tone="brand">{t('attendance.workplaces.default')}</Badge>}
              {!w.is_active && <Badge tone="neutral">{t('attendance.workplaces.archived')}</Badge>}
              {w.updated_by && (
                <span>
                  {t('attendance.updatedBy', {
                    name: w.updated_by.is_system ? t('roles.superadmin') : w.updated_by.full_name,
                    time: formatDate(w.updated_at),
                  })}
                </span>
              )}
            </span>
          )
        }
        back={paths.attendanceWorkplaces}
      />
      {query.isError && <Alert tone="error">{errorMessage(query.error)}</Alert>}
      {!w ? (
        !query.isError && (
          <div className="flex justify-center py-16 text-brand-600">
            <Spinner />
          </div>
        )
      ) : (
        <>
          {!w.is_active && <ArchivedNotice workplace={w} canManage={canManage} />}
          <LocationCard
            workplace={w}
            canEdit={canUpdate && w.is_active}
            fallbackCenter={fallbackCenter}
            actions={canManage && w.is_active && <LocationActions workplace={w} />}
          />
          <ScheduleSummaryCard workplace={w} />
          <EmployeesCard workplace={w} />
        </>
      )}
    </div>
  )
}

/** Make default and Delete (archive when it has history), with why Delete is blocked. */
function LocationActions({ workplace: w }: { workplace: Workplace }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const [confirm, setConfirm] = useState<'default' | 'delete' | null>(null)

  const makeDefault = useMutation({
    mutationFn: async () => (await api.patch<Workplace>(`/attendance/workplaces/${w.id}`, { is_default: true })).data,
    onSuccess: (next) => {
      invalidateWorkplaces(queryClient, next)
      setConfirm(null)
    },
  })
  const remove = useMutation({
    mutationFn: async () =>
      (await api.delete<{ result: 'archived' | 'deleted' }>(`/attendance/workplaces/${w.id}`)).data,
    onSuccess: () => {
      invalidateWorkplaces(queryClient)
      navigate(paths.attendanceWorkplaces, { replace: true })
    },
  })

  if (w.is_default) {
    return <p className="mr-auto text-xs text-stone-500">{t('attendance.workplaces.defaultNoDelete')}</p>
  }
  const blocked = w.employee_count > 0
  return (
    <>
      {blocked && (
        <p className="mr-auto text-xs text-stone-500">
          {t('attendance.workplaces.inUse', { count: w.employee_count })}{' '}
          <Link to={`${paths.users}?workplace=${w.id}`} className="font-medium text-brand-700 hover:underline">
            {t('attendance.workplaces.seeEmployees')}
          </Link>
        </p>
      )}
      <Button variant="secondary" disabled={blocked} onClick={() => setConfirm('delete')}>
        {w.has_history ? t('attendance.workplaces.archive') : t('attendance.workplaces.delete')}
      </Button>
      <Button
        variant="secondary"
        disabled={!w.has_coordinates}
        title={w.has_coordinates ? undefined : t('attendance.workplaces.defaultNeedsLocation')}
        onClick={() => setConfirm('default')}
      >
        {t('attendance.workplaces.makeDefault')}
      </Button>
      {confirm === 'default' && (
        <ConfirmDialog
          open
          title={t('attendance.workplaces.makeDefault')}
          body={t('attendance.workplaces.makeDefaultConfirm', { name: w.name })}
          confirmLabel={t('attendance.workplaces.makeDefault')}
          loading={makeDefault.isPending}
          error={makeDefault.isError ? errorMessage(makeDefault.error) : null}
          onConfirm={() => makeDefault.mutate()}
          onClose={() => {
            setConfirm(null)
            makeDefault.reset()
          }}
        />
      )}
      {confirm === 'delete' && (
        <ConfirmDialog
          open
          tone="danger"
          title={w.has_history ? t('attendance.workplaces.archiveTitle') : t('attendance.workplaces.deleteTitle')}
          body={
            w.has_history
              ? t('attendance.workplaces.archiveConfirm', { name: w.name })
              : t('attendance.workplaces.deleteConfirm', { name: w.name })
          }
          confirmLabel={w.has_history ? t('attendance.workplaces.archive') : t('attendance.workplaces.delete')}
          loading={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => remove.mutate()}
          onClose={() => {
            setConfirm(null)
            remove.reset()
          }}
        />
      )}
    </>
  )
}

function ArchivedNotice({ workplace: w, canManage }: { workplace: Workplace; canManage: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const restore = useMutation({
    mutationFn: async () => (await api.post<Workplace>(`/attendance/workplaces/${w.id}/restore`)).data,
    onSuccess: (next) => invalidateWorkplaces(queryClient, next),
  })
  return (
    <Alert tone="warning">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>{t('attendance.workplaces.archivedNotice')}</span>
        {canManage && (
          <Button variant="secondary" loading={restore.isPending} onClick={() => restore.mutate()}>
            {t('attendance.workplaces.restore')}
          </Button>
        )}
      </div>
      {restore.isError && <p className="mt-2">{errorMessage(restore.error)}</p>}
    </Alert>
  )
}

function EmployeesCard({ workplace: w }: { workplace: Workplace }) {
  const { t } = useTranslation()
  const canViewUsers = usePermission('users.view')
  const employees = w.employees ?? []
  return (
    <Card title={t('attendance.workplace.employees', { count: employees.length })}>
      {employees.length === 0 ? (
        <EmptyState>{t('attendance.workplace.noEmployees')}</EmptyState>
      ) : (
        <ul className="-my-2 divide-y divide-stone-100">
          {employees.map((e) => {
            const label = (
              <>
                <span className="font-medium text-stone-900">{e.user.full_name}</span>
                <span className="block text-xs text-stone-500">
                  {t(`roles.${e.role}`)}
                  {e.position ? ` · ${e.position}` : ''}
                </span>
              </>
            )
            return (
              <li key={e.user.id ?? e.user.full_name} className="py-2">
                {canViewUsers && e.user.id ? (
                  <Link to={paths.user(e.user.id)} className="block hover:underline">
                    {label}
                  </Link>
                ) : (
                  label
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
