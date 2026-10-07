import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ItemPicture } from '@/components/InventoryItemCard'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, getError, useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import {
  QUANTITY_UNITS,
  UNIT_DECIMALS,
  amountIn,
  parseQuantity,
  scaledOfAmount,
  toApiQuantity,
  useQuantityFormat,
  type QuantityUnit,
} from '@/lib/quantity'
import {
  MATERIAL_NAME_MAX_LENGTH,
  MATERIAL_REASON_MAX_LENGTH,
  type InventoryItem,
  type Material,
} from '@/lib/types'
import { invalidateInventory } from './api'
import { materialPicture } from './itemVisuals'
import { ICON_MAX_BYTES, ICON_TYPES, useMaterialIcon } from './materialIcons'

/** Quick amounts per unit for the Add sheet. */
const CHIPS: Record<QuantityUnit, number[]> = { count: [1, 5, 10], kg: [0.5, 1, 5], g: [100, 500, 1000] }

const textareaClass =
  'block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm'

/** A material as the sheets need it: from the overview (an item) or the materials list. */
export interface MaterialRef {
  id: string
  name_km: string
  name_en: string
  unit: QuantityUnit
  system_code: string | null
  /** Bundled picture key and uploaded icon path (see ItemMaterial). */
  iconKey: string | null
  iconUrl: string | null
  count: number | null
  kg: string | null
  g: string | null
  /** Any movement yet (to / from count is then locked). */
  hasMovements: boolean
}

export function materialRefOfItem(item: InventoryItem): MaterialRef | null {
  // A prepared twin carries its material (picture) but isn't changed by hand.
  if (!item.material || item.origin !== 'manual') return null
  return {
    id: item.material.id,
    name_km: item.name_km,
    name_en: item.name_en,
    unit: item.material.unit,
    system_code: item.material.system_code,
    iconKey: item.material.icon_key,
    iconUrl: item.material.icon_url,
    count: item.count,
    kg: item.kg,
    g: item.g,
    // The overview has no movement flag: a material that never changed has no movements.
    hasMovements: item.updated_at !== null,
  }
}

export function materialRefOf(m: Material): MaterialRef {
  return { ...m, iconKey: m.icon_key, iconUrl: m.icon_url, hasMovements: m.has_movements }
}

/** Add stock (chips + quantity, new balance preview) or remove it (quantity + reason). */
export function StockSheet({
  material,
  mode,
  open,
  onClose,
}: {
  material: MaterialRef | null
  mode: 'add' | 'remove'
  open: boolean
  onClose(): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const errorMessage = useErrorMessage()
  const format = useQuantityFormat()
  const queryClient = useQueryClient()
  const [input, setInput] = useState('')
  const [reason, setReason] = useState('')

  const unit: QuantityUnit = material?.unit ?? 'count'
  const parsed = parseQuantity(input, unit)
  const current = material ? scaledOfAmount(amountIn(material, unit), unit) : 0
  const next = parsed.kind === 'ok' ? current + (mode === 'add' ? parsed.scaled : -parsed.scaled) : null
  const tooMuch = next !== null && next < 0
  const save = useMutation({
    mutationFn: async () => {
      if (!material || parsed.kind !== 'ok') return
      const quantity = toApiQuantity(parsed.scaled, unit)
      const body = mode === 'add' ? { quantity } : { quantity, reason: reason.trim() }
      await api.post<Material>(`/inventory/materials/${material.id}/${mode}`, body)
    },
    onSuccess: () => {
      invalidateInventory(queryClient)
      setInput('')
      setReason('')
      onClose()
    },
  })
  if (!material) return null

  const close = () => {
    save.reset()
    setInput('')
    setReason('')
    onClose()
  }
  const ready = parsed.kind === 'ok' && !tooMuch && (mode === 'add' || reason.trim().length > 0)
  const places = UNIT_DECIMALS[unit]
  // Adds to what's typed (from the latest value, so quick taps add up).
  const addChip = (value: number) =>
    setInput((prev) => {
      const before = parseQuantity(prev, unit)
      const base = before.kind === 'ok' ? before.scaled : 0
      const text = String(toApiQuantity(base + Math.round(value * 10 ** places), unit))
      // "1.500" → "1.5" (but "10" stays "10").
      return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
    })

  return (
    <Sheet
      open={open}
      title={t(mode === 'add' ? 'materials.addTitle' : 'materials.removeTitle', { name: localized(material) })}
      onClose={close}
      busy={save.isPending}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={close} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button
            variant={mode === 'add' ? 'primary' : 'danger'}
            loading={save.isPending}
            disabled={!ready}
            onClick={() => save.mutate()}
          >
            {t(mode === 'add' ? 'materials.add' : 'materials.remove')}
          </Button>
        </div>
      }
    >
      <p className="mb-4 text-sm text-stone-600">
        {t('materials.inStock', { amount: format(amountIn(material, unit) ?? 0, unit) })}
      </p>
      <Field
        label={t('materials.quantity', { unit: t(`materials.units.${unit}`) })}
        hint={t(`materials.precision.${unit}`)}
      >
        {(id) => (
          <Input
            id={id}
            inputMode={places === 0 ? 'numeric' : 'decimal'}
            autoComplete="off"
            autoFocus
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-invalid={parsed.kind === 'invalid' || tooMuch ? true : undefined}
            className="h-12 text-base tabular-nums sm:h-10 sm:text-sm"
          />
        )}
      </Field>
      {mode === 'add' && (
        <div className="mt-2 flex flex-wrap gap-2">
          {CHIPS[unit].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => addChip(value)}
              className="rounded-full bg-stone-100 px-3 py-1.5 text-sm font-medium tabular-nums text-stone-700 ring-1 ring-inset ring-stone-200 hover:bg-stone-200"
            >
              +{format(value, unit)}
            </button>
          ))}
        </div>
      )}
      {parsed.kind === 'invalid' && (
        <p className="mt-2 text-sm text-red-700">{t(`materials.invalid.${unit}`)}</p>
      )}
      {next !== null && (
        <p className={tooMuch ? 'mt-3 text-sm font-medium text-red-700' : 'mt-3 text-sm text-stone-700'}>
          {tooMuch
            ? t('materials.notEnough', { amount: format(amountIn(material, unit) ?? 0, unit) })
            : t('materials.newBalance', { amount: format(String(toApiQuantity(next, unit)), unit) })}
        </p>
      )}
      {mode === 'remove' && (
        <Field label={t('materials.reason')} className="mt-4" hint={t('materials.reasonHint')}>
          {(id) => (
            <textarea
              id={id}
              rows={2}
              maxLength={MATERIAL_REASON_MAX_LENGTH}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className={textareaClass}
            />
          )}
        </Field>
      )}
      {save.isError && (
        <Alert tone="error" className="mt-3">
          {errorMessage(save.error)}
        </Alert>
      )}
    </Sheet>
  )
}

