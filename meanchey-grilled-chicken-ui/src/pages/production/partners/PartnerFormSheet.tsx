import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Sheet } from '@/components/Sheet'
import { Alert, Button, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { PARTNER_LOCATION_MAX_LENGTH, PARTNER_NAME_MAX_LENGTH, type Partner } from '@/lib/types'
import { partnerKeys, type PartnerConfig } from './config'
import {
  toPayload,
  validatePartner,
  type PartnerField,
  type PartnerFormValues,
} from './validation'

const EMPTY: PartnerFormValues = { name: '', location: '', phone: '' }
const FIELDS: PartnerField[] = ['name', 'location', 'phone']

/** Which field a server error belongs to (null: show it above the form). */
function fieldOf(err: unknown): PartnerField | null {
  const { code, details } = getError(err)
  if (code === 'DUPLICATE_PHONE' || code === 'INVALID_PHONE') return 'phone'
  if (code === 'VALIDATION_ERROR' && Array.isArray(details.fields)) {
    for (const f of details.fields as { loc?: string[] }[]) {
      const field = f.loc?.[1]
      if (field && (FIELDS as string[]).includes(field)) return field as PartnerField
    }
  }
  return null
}

interface Props {
  config: PartnerConfig
  open: boolean
  /** The record to edit; null to create. */
  partner: Partner | null
  onClose(): void
  onSaved(partner: Partner, created: boolean): void
}

export function PartnerFormSheet({ config, open, partner, onClose, onSaved }: Props) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()
  const queryClient = useQueryClient()
  const keys = partnerKeys(config)
  const ns = config.resource

  const [values, setValues] = useState<PartnerFormValues>(EMPTY)
  const [errors, setErrors] = useState<Partial<Record<PartnerField | 'form', unknown>>>({})

  // Reset the form each time the sheet opens.
  useEffect(() => {
    if (!open) return
    setValues(
      partner
        ? { name: partner.name, location: partner.location ?? '', phone: partner.phone_display ?? '' }
        : EMPTY,
    )
    setErrors({})
  }, [open, partner])

  const save = useMutation({
    mutationFn: async (body: ReturnType<typeof toPayload>) =>
      partner
        ? (await api.patch<Partner>(`/${config.resource}/${partner.id}`, body)).data
        : (await api.post<Partner>(`/${config.resource}`, body)).data,
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.one(saved.id), saved)
      queryClient.invalidateQueries({ queryKey: keys.list })
      queryClient.invalidateQueries({ queryKey: keys.stats })
      onSaved(saved, partner === null)
    },
    onError: (err) => setErrors({ [fieldOf(err) ?? 'form']: err }),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const clientErrors = validatePartner(values)
    setErrors(clientErrors)
    if (Object.keys(clientErrors).length === 0) save.mutate(toPayload(values))
  }

  const set = (field: PartnerField) => (value: string) => {
    setValues((v) => ({ ...v, [field]: value }))
    if (errors[field]) setErrors((e) => ({ ...e, [field]: undefined }))
  }

  const fieldError = (field: PartnerField) =>
    errors[field] ? (
      <span className="mt-1 block text-xs text-red-600" role="alert">
        {errorMessage(errors[field])}
      </span>
    ) : null

  const formId = `${config.entity}-form`
  return (
    <Sheet
      open={open}
      onClose={onClose}
      busy={save.isPending}
      title={t(partner ? `${ns}.editTitle` : `${ns}.newTitle`)}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={save.isPending}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" form={formId} loading={save.isPending}>
            {partner ? t('common.save') : t(`${ns}.new`)}
          </Button>
        </div>
      }
    >
      <form id={formId} onSubmit={onSubmit} noValidate className="space-y-4">
        {errors.form != null && <Alert tone="error">{errorMessage(errors.form)}</Alert>}
        <Field label={t('partners.fields.name')} hint={fieldError('name')}>
          {(id) => (
            <Input
              id={id}
              autoFocus
              required
              maxLength={PARTNER_NAME_MAX_LENGTH}
              value={values.name}
              aria-invalid={Boolean(errors.name)}
              onChange={(e) => set('name')(e.target.value)}
              placeholder={t(`${ns}.namePlaceholder`)}
            />
          )}
        </Field>
        <Field
          label={t('partners.fields.location')}
          hint={fieldError('location') ?? t('partners.hints.optional')}
        >
          {(id) => (
            <Input
              id={id}
              maxLength={PARTNER_LOCATION_MAX_LENGTH}
              value={values.location}
              aria-invalid={Boolean(errors.location)}
              onChange={(e) => set('location')(e.target.value)}
              placeholder={t('partners.hints.locationPlaceholder')}
            />
          )}
        </Field>
        <Field label={t('partners.fields.phone')} hint={fieldError('phone') ?? t('partners.hints.phone')}>
          {(id) => (
            <Input
              id={id}
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              maxLength={32}
              value={values.phone}
              aria-invalid={Boolean(errors.phone)}
              onChange={(e) => set('phone')(e.target.value)}
              placeholder="012 345 678"
            />
          )}
        </Field>
      </form>
    </Sheet>
  )
}
