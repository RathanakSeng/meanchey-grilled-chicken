import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, Card, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, useErrorMessage } from '@/lib/errors'
import type { Workplace } from '@/lib/types'
import { invalidateWorkplaces } from '@/pages/attendance/api'
import { MapView, type MapPoint } from '@/pages/attendance/MapView'

const RADIUS_MIN = 10
const RADIUS_MAX = 5000
const SLIDER_MAX = 1000
const DEFAULT_RADIUS = 100

interface Form {
  name: string
  address: string
  latitude: string
  longitude: string
  radius: number
}

function toForm(w: Workplace | null): Form {
  return {
    name: w?.name ?? '',
    address: w?.address ?? '',
    latitude: w?.latitude == null ? '' : String(w.latitude),
    longitude: w?.longitude == null ? '' : String(w.longitude),
    radius: w?.radius_m ?? DEFAULT_RADIUS,
  }
}

function coordinate(value: string, limit: number): number | null {
  const n = Number(value.replace(',', '.'))
  return value.trim() !== '' && Number.isFinite(n) && Math.abs(n) <= limit ? n : null
}

interface LocationCardProps {
  /** null: a new workplace (POST); its schedule is copied from the default one. */
  workplace: Workplace | null
  canEdit: boolean
  /** Where to look when there is no pin yet (e.g. the default workplace). */
  fallbackCenter?: MapPoint
  onSaved?(workplace: Workplace): void
  /** Extra buttons next to Save (Make default, Delete). */
  actions?: ReactNode
}

/**
 * A workplace's location: name, address, the pin (tap the map, or type latitude / longitude)
 * and the check-in radius. Read-only without attendance.workplace_update (a new one needs
 * attendance.workplace_manage).
 */
export function LocationCard({ workplace, canEdit, fallbackCenter, onSaved, actions }: LocationCardProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const [form, setForm] = useState<Form>(() => toForm(workplace))
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (workplace) setForm(toForm(workplace))
  }, [workplace])

  const lat = coordinate(form.latitude, 90)
  const lng = coordinate(form.longitude, 180)
  const pin = useMemo(
    () => (lat !== null && lng !== null ? { latitude: lat, longitude: lng, radius: form.radius } : null),
    [lat, lng, form.radius],
  )

  const save = useMutation({
    mutationFn: async () => {
      if (!form.name.trim()) throw new ClientError('NAME_REQUIRED')
      const hasLat = form.latitude.trim() !== ''
      const hasLng = form.longitude.trim() !== ''
      if (hasLat !== hasLng || (hasLat && (lat === null || lng === null))) {
        throw new ClientError('ATTENDANCE_COORDINATES_INVALID')
      }
      const body = {
        name: form.name.trim(),
        address: form.address.trim() || null,
        latitude: lat,
        longitude: lng,
        radius_m: form.radius,
      }
      return workplace
        ? (await api.patch<Workplace>(`/attendance/workplaces/${workplace.id}`, body)).data
        : (await api.post<Workplace>('/attendance/workplaces', body)).data
    },
    onSuccess: (next) => {
      invalidateWorkplaces(queryClient, next)
      setSaved(true)
      onSaved?.(next)
    },
  })

  const update = (patch: Partial<Form>) => {
    setSaved(false)
    setForm((f) => ({ ...f, ...patch }))
  }
  const onPick = canEdit
    ? (p: MapPoint) => update({ latitude: p.latitude.toFixed(6), longitude: p.longitude.toFixed(6) })
    : undefined

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <form onSubmit={submit}>
      <Card title={t('attendance.workplace.location')}>
        <div className="space-y-4">
          {!pin && <Alert tone="warning">{t('attendance.workplace.notSet')}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('attendance.workplace.name')}>
              {(id) => (
                <Input
                  id={id}
                  value={form.name}
                  maxLength={100}
                  disabled={!canEdit}
                  required
                  onChange={(e) => update({ name: e.target.value })}
                />
              )}
            </Field>
            <Field label={t('attendance.workplace.address')}>
              {(id) => (
                <Input
                  id={id}
                  value={form.address}
                  maxLength={255}
                  disabled={!canEdit}
                  onChange={(e) => update({ address: e.target.value })}
                />
              )}
            </Field>
          </div>
          <MapView
            workplace={pin}
            onPick={onPick}
            fallbackCenter={fallbackCenter}
            className="isolate z-0 h-80 w-full overflow-hidden rounded-xl ring-1 ring-stone-200"
          />
          {canEdit && <p className="text-xs text-stone-500">{t('attendance.workplace.tapHint')}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('attendance.workplace.latitude')}>
              {(id) => (
                <Input
                  id={id}
                  inputMode="decimal"
                  value={form.latitude}
                  disabled={!canEdit}
                  onChange={(e) => update({ latitude: e.target.value })}
                />
              )}
            </Field>
            <Field label={t('attendance.workplace.longitude')}>
              {(id) => (
                <Input
                  id={id}
                  inputMode="decimal"
                  value={form.longitude}
                  disabled={!canEdit}
                  onChange={(e) => update({ longitude: e.target.value })}
                />
              )}
            </Field>
          </div>
          <Field label={t('attendance.workplace.radius', { radius: form.radius })} hint={t('attendance.workplace.radiusHint')}>
            {(id) => (
              <div className="flex items-center gap-3">
                <input
                  id={id}
                  type="range"
                  min={RADIUS_MIN}
                  max={Math.max(SLIDER_MAX, form.radius)}
                  step={10}
                  value={form.radius}
                  disabled={!canEdit}
                  onChange={(e) => update({ radius: Number(e.target.value) })}
                  className="flex-1 accent-brand-600"
                />
                <Input
                  type="number"
                  min={RADIUS_MIN}
                  max={RADIUS_MAX}
                  value={form.radius}
                  disabled={!canEdit}
                  onChange={(e) => update({ radius: Math.min(RADIUS_MAX, Math.max(0, Number(e.target.value) || 0)) })}
                  className="w-24"
                  aria-label={t('attendance.workplace.radiusMetres')}
                />
              </div>
            )}
          </Field>
          {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
          {saved && workplace && <Alert tone="success">{t('attendance.saved')}</Alert>}
          {(canEdit || actions) && (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {actions}
              {canEdit && (
                <Button type="submit" loading={save.isPending} disabled={form.radius < RADIUS_MIN}>
                  {workplace ? t('common.save') : t('attendance.workplaces.create')}
                </Button>
              )}
            </div>
          )}
        </div>
      </Card>
    </form>
  )
}