/** The material was created but its icon wasn't uploaded (`reason`: why). */
class IconUploadFailed extends Error {
  constructor(readonly reason: unknown) {
    super('Icon upload failed')
  }
}

/** A local file as an object URL (the icon chosen before the material exists). */
function useObjectUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!file) {
      setUrl(null)
      return
    }
    const next = URL.createObjectURL(file)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [file])
  return url
}

/** Type and size before sending (the API checks them again, by decoding the image). */
function checkIcon(file: File) {
  if (!ICON_TYPES.includes(file.type)) throw new ClientError('ICON_WRONG_TYPE')
  if (file.size > ICON_MAX_BYTES) throw new ClientError('ICON_TOO_LARGE')
}

async function putIcon(materialId: string, file: File): Promise<Material> {
  checkIcon(file)
  const data = new FormData()
  data.append('file', file)
  try {
    return (await api.put<Material>(`/inventory/materials/${materialId}/icon`, data)).data
  } catch (err) {
    // Type and size were checked: the API refusing it means it isn't a real image (e.g. renamed).
    if (getError(err).code === 'VALIDATION_ERROR') throw new ClientError('ICON_WRONG_TYPE')
    throw err
  }
}

/**
 * Create a material, or edit one (names, unit, icon).
 *
 * Icon: editing uploads / removes it right away; creating keeps the chosen file and uploads it
 * right after the material is created. If that upload fails the material exists anyway: the sheet
 * then edits it (Save won't create it twice) and shows the error, so the icon can be retried.
 */
