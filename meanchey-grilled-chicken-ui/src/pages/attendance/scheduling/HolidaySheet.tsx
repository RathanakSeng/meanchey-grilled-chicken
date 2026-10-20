import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, ConfirmDialog, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import type { Holiday, HolidayInput, HolidayWriteResult, WorkplaceOption } from '@/lib/types'
import { invalidateScheduling } from '../api'
import { addDays, ApplyToAll } from './shared'

const MAX_DAYS = 31

interface HolidaySheetProps {
  /** Editing this holiday, else a new one starting on `date`. */
  holiday: Holiday | null
  date: string
  today: string
  /** The page's workplace: a new holiday is for it alone unless "Apply to all workplaces". */
  workplace: WorkplaceOption
  workplaceOptions: WorkplaceOption[]
  onClose(): void
  onDone(message: string): void
}

function daysBetween(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1
}

/**
 * Add or edit a holiday: names (km / en), From / To (whole days, at most 31), note and "Apply to
 * all workplaces" (later ones too). Unticked, a new holiday or one that was for all becomes this
 * workplace's only; one already shared by a few workplaces keeps them ("Also at: …"). A holiday covering today or earlier
 * removes the attendance already recorded on those days (corrected records are kept), so saving
 * one asks first.
 */
export function HolidaySheet({ holiday, date, today, workplace, workplaceOptions, onClose, onDone }: HolidaySheetProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const [form, setForm] = useState<HolidayInput>(() =>
    holiday
      ? {
          name_km: holiday.name_km,
          name_en: holiday.name_en,
          start_date: holiday.start_date,
          end_date: holiday.end_date,
          scope: holiday.scope,
          workplace_ids: holiday.workplaces.map((w) => w.id),
          note: holiday.note,
        }
      : {
          name_km: '',
          name_en: '',
          start_date: date,
          end_date: date,
          scope: 'selected',
          workplace_ids: [workplace.id],
          note: null,
        },
  )
  const [confirm, setConfirm] = useState<'save' | 'delete' | null>(null)

  const done = (result: HolidayWriteResult, key: 'saved' | 'deleted') => {
    invalidateScheduling(queryClient)
    const parts = [t(`attendance.scheduling.holiday.${key}`)]
    if (result.records_removed) parts.push(t('attendance.scheduling.recordsRemoved', { count: result.records_removed }))
    if (result.skipped_locked) parts.push(t('attendance.scheduling.skippedLocked', { count: result.skipped_locked }))
    if (result.absents_recreated) parts.push(t('attendance.scheduling.absentsRecreated', { count: result.absents_recreated }))
    onDone(parts.join(' '))
  }

  const save = useMutation({
    mutationFn: async (body: HolidayInput) =>
      (holiday
        ? await api.patch<HolidayWriteResult>(`/attendance/holidays/${holiday.id}`, body)
        : await api.post<HolidayWriteResult>('/attendance/holidays', body)
      ).data,
    onSuccess: (result) => done(result, 'saved'),
  })
  const remove = useMutation({
    mutationFn: async () => (await api.delete<HolidayWriteResult>(`/attendance/holidays/${holiday!.id}`)).data,
    onSuccess: (result) => done(result, 'deleted'),
  })

  const update = (patch: Partial<HolidayInput>) => {
    save.reset()
    setForm((f) => ({ ...f, ...patch }))
  }
  const length = form.end_date >= form.start_date ? daysBetween(form.start_date, form.end_date) : 0
  const tooLong = length > MAX_DAYS
  const valid = form.name_km.trim() && form.name_en.trim() && length > 0 && !tooLong
  // Unticking "all" keeps a holiday's own workplaces when it had several, else just this one.
  const ownIds = holiday?.scope === 'selected' && holiday.workplaces.length ? holiday.workplaces.map((w) => w.id) : [workplace.id]
  const alsoAt = form.scope === 'selected'
    ? workplaceOptions.filter((w) => w.id !== workplace.id && form.workplace_ids?.includes(w.id))
    : []
  const body = (): HolidayInput => ({
    ...form,
    note: form.note?.trim() || null,
    workplace_ids: form.scope === 'selected' ? form.workplace_ids : undefined,
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    if (form.start_date <= today) setConfirm('save')
    else save.mutate(body())
  }
  const busy = save.isPending || remove.isPending

  return (
    <Sheet
      open
      busy={busy}
      title={holiday ? t('attendance.scheduling.holiday.edit') : t('attendance.scheduling.holiday.add')}
      onClose={onClose}
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          {holiday ? (
            <Button variant="ghost" className="text-red-700" disabled={busy} onClick={() => setConfirm('delete')}>
              {t('attendance.scheduling.delete')}
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" form="holiday-form" loading={save.isPending && !confirm} disabled={!valid}>
              {t('common.save')}
            </Button>
          </div>
        </div>
      }
    >
      <form id="holiday-form" onSubmit={submit} className="space-y-4">
        <Field label={t('attendance.scheduling.holiday.nameKm')}>
          {(id) => <Input id={id} value={form.name_km} maxLength={100} onChange={(e) => update({ name_km: e.target.value })} />}
        </Field>
        <Field label={t('attendance.scheduling.holiday.nameEn')}>
          {(id) => <Input id={id} value={form.name_en} maxLength={100} onChange={(e) => update({ name_en: e.target.value })} />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('attendance.scheduling.holiday.from')}>
            {(id) => (
              <Input
                id={id}
                type="date"
                value={form.start_date}
                onChange={(e) => {
                  const start = e.target.value
                  if (!start) return
                  // Keep the length when moving the start; never end before it.
                  const end = form.end_date < start ? start : form.end_date
                  update({ start_date: start, end_date: end })
                }}
              />
            )}
          </Field>
          <Field label={t('attendance.scheduling.holiday.to')}>
            {(id) => (
              <Input
                id={id}
                type="date"
                value={form.end_date}
                min={form.start_date}
                max={addDays(form.start_date, MAX_DAYS - 1)}
                onChange={(e) => e.target.value && update({ end_date: e.target.value })}
              />
            )}
          </Field>
        </div>
        <p className={tooLong ? 'text-sm text-red-700' : 'text-sm text-stone-600'}>
          {tooLong
            ? t('attendance.scheduling.holiday.tooLong', { max: MAX_DAYS })
            : t('attendance.scheduling.days', { count: length })}
        </p>

        <div className="space-y-1">
          <ApplyToAll
            checked={form.scope === 'all'}
            others={workplaceOptions.length - 1}
            onChange={(on) => update(on ? { scope: 'all' } : { scope: 'selected', workplace_ids: ownIds })}
          />
          {form.scope === 'all' && (
            <p className="pl-6 text-sm text-stone-500">
              {holiday?.scope === 'all'
                ? t('attendance.scheduling.holiday.shared')
                : t('attendance.scheduling.holiday.allHint')}
            </p>
          )}
          {alsoAt.length > 0 && (
            <p className="text-sm text-stone-600">
              {t('attendance.scheduling.holiday.alsoAt', { names: alsoAt.map((w) => w.name).join(', ') })}
            </p>
          )}
        </div>

        <Field label={t('attendance.scheduling.holiday.note')}>
          {(id) => (
            <Input id={id} value={form.note ?? ''} maxLength={500} onChange={(e) => update({ note: e.target.value })} />
          )}
        </Field>
        {form.start_date <= today && <Alert tone="warning">{t('attendance.scheduling.holiday.pastWarning')}</Alert>}
        {save.isError && !confirm && <Alert tone="error">{errorMessage(save.error)}</Alert>}
      </form>

      {confirm === 'save' && (
        <ConfirmDialog
          open
          tone="danger"
          title={t('attendance.scheduling.holiday.confirmTitle')}
          body={t('attendance.scheduling.holiday.pastWarning')}
          confirmLabel={t('common.save')}
          loading={save.isPending}
          error={save.isError ? errorMessage(save.error) : null}
          onConfirm={() => save.mutate(body())}
          onClose={() => {
            setConfirm(null)
            save.reset()
          }}
        />
      )}
      {confirm === 'delete' && holiday && (
        <DeleteHolidayDialog
          holiday={holiday}
          today={today}
          loading={remove.isPending}
          error={remove.isError ? errorMessage(remove.error) : null}
          onConfirm={() => remove.mutate()}
          onClose={() => {
            setConfirm(null)
            remove.reset()
          }}
        />
      )}
    </Sheet>
  )
}

export function DeleteHolidayDialog({
  holiday,
  today,
  loading,
  error,
  onConfirm,
  onClose,
}: {
  holiday: Holiday
  today: string
  loading: boolean
  error: string | null
  onConfirm(): void
  onClose(): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const body = [
    holiday.start_date <= today
      ? t('attendance.scheduling.holiday.deletePast', { name: localized(holiday) })
      : t('attendance.scheduling.holiday.deleteConfirm', { name: localized(holiday) }),
    holiday.scope === 'all'
      ? t('attendance.scheduling.holiday.deleteAll')
      : holiday.workplaces.length > 1
        ? t('attendance.scheduling.holiday.deleteSeveral', { names: holiday.workplaces.map((w) => w.name).join(', ') })
        : null,
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <ConfirmDialog
      open
      tone="danger"
      title={t('attendance.scheduling.holiday.deleteTitle')}
      body={body}
      confirmLabel={t('attendance.scheduling.delete')}
      loading={loading}
      error={error}
      onConfirm={onConfirm}
      onClose={onClose}
    />
  )
}
