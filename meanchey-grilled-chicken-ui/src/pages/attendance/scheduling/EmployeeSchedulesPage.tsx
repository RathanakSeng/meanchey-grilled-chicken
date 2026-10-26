import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Alert, Badge, Button, ConfirmDialog, Input, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { paths } from '@/lib/paths'
import type { EmployeeScheduleRow, EmployeeScheduleWriteResult } from '@/lib/types'
import { invalidateScheduling, useEmployeeSchedules } from '../api'
import { EmployeeScheduleSheet } from './EmployeeScheduleSheet'
import { SchedulingTabs, useDayName, useScheduleText } from './shared'

/**
 * Scheduling → Employees (attendance.scheduling): tracked employees in scope with their schedule
 * today ("Mon–Sat · Morning only 07:30–12:00"), a Custom badge when some of it is their own and
 * "Changes on …" when a version is planned. Filters: workplace, Custom only, search. Select
 * several for Edit schedule / Reset to workplace; tap one to edit it (`?employee=id`).
 */
export function EmployeeSchedulesPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState('')
  const [workplaceId, setWorkplaceId] = useState('')
  const [customOnly, setCustomOnly] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [bulk, setBulk] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const list = useEmployeeSchedules({ workplaceIds: workplaceId ? [workplaceId] : [], customOnly, q })
  const rows = list.data?.items ?? []
  const today = list.data?.today ?? ''
  const single = params.get('employee')

  const reset = useMutation({
    mutationFn: async (userIds: string[]) =>
      (await api.post<EmployeeScheduleWriteResult>('/attendance/scheduling/employees/reset', { user_ids: userIds })).data,
    onSuccess: (result) => {
      invalidateScheduling(queryClient)
      setConfirmReset(false)
      setSelected([])
      setMessage(t('attendance.employeeSchedules.resetDone', { count: result.changed.length }))
    },
  })

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const allShown = rows.length > 0 && rows.every((r) => selected.includes(r.user.id!))
  const editRows = bulk ? rows.filter((r) => selected.includes(r.user.id!)) : rows.filter((r) => r.user.id! === single)
  const closeSheet = () => {
    setBulk(false)
    if (single) {
      params.delete('employee')
      setParams(params, { replace: true })
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 pb-24">
      <PageHeader
        title={t('attendance.scheduling.title')}
        subtitle={t('attendance.employeeSchedules.subtitle')}
        back={paths.attendance}
      />
      <SchedulingTabs />
      {message && (
        <Alert tone="success">
          <span className="flex items-start justify-between gap-2">
            {message}
            <button type="button" onClick={() => setMessage(null)} aria-label={t('common.close')}>
              <Icon name="close" width={16} height={16} />
            </button>
          </span>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1 basis-56">
          <Input
            type="search"
            value={q}
            placeholder={t('attendance.employeeSchedules.search')}
            aria-label={t('attendance.employeeSchedules.search')}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {(list.data?.workplace_options.length ?? 0) > 1 && (
          <Select
            className="w-auto"
            value={workplaceId}
            aria-label={t('attendance.employeeSchedules.workplace')}
            onChange={(e) => setWorkplaceId(e.target.value)}
          >
            <option value="">{t('attendance.scheduling.allWorkplaces')}</option>
            {list.data?.workplace_options.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </Select>
        )}
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-stone-800">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-stone-300 accent-brand-600"
            checked={customOnly}
            onChange={(e) => setCustomOnly(e.target.checked)}
          />
          {t('attendance.employeeSchedules.customOnly')}
        </label>
      </div>

      {list.isError && <Alert tone="error">{errorMessage(list.error)}</Alert>}
      {!list.data ? (
        !list.isError && (
          <div className="flex justify-center py-16 text-brand-600">
            <Spinner />
          </div>
        )
      ) : rows.length === 0 ? (
        <p className="rounded-xl bg-white p-6 text-center text-sm text-stone-500 ring-1 ring-stone-200">
          {t('attendance.employeeSchedules.none')}
        </p>
      ) : (
        <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-stone-200">
          <label className="flex cursor-pointer items-center gap-3 border-b border-stone-100 px-4 py-2 text-sm text-stone-600">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-stone-300 accent-brand-600"
              checked={allShown}
              onChange={(e) => setSelected(e.target.checked ? rows.map((r) => r.user.id!) : [])}
            />
            {t('attendance.employeeSchedules.selectAll', { count: rows.length })}
          </label>
          <ul className="divide-y divide-stone-100">
            {rows.map((row) => (
              <EmployeeRow
                key={row.user.id!}
                row={row}
                checked={selected.includes(row.user.id!)}
                onToggle={() => toggle(row.user.id!)}
                onOpen={() => {
                  params.set('employee', row.user.id!)
                  setParams(params, { replace: true })
                }}
              />
            ))}
          </ul>
        </div>
      )}

      {selected.length > 0 && (
        <div className="fixed inset-x-0 bottom-16 z-30 px-4 sm:bottom-4">
          <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-2 rounded-xl bg-stone-900 px-4 py-3 text-white shadow-lg">
            <span className="mr-auto text-sm font-medium">
              {t('attendance.employeeSchedules.selected', { count: selected.length })}
            </span>
            <Button variant="secondary" onClick={() => setSelected([])}>
              {t('attendance.employeeSchedules.clear')}
            </Button>
            <Button variant="secondary" onClick={() => setConfirmReset(true)}>
              {t('attendance.employeeSchedules.reset')}
            </Button>
            <Button onClick={() => setBulk(true)}>{t('attendance.employeeSchedules.edit')}</Button>
          </div>
        </div>
      )}

      {(bulk || single) && editRows.length > 0 && today && (
        <EmployeeScheduleSheet
          rows={editRows}
          today={today}
          onClose={closeSheet}
          onDone={(text) => {
            closeSheet()
            if (bulk) setSelected([])
            setMessage(text)
          }}
        />
      )}
      {confirmReset && (
        <ConfirmDialog
          open
          title={t('attendance.employeeSchedules.resetTitle')}
          body={t('attendance.employeeSchedules.resetBody', { count: selected.length })}
          confirmLabel={t('attendance.employeeSchedules.reset')}
          loading={reset.isPending}
          error={reset.isError ? errorMessage(reset.error) : null}
          onConfirm={() => reset.mutate(selected)}
          onClose={() => {
            setConfirmReset(false)
            reset.reset()
          }}
        />
      )}
    </div>
  )
}

function EmployeeRow({
  row,
  checked,
  onToggle,
  onOpen,
}: {
  row: EmployeeScheduleRow
  checked: boolean
  onToggle(): void
  onOpen(): void
}) {
  const { t } = useTranslation()
  const scheduleText = useScheduleText()
  const dayName = useDayName()
  const custom = row.summary.custom.length > 0
  return (
    <li className={cx('flex items-start gap-3 px-4 py-3', checked && 'bg-brand-50/50')}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 shrink-0 rounded border-stone-300 accent-brand-600"
        checked={checked}
        aria-label={row.user.full_name}
        onChange={onToggle}
      />
      <button type="button" onClick={onOpen} className="group min-w-0 flex-1 text-left">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-stone-900 group-hover:underline">{row.user.full_name}</span>
          {row.role === 'supervisor' && <Badge tone="blue">{t('roles.supervisor')}</Badge>}
          {custom && <Badge tone="brand">{t('attendance.employeeSchedules.custom')}</Badge>}
        </span>
        <span className="block text-xs text-stone-500">
          {[row.position, row.workplace?.name].filter(Boolean).join(' · ')}
        </span>
        <span className="mt-0.5 block text-sm tabular-nums text-stone-700">
          {scheduleText(row.summary.weekdays, row.summary.shifts)}
        </span>
        {row.next_change && (
          <span className="block text-xs font-medium text-amber-800">
            {t('attendance.employeeSchedules.changesOn', { date: dayName(row.next_change) })}
          </span>
        )}
      </button>
      <Icon name="chevronRight" width={18} height={18} className="mt-1 shrink-0 text-stone-400" />
    </li>
  )
}