export function MaterialFormSheet({
  material: initial,
  open,
  onClose,
}: {
  /** null: a new material. */
  material: MaterialRef | null
  open: boolean
  onClose(): void
}) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const [created, setCreated] = useState<Material | null>(null)
  const material = initial ?? (created ? materialRefOf(created) : null)
  const [nameKm, setNameKm] = useState(initial?.name_km ?? '')
  const [nameEn, setNameEn] = useState(initial?.name_en ?? '')
  const [unit, setUnit] = useState<QuantityUnit>(initial?.unit ?? 'kg')
  // The uploaded icon (changes as soon as an upload / removal succeeds) and, while creating, the
  // file chosen for it.
  const [iconUrl, setIconUrl] = useState<string | null>(initial?.iconUrl ?? null)
  const [pending, setPending] = useState<File | null>(null)
  const [iconError, setIconError] = useState<unknown>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const pendingUrl = useObjectUrl(pending)
  const uploadedUrl = useMaterialIcon(iconUrl)
  const preview = pendingUrl ?? uploadedUrl ?? materialPicture(material?.iconKey)

  const save = useMutation({
    mutationFn: async () => {
      setIconError(null)
      const body = { name_km: nameKm.trim(), name_en: nameEn.trim(), unit }
      if (material) {
        await api.patch<Material>(`/inventory/materials/${material.id}`, body)
        return
      }
      const made = (await api.post<Material>('/inventory/materials', body)).data
      if (!pending) return
      try {
        await putIcon(made.id, pending)
      } catch (err) {
        setCreated(made)
        setIconUrl(null)
        setPending(null)
        throw new IconUploadFailed(err)
      }
    },
    onSuccess: () => {
      invalidateInventory(queryClient)
      onClose()
    },
    onError: (err) => {
      if (err instanceof IconUploadFailed) {
        invalidateInventory(queryClient)
        setIconError(err.reason)
      }
    },
  })
  const icon = useMutation({
    mutationFn: async (file: File | null) => {
      if (!material) return null
      return file
        ? await putIcon(material.id, file)
        : (await api.delete<Material>(`/inventory/materials/${material.id}/icon`)).data
    },
    onMutate: () => setIconError(null),
    onSuccess: (m) => {
      if (!m) return
      setIconUrl(m.icon_url)
      invalidateInventory(queryClient)
    },
    onError: (err) => setIconError(err),
  })

  const chooseIcon = (file: File) => {
    if (material) {
      icon.mutate(file)
      return
    }
    try {
      checkIcon(file)
      setIconError(null)
      setPending(file)
    } catch (err) {
      setIconError(err)
    }
  }
  const removeIcon = () => {
    setIconError(null)
    if (material) icon.mutate(null)
    else setPending(null)
  }
  const hasUpload = Boolean(pending || iconUrl)

  const weight = (u: QuantityUnit) => u !== 'count'
  // To / from count only before the first stock entry; never to count for system materials.
  const unitLocked = (u: QuantityUnit): string | undefined => {
    if (!material || u === material.unit) return undefined
    if (material.system_code && u === 'count') return t('materials.systemNoCount')
    if (weight(u) !== weight(material.unit) && material.hasMovements) return t('materials.unitLocked')
    return undefined
  }
  const ready = nameKm.trim() !== '' && nameEn.trim() !== ''
  const busy = save.isPending || icon.isPending
  const close = () => {
    // A material created before its icon failed is in the list already.
    if (created) invalidateInventory(queryClient)
    onClose()
  }

  return (
    <Sheet
      open={open}
      title={initial ? t('materials.editTitle') : t('materials.newTitle')}
      onClose={close}
      busy={busy}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={close} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button loading={save.isPending} disabled={!ready || icon.isPending} onClick={() => save.mutate()}>
            {t('common.save')}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <Field label={t('materials.nameKm')}>
          {(id) => (
            <Input id={id} value={nameKm} maxLength={MATERIAL_NAME_MAX_LENGTH} onChange={(e) => setNameKm(e.target.value)} />
          )}
        </Field>
        <Field label={t('materials.nameEn')}>
          {(id) => (
            <Input id={id} value={nameEn} maxLength={MATERIAL_NAME_MAX_LENGTH} onChange={(e) => setNameEn(e.target.value)} />
          )}
        </Field>
        <div>
          <p className="mb-1 text-sm font-medium text-stone-700">{t('materials.unit')}</p>
          <SegmentedControl<QuantityUnit>
            label={t('materials.unit')}
            segments={QUANTITY_UNITS.map((u) => ({
              value: u,
              label: t(`materials.units.${u}`),
              disabled: unitLocked(u) !== undefined,
              title: unitLocked(u),
            }))}
            value={unit}
            onChange={setUnit}
          />
          <p className="mt-1 text-xs text-stone-500">
            {material ? t('materials.unitChangeHint') : t('materials.unitHint')}
          </p>
          {material && material.unit !== unit && weight(unit) && weight(material.unit) && (
            <p className="mt-2 text-sm text-stone-700">
              {t('materials.unitConvertPreview', { from: t(`materials.units.${material.unit}`), to: t(`materials.units.${unit}`) })}
            </p>
          )}
        </div>
        <div>
          <p className="mb-1 text-sm font-medium text-stone-700">
            {t('materials.icon')} <span className="font-normal text-stone-400">({t('materials.optional')})</span>
          </p>
          <div className="flex items-center gap-3">
            <ItemPicture
              src={preview}
              icon={unit === 'count' ? 'hash' : 'scale'}
              className="h-16 w-16 ring-1 ring-inset ring-stone-200"
            />
            <div className="flex min-w-0 flex-wrap gap-2">
              <Button
                variant="secondary"
                loading={icon.isPending && icon.variables !== null}
                disabled={busy}
                onClick={() => fileRef.current?.click()}
              >
                {hasUpload ? t('materials.iconChange') : t('materials.iconUpload')}
              </Button>
              {hasUpload && (
                <Button
                  variant="ghost"
                  loading={icon.isPending && icon.variables === null}
                  disabled={busy}
                  onClick={removeIcon}
                >
                  {t('materials.iconRemove')}
                </Button>
              )}
            </div>
          </div>
          <p className="mt-1 text-xs text-stone-500">{t('materials.iconHint')}</p>
          <input
            ref={fileRef}
            type="file"
            accept={ICON_TYPES.join(',')}
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) chooseIcon(file)
            }}
          />
          {iconError !== null && (
            <Alert tone="error" className="mt-2">
              {created && !initial ? `${t('materials.iconUploadFailed')} ` : ''}
              {errorMessage(iconError)}
            </Alert>
          )}
        </div>
        {save.isError && !(save.error instanceof IconUploadFailed) && (
          <Alert tone="error">{errorMessage(save.error)}</Alert>
        )}
      </div>
    </Sheet>
  )
}
