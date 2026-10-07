import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'
import { usePermission } from '@/auth/usePermission'
import { ActionMenu, type ActionMenuItem } from '@/components/ActionMenu'
import { Icon } from '@/components/icons'
import { Sheet } from '@/components/Sheet'
import { Alert, Badge, Button, Card, ConfirmDialog, Field, PageHeader, Spinner, cx } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, getError, useErrorMessage } from '@/lib/errors'
import { useFormatDate, useFormatDay, useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import { UNIT_DECIMALS, useQuantityFormat, type QuantityUnit } from '@/lib/quantity'
import {
  PREPARATION_NOTE_MAX_LENGTH,
  PREPARATION_REASON_MAX_LENGTH,
  type PackSize,
  type Preparation,
  type PreparationItem,
  type PreparationMaterial,
} from '@/lib/types'
import { keepaliveFetch, useAutosave, type AutosaveTarget } from '@/lib/useAutosave'
import { formatScaled } from '@/pages/workstation/production/numbers'
import { NumberField, StepShell } from '@/pages/workstation/production/StepShell'
import { onPreparationChanged, preparationDraftKey, preparationKeys } from './api'
import { ItemThumb, MaterialThumb, PreparationStatusBadge, PreparationTypeBadge } from './badges'
import {
  PACK_SIZES,
  fieldErrors,
  fromPreparation,
  gramsInUnit,
  lineCount,
  parseAmount,
  stockScaled,
  toPayload,
  type PreparationValues,
  type UnitContext,
} from './values'

const ZIP_ROLE = { 2: 'zip_bag_2', 4: 'zip_bag_4' } as const

/**
 * One preparation (code PP-…): header with the status and prepared date, ⋮ Reopen
 * (`preparation.update`, finished) and Cancel (`preparation.cancel`, reason required). A draft is
 * a form that saves itself (the shared autosave, like production steps) with a sticky Finish;
 * a finished or cancelled one is a read-only summary of what was used and made.
 */
export function PreparationPage() {
  const { preparationId = '' } = useParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDay = useFormatDay()
  const formatDate = useFormatDate()
  const canRecord = usePermission('preparation.create')
  const canReopen = usePermission('preparation.update')
  const canCancel = usePermission('preparation.cancel')
  const [reopenOpen, setReopenOpen] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
  const [reason, setReason] = useState('')

  const query = useQuery({
    queryKey: preparationKeys.one(preparationId),
    queryFn: async () => (await api.get<Preparation>(`/preparations/${preparationId}`)).data,
  })
  const p = query.data
  // Someone else changed it meanwhile: show the current copy (the error says so).
  const refetchIfStale = (err: unknown) => {
    const { code } = getError(err)
    if (code.startsWith('PREPARATION_')) void query.refetch()
  }

  const reopen = useMutation({
    mutationFn: async () =>
      (await api.post<Preparation>(`/preparations/${preparationId}/reopen`, { version: p?.version })).data,
    onSuccess: (data) => {
      onPreparationChanged(queryClient, data)
      setReopenOpen(false)
    },
    onError: (err) => refetchIfStale(err),
  })
  const cancel = useMutation({
    mutationFn: async () =>
      (
        await api.post<Preparation>(`/preparations/${preparationId}/cancel`, {
          version: p?.version,
          reason: reason.trim(),
        })
      ).data,
    onSuccess: (data) => {
      onPreparationChanged(queryClient, data)
      setCancelOpen(false)
    },
    onError: (err) => refetchIfStale(err),
  })

  if (query.isPending) {
    return (
      <div className="flex justify-center py-10 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (!p) {
    return (
      <>
        <PageHeader back={paths.preparations} title={t('preparations.title')} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const actions: ActionMenuItem[] = [
    ...(canReopen && p.status === 'finished'
      ? [
          {
            key: 'reopen',
            label: t('preparations.reopen'),
            icon: 'restore' as const,
            onSelect: () => {
              reopen.reset()
              setReopenOpen(true)
            },
          },
        ]
      : []),
    ...(canCancel && p.status !== 'cancelled'
      ? [
          {
            key: 'cancel',
            label: t('preparations.cancel'),
            icon: 'close' as const,
            tone: 'danger' as const,
            onSelect: () => {
              cancel.reset()
              setReason('')
              setCancelOpen(true)
            },
          },
        ]
      : []),
  ]

  return (
    <>
      <PageHeader
        back={paths.preparations}
        title={<span className="tabular-nums">{p.code}</span>}
        subtitle={t(`preparations.types.${p.type}.title`)}
        actions={<ActionMenu items={actions} label={t('preparations.actions')} />}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm text-stone-600">
        <PreparationStatusBadge status={p.status} />
        <PreparationTypeBadge type={p.type} />
        <span className="tabular-nums">
          {p.prepared_date
            ? t('preparations.preparedOn', { date: formatDay(p.prepared_date) })
            : t('production.started', { date: formatDate(p.created_at, { day: 'numeric', month: 'short' }) })}
        </span>
      </div>

      {p.status === 'cancelled' && (
        <Alert className="mb-4">
          <p className="font-medium">{t('preparations.cancelledNotice')}</p>
          {p.cancel_reason && <p className="mt-0.5">{p.cancel_reason}</p>}
        </Alert>
      )}

      {p.status === 'draft' && canRecord ? (
        <PreparationForm key={p.id} preparation={p} />
      ) : (
        <>
          {p.status === 'draft' && <Alert className="mb-4">{t('preparations.viewOnlyNotice')}</Alert>}
          <PreparationSummary preparation={p} />
        </>
      )}

      <ConfirmDialog
        open={reopenOpen}
        title={t('preparations.reopenTitle', { code: p.code })}
        body={t('preparations.reopenBody')}
        confirmLabel={t('preparations.reopen')}
        loading={reopen.isPending}
        error={reopen.isError ? errorMessage(reopen.error) : null}
        onConfirm={() => reopen.mutate()}
        onClose={() => setReopenOpen(false)}
      />
      <Sheet
        open={cancelOpen}
        title={t('preparations.cancel')}
        onClose={() => setCancelOpen(false)}
        busy={cancel.isPending}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setCancelOpen(false)} disabled={cancel.isPending}>
              {t('common.cancel')}
            </Button>
            <Button variant="danger" loading={cancel.isPending} disabled={!reason.trim()} onClick={() => cancel.mutate()}>
              {t('preparations.cancel')}
            </Button>
          </div>
        }
      >
        <p className="mb-3 text-sm text-stone-600">
          {t(p.status === 'finished' ? 'preparations.cancelBodyFinished' : 'preparations.cancelBody', {
            code: p.code,
          })}
        </p>
        <Field label={t('preparations.cancelReason')}>
          {(id) => (
            <textarea
              id={id}
              rows={3}
              autoFocus
              maxLength={PREPARATION_REASON_MAX_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
            />
          )}
        </Field>
        {cancel.isError && (
          <Alert tone="error" className="mt-3">
            {errorMessage(cancel.error)}
          </Alert>
        )}
      </Sheet>
    </>
  )
}

// --- Read-only summary ---------------------------------------------------------------------------

function ItemRows({ items }: { items: PreparationItem[] }) {
  const localized = useLocalized()
  const format = useQuantityFormat()
  return (
    <ul className="divide-y divide-stone-100">
      {items.map((item) => (
        <li key={item.item_code} className="flex items-center gap-3 py-2">
          {item.material_id ? (
            <MaterialThumb
              material={{
                id: item.material_id,
                item_code: item.item_code,
                unit: item.unit,
                icon_key: item.icon_key,
                icon_url: null,
              }}
            />
          ) : (
            <ItemThumb code={item.item_code} />
          )}
          <span className="min-w-0 flex-1 text-sm text-stone-800">{localized(item)}</span>
          <span className="shrink-0 text-sm font-semibold tabular-nums text-stone-900">
            {format(item.quantity, item.unit)}
          </span>
        </li>
      ))}
    </ul>
  )
}

function PreparationSummary({ preparation: p }: { preparation: Preparation }) {
  const { t } = useTranslation()
  const formatDate = useFormatDate()
  const by = (ref: Preparation['finished_by']) =>
    ref ? (ref.is_system ? t('audit.system') : ref.full_name) : t('audit.system')
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={t('preparations.used')}>
        <div className="px-4 pb-2 sm:px-5">
          {p.inputs.length ? <ItemRows items={p.inputs} /> : <p className="py-4 text-sm text-stone-500">—</p>}
        </div>
      </Card>
      <Card title={t('preparations.made')}>
        <div className="px-4 pb-2 sm:px-5">
          {p.outputs.length ? <ItemRows items={p.outputs} /> : <p className="py-4 text-sm text-stone-500">—</p>}
        </div>
      </Card>
      {(p.note || p.finished_at || p.cancelled_at) && (
        <Card className="lg:col-span-2">
          <div className="space-y-1 p-4 text-sm text-stone-600 sm:p-5">
            {p.finished_at && (
              <p>{t('preparations.finishedBy', { name: by(p.finished_by), time: formatDate(p.finished_at) })}</p>
            )}
            {p.cancelled_at && (
              <p>{t('preparations.cancelledBy', { name: by(p.cancelled_by), time: formatDate(p.cancelled_at) })}</p>
            )}
            {p.note && (
              <p>
                <span className="font-medium text-stone-700">{t('preparations.fields.note')}:</span> {p.note}
              </p>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

// --- Draft form ----------------------------------------------------------------------------------

/** "Available: 1.250 kg" under an input; red when the entered amount is more. */
function Available({ material, exceeded }: { material: PreparationMaterial | null; exceeded: boolean }) {
  const { t } = useTranslation()
  const format = useQuantityFormat()
  if (!material) return <span className="text-red-600">{t('preparations.noMaterial')}</span>
  return (
    <span className={cx('tabular-nums', exceeded && 'font-medium text-red-600')}>
      {t('preparations.available', { amount: format(material.stock, material.unit) })}
    </span>
  )
}

function unitLabel(t: (k: string) => string, unit: QuantityUnit) {
  return unit === 'count' ? '' : t(`materials.units.${unit}`)
}

function PreparationForm({ preparation: p }: { preparation: Preparation }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const localized = useLocalized()
  const format = useQuantityFormat()
  const [values, setValues] = useState<PreparationValues>(() => fromPreparation(p))
  const [picking, setPicking] = useState(false)

  const options = useQuery({
    queryKey: preparationKeys.materialOptions,
    queryFn: async () => (await api.get<PreparationMaterial[]>('/preparations/material-options')).data,
    enabled: p.type === 'packaging_material',
  })
  // Materials by id: the options (fresh stock) and the saved lines (an archived one stays shown).
  const materials = new Map<string, PreparationMaterial>()
  for (const line of p.lines) if (line.material) materials.set(line.material.id, line.material)
  for (const m of options.data ?? []) materials.set(m.id, m)

  const sm = p.satay_materials
  const units: UnitContext = {
    zipUnit: (size) => sm?.[ZIP_ROLE[size]]?.unit ?? 'kg',
    materialUnit: (id) => materials.get(id)?.unit ?? 'kg',
  }

  const target: AutosaveTarget<Preparation> = {
    storageKey: preparationDraftKey(p.id),
    entity: p,
    version: (e) => e.version,
    updatedAt: (e) => e.updated_at,
    editable: (e) => e.status === 'draft',
    save: async (body) => (await api.patch<Preparation>(`/preparations/${p.id}`, body)).data,
    keepalive: (body) => keepaliveFetch(`/preparations/${p.id}`, 'PATCH', body),
    conflictCode: 'PREPARATION_CONFLICT',
    conflictEntity: (details) => details.preparation as Preparation | undefined,
    reload: () => void queryClient.invalidateQueries({ queryKey: preparationKeys.one(p.id) }),
  }
  const autosave = useAutosave<Preparation, PreparationValues>({
    target,
    enabled: true,
    values,
    setValues,
    fromEntity: fromPreparation,
    toPayload: (v) => toPayload(p.type, v, units),
    onSaved: (saved) => queryClient.setQueryData(preparationKeys.one(p.id), saved),
  })

  const finish = useMutation({
    mutationFn: async () => {
      // Everything typed must be on the server first; Finish validates the saved copy.
      if (!(await autosave.flush())) throw new ClientError('PRODUCTION_UNSAVED')
      return (await api.post<Preparation>(`/preparations/${p.id}/finish`, { version: autosave.version() })).data
    },
    onSuccess: (data) => {
      autosave.clearDraft()
      onPreparationChanged(queryClient, data)
    },
  })

  const typingErrors = fieldErrors(p.type, values, units, false)
  const finishErrors = fieldErrors(p.type, values, units, true)
  const scaled = (input: string, unit: QuantityUnit) => {
    const parsed = parseAmount(input, unit)
    return parsed.kind === 'ok' ? parsed.value : 0
  }

  // Stock checks (what the API refuses with INVENTORY_INSUFFICIENT), shown before Finish.
  const short: string[] = []
  const exceeded = new Set<string>()
  if (p.type === 'satay_sachet') {
    const sauce = sm?.satay_sauce ?? null
    const grams = PACK_SIZES.filter((s) => values.satay[s].include).reduce(
      (sum, s) => sum + scaled(values.satay[s].satay_g, 'g'),
      0,
    )
    if (sauce && sauce.unit !== 'count' && gramsInUnit(grams, sauce.unit) > stockScaled(sauce)) {
      PACK_SIZES.forEach((s) => exceeded.add(`${s}.satay_g`))
      short.push(t('preparations.notEnough', { name: localized(sauce) }))
    }
    for (const size of PACK_SIZES) {
      const zip = sm?.[ZIP_ROLE[size]] ?? null
      if (!values.satay[size].include || !zip) continue
      if (scaled(values.satay[size].zip_bag_qty, zip.unit) > stockScaled(zip)) {
        exceeded.add(`${size}.zip_bag_qty`)
        short.push(t('preparations.notEnough', { name: localized(zip) }))
      }
    }
  } else {
    for (const line of values.packaging) {
      const m = materials.get(line.material_id)
      if (m && scaled(line.quantity, m.unit) > stockScaled(m)) {
        exceeded.add(`${m.id}.quantity`)
        short.push(t('preparations.notEnough', { name: localized(m) }))
      }
    }
  }

  const missingMaterial =
    p.type === 'satay_sachet' &&
    (!sm?.satay_sauce || PACK_SIZES.some((s) => values.satay[s].include && !sm?.[ZIP_ROLE[s]]))
  const blockers = [
    ...(lineCount(p.type, values) === 0 ? [t('preparations.blockers.noLines')] : []),
    ...(Object.keys(finishErrors).length > 0 ? [t('preparations.blockers.fillIn')] : []),
    ...(missingMaterial ? [t('preparations.blockers.noMaterial')] : []),
    ...short,
  ]

  const setSatay = (size: PackSize, field: keyof PreparationValues['satay'][2], value: string | boolean) =>
    setValues((v) => ({ ...v, satay: { ...v.satay, [size]: { ...v.satay[size], [field]: value } } }))
  const setQuantity = (id: string, quantity: string) =>
    setValues((v) => ({
      ...v,
      packaging: v.packaging.map((l) => (l.material_id === id ? { ...l, quantity } : l)),
    }))
  const removeLine = (id: string) =>
    setValues((v) => ({ ...v, packaging: v.packaging.filter((l) => l.material_id !== id) }))
  const addLine = (id: string) => {
    setValues((v) => ({ ...v, packaging: [...v.packaging, { material_id: id, quantity: '' }] }))
    setPicking(false)
  }
  const fieldError = (key: string) => typingErrors[key] ?? null

  let body: ReactNode
  if (p.type === 'satay_sachet') {
    body = (
      <div className="grid gap-4 md:grid-cols-2">
        {PACK_SIZES.map((size) => {
          const line = values.satay[size]
          const zip = sm?.[ZIP_ROLE[size]] ?? null
          return (
            <div
              key={size}
              className={cx(
                'rounded-xl p-4 ring-1',
                line.include ? 'bg-white ring-brand-200' : 'bg-stone-50 ring-stone-200',
              )}
            >
              <label className="flex cursor-pointer items-center gap-3">
                <ItemThumb code={`satay_sachet_${size}`} className="h-12 w-12" />
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold text-stone-900">{t(`preparations.satay.line${size}`)}</span>
                  <span className="block text-xs text-stone-500">{t('preparations.satay.include')}</span>
                </span>
                <input
                  type="checkbox"
                  checked={line.include}
                  onChange={(e) => setSatay(size, 'include', e.target.checked)}
                  className="h-5 w-5 rounded border-stone-300 text-brand-600 focus:ring-brand-500"
                  aria-label={`${t('preparations.satay.include')}: ${t(`preparations.satay.line${size}`)}`}
                />
              </label>
              {line.include && (
                <div className="mt-4 space-y-3">
                  <NumberField
                    label={t('preparations.satay.sauceUsed')}
                    value={line.satay_g}
                    onChange={(v) => setSatay(size, 'satay_g', v)}
                    unit={t('materials.units.g')}
                    mode="decimal"
                    error={fieldError(`${size}.satay_g`)}
                    hint={<Available material={sm?.satay_sauce ?? null} exceeded={exceeded.has(`${size}.satay_g`)} />}
                  />
                  <NumberField
                    label={t('preparations.satay.zipUsed')}
                    value={line.zip_bag_qty}
                    onChange={(v) => setSatay(size, 'zip_bag_qty', v)}
                    unit={unitLabel(t, units.zipUnit(size))}
                    mode={units.zipUnit(size) === 'count' ? 'numeric' : 'decimal'}
                    error={fieldError(`${size}.zip_bag_qty`)}
                    hint={<Available material={zip} exceeded={exceeded.has(`${size}.zip_bag_qty`)} />}
                  />
                  <NumberField
                    label={t('preparations.satay.sachetsMade')}
                    value={line.sachets}
                    onChange={(v) => setSatay(size, 'sachets', v)}
                    mode="numeric"
                    error={fieldError(`${size}.sachets`)}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  } else {
    const chosen = new Set(values.packaging.map((l) => l.material_id))
    const available = (options.data ?? []).filter((m) => !chosen.has(m.id))
    body = (
      <div className="space-y-3">
        <p className="rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800 ring-1 ring-inset ring-sky-200">
          {t('preparations.packaging.hint')}
        </p>
        {values.packaging.length === 0 && (
          <p className="py-4 text-center text-sm text-stone-500">{t('preparations.packaging.empty')}</p>
        )}
        <ul className="space-y-3">
          {values.packaging.map((line) => {
            const m = materials.get(line.material_id)
            if (!m) return null
            return (
              <li key={m.id} className="rounded-xl bg-white p-3 ring-1 ring-stone-200">
                <div className="mb-2 flex items-center gap-3">
                  <MaterialThumb material={m} />
                  <span className="min-w-0 flex-1 font-medium text-stone-900">{localized(m)}</span>
                  {m.archived && <Badge>{t('materials.archivedBadge')}</Badge>}
                  <button
                    type="button"
                    onClick={() => removeLine(m.id)}
                    className="rounded-lg p-2 text-stone-500 hover:bg-stone-100"
                    aria-label={t('preparations.packaging.remove', { name: localized(m) })}
                  >
                    <Icon name="close" width={18} height={18} />
                  </button>
                </div>
                <NumberField
                  label={t('preparations.packaging.quantity')}
                  value={line.quantity}
                  onChange={(v) => setQuantity(m.id, v)}
                  unit={unitLabel(t, m.unit)}
                  mode={m.unit === 'count' ? 'numeric' : 'decimal'}
                  error={fieldError(`${m.id}.quantity`)}
                  hint={<Available material={m} exceeded={exceeded.has(`${m.id}.quantity`)} />}
                />
              </li>
            )
          })}
        </ul>
        <Button variant="soft" onClick={() => setPicking(true)} disabled={options.isPending}>
          <Icon name="plus" width={18} height={18} />
          {t('preparations.packaging.add')}
        </Button>
        <Sheet open={picking} title={t('preparations.packaging.add')} onClose={() => setPicking(false)}>
          {available.length === 0 ? (
            <p className="py-6 text-center text-sm text-stone-500">{t('preparations.packaging.noneLeft')}</p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {available.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => addLine(m.id)}
                    className="flex w-full items-center gap-3 px-1 py-3 text-left hover:bg-stone-50"
                  >
                    <MaterialThumb material={m} />
                    <span className="min-w-0 flex-1 font-medium text-stone-900">{localized(m)}</span>
                    <span className="shrink-0 text-sm tabular-nums text-stone-500">{format(m.stock, m.unit)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Sheet>
      </div>
    )
  }

  // Outputs preview (what Finish makes), from the values on screen.
  const preview: string[] =
    p.type === 'satay_sachet'
      ? PACK_SIZES.filter((s) => values.satay[s].include && scaled(values.satay[s].sachets, 'count') > 0).map((s) =>
          t('preparations.countOf', {
            n: scaled(values.satay[s].sachets, 'count'),
            name: t(`preparations.satay.line${s}`),
          }),
        )
      : values.packaging.flatMap((l) => {
          const m = materials.get(l.material_id)
          const n = m ? scaled(l.quantity, m.unit) : 0
          return m && n > 0 ? [`${localized(m)} ${format(formatScaled(n, UNIT_DECIMALS[m.unit]), m.unit)}`] : []
        })

  return (
    <StepShell
      title={t(`preparations.types.${p.type}.title`)}
      autosave={autosave}
      fieldLabel={(key) => t(key.startsWith('lines') ? 'preparations.fields.lines' : 'preparations.fields.note')}
      blockers={blockers}
      onFinish={() => finish.mutate()}
      finishing={finish.isPending}
      finishError={finish.error}
      finishLabel={t('preparations.finish')}
      confirmTitle={t('preparations.finishConfirmTitle')}
      confirmBody={t('preparations.finishConfirmBody')}
    >
      {body}
      {preview.length > 0 && (
        <p className="rounded-lg bg-green-50 px-3 py-2 text-sm text-green-800 ring-1 ring-inset ring-green-200">
          {t('preparations.willMake', { items: preview.join(', ') })}
        </p>
      )}
      <Field label={t('preparations.fields.note')}>
        {(id) => (
          <textarea
            id={id}
            rows={2}
            maxLength={PREPARATION_NOTE_MAX_LENGTH}
            value={values.note}
            onChange={(e) => setValues((v) => ({ ...v, note: e.target.value }))}
            className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
          />
        )}
      </Field>
      <p className="text-xs text-stone-500">{t('preparations.dateHint')}</p>
    </StepShell>
  )
}
