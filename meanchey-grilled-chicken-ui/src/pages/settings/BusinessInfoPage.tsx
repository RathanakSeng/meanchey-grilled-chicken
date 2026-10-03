import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Icon } from '@/components/icons'
import { Alert, Button, Card, Field, Input, PageHeader, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import { ClientError, getError, useErrorMessage } from '@/lib/errors'
import { useFormatDate } from '@/lib/format'
import { paths } from '@/lib/paths'
import { fetchPdf, openPdf } from '@/lib/pdf'
import {
  BUSINESS_ADDRESS_MAX_LENGTH,
  BUSINESS_FOOTER_MAX_LENGTH,
  BUSINESS_NAME_MAX_LENGTH,
  LOGO_MAX_BYTES,
  type BusinessInfo,
} from '@/lib/types'

export const BUSINESS_KEY = ['business-settings'] as const
const LOGO_KEY = ['business-settings', 'logo'] as const

const FIELDS = ['name_km', 'name_en', 'address_km', 'address_en', 'phone', 'footer_note_km', 'footer_note_en'] as const
type FieldName = (typeof FIELDS)[number]
type Form = Record<FieldName, string>

function toForm(info: BusinessInfo): Form {
  const form = {} as Form
  for (const f of FIELDS) form[f] = (f === 'phone' ? info.phone_display : info[f]) ?? ''
  return form
}

const textareaClass =
  'block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm'

/** The logo as an object URL (fetched with the API client: it needs the bearer token). */
function useLogoUrl(info: BusinessInfo | undefined): string | null {
  const query = useQuery({
    queryKey: [...LOGO_KEY, info?.updated_at],
    enabled: Boolean(info?.has_logo),
    queryFn: async () => (await api.get<Blob>('/settings/business/logo', { responseType: 'blob' })).data,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!info?.has_logo || !query.data) {
      setUrl(null)
      return
    }
    const next = URL.createObjectURL(query.data)
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [info?.has_logo, query.data])
  return url
}

/**
 * Settings → Business info: what delivery notes print at the top (logo, names, address, phone)
 * and bottom (footer note). The superadmin, or a general manager given Business info.
 */
export function BusinessInfoPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const formatDate = useFormatDate()
  const fileRef = useRef<HTMLInputElement>(null)

  const query = useQuery({
    queryKey: BUSINESS_KEY,
    queryFn: async () => (await api.get<BusinessInfo>('/settings/business')).data,
  })
  const info = query.data
  const logoUrl = useLogoUrl(info)
  const [form, setForm] = useState<Form | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (info) setForm(toForm(info))
  }, [info])

  const onSaved = (next: BusinessInfo) => {
    queryClient.setQueryData(BUSINESS_KEY, next)
    setSaved(true)
  }
  const save = useMutation({
    mutationFn: async (values: Form) => {
      const body: Record<string, string | null> = {}
      for (const f of FIELDS) body[f] = values[f].trim() || null
      return (await api.put<BusinessInfo>('/settings/business', body)).data
    },
    onMutate: () => setSaved(false),
    onSuccess: onSaved,
  })
  const uploadLogo = useMutation({
    mutationFn: async (file: File) => {
      if (!['image/png', 'image/jpeg'].includes(file.type)) throw new ClientError('LOGO_WRONG_TYPE')
      if (file.size > LOGO_MAX_BYTES) throw new ClientError('LOGO_TOO_LARGE')
      const data = new FormData()
      data.append('file', file)
      try {
        return (await api.put<BusinessInfo>('/settings/business/logo', data)).data
      } catch (err) {
        // Type and size are checked above, so the API refusing it means the file isn't a real
        // PNG / JPEG (e.g. renamed): say that instead of the generic validation message.
        if (getError(err).code === 'VALIDATION_ERROR') throw new ClientError('LOGO_WRONG_TYPE')
        throw err
      }
    },
    onMutate: () => setSaved(false),
    onSuccess: onSaved,
  })
  const removeLogo = useMutation({
    mutationFn: async () => (await api.delete<BusinessInfo>('/settings/business/logo')).data,
    onMutate: () => setSaved(false),
    onSuccess: onSaved,
  })
  const preview = useMutation({
    mutationFn: (tab: Window | null) => openPdf(() => fetchPdf('/settings/business/preview.pdf'), tab),
  })

  if (query.isPending || (info && !form)) {
    return (
      <div className="flex justify-center py-16 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (!info || !form) {
    return (
      <>
        <PageHeader back={paths.settings} title={t('business.title')} />
        <Alert tone="error">{errorMessage(query.error)}</Alert>
      </>
    )
  }

  const set = (field: FieldName) => (value: string) => {
    setSaved(false)
    setForm({ ...form, [field]: value })
  }
  const dirty = FIELDS.some((f) => form[f] !== toForm(info)[f])
  const namesMissing = !form.name_km.trim() || !form.name_en.trim()
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!namesMissing) save.mutate(form)
  }
  const error = save.error ?? uploadLogo.error ?? removeLogo.error ?? preview.error

  const text = (field: FieldName, max: number, label: string, hint?: string) => (
    <Field label={label} hint={hint}>
      {(id) => (
        <Input id={id} value={form[field]} maxLength={max} onChange={(e) => set(field)(e.target.value)} />
      )}
    </Field>
  )
  const area = (field: FieldName, max: number, label: string) => (
    <Field label={label}>
      {(id) => (
        <textarea
          id={id}
          rows={2}
          value={form[field]}
          maxLength={max}
          onChange={(e) => set(field)(e.target.value)}
          className={textareaClass}
        />
      )}
    </Field>
  )

  return (
    <>
      <PageHeader
        back={paths.settings}
        title={t('business.title')}
        subtitle={t('business.subtitle')}
        actions={
          <Button
            variant="secondary"
            loading={preview.isPending}
            onClick={() => preview.mutate(window.open('', '_blank'))}
          >
            {!preview.isPending && <Icon name="receipt" width={18} height={18} />}
            {t('business.preview')}
          </Button>
        }
      />

      {error && (
        <Alert tone="error" className="mb-4">
          {errorMessage(error)}
        </Alert>
      )}
      {saved && (
        <Alert tone="success" className="mb-4">
          {t('business.saved')}
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Card title={t('business.nameSection')}>
            <div className="grid gap-4 sm:grid-cols-2">
              {text('name_km', BUSINESS_NAME_MAX_LENGTH, t('business.fields.nameKm'))}
              {text('name_en', BUSINESS_NAME_MAX_LENGTH, t('business.fields.nameEn'))}
            </div>
            {namesMissing && <p className="mt-2 text-sm text-red-700">{t('business.namesRequired')}</p>}
          </Card>
          <Card title={t('business.contactSection')}>
            <div className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                {area('address_km', BUSINESS_ADDRESS_MAX_LENGTH, t('business.fields.addressKm'))}
                {area('address_en', BUSINESS_ADDRESS_MAX_LENGTH, t('business.fields.addressEn'))}
              </div>
              <div className="sm:w-1/2 sm:pr-2">
                {text('phone', 32, t('business.fields.phone'), t('business.phoneHint'))}
              </div>
            </div>
          </Card>
          <Card title={t('business.footerSection')}>
            <div className="grid gap-4 sm:grid-cols-2">
              {area('footer_note_km', BUSINESS_FOOTER_MAX_LENGTH, t('business.fields.footerKm'))}
              {area('footer_note_en', BUSINESS_FOOTER_MAX_LENGTH, t('business.fields.footerEn'))}
            </div>
            <p className="mt-2 text-xs text-stone-500">{t('business.footerHint')}</p>
          </Card>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
            {info.updated_by && (
              <p className="text-xs text-stone-500 sm:mr-auto">
                {t('business.updated', {
                  date: formatDate(info.updated_at),
                  name: info.updated_by.is_system ? t('audit.system') : info.updated_by.full_name,
                })}
              </p>
            )}
            <Button type="submit" loading={save.isPending} disabled={!dirty || namesMissing}>
              {t('common.save')}
            </Button>
          </div>
        </form>

        <Card title={t('business.logo')}>
          <div className="flex h-32 items-center justify-center rounded-lg bg-stone-50 ring-1 ring-inset ring-stone-200">
            {logoUrl ? (
              <img src={logoUrl} alt={t('business.logo')} className="max-h-28 max-w-full object-contain" />
            ) : (
              <span className="flex flex-col items-center gap-1 text-sm text-stone-400">
                <Icon name="image" width={28} height={28} />
                {t('business.noLogo')}
              </span>
            )}
          </div>
          <p className="mt-2 text-xs text-stone-500">{t('business.logoHint')}</p>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) uploadLogo.mutate(file)
            }}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="secondary" loading={uploadLogo.isPending} onClick={() => fileRef.current?.click()}>
              {info.has_logo ? t('business.changeLogo') : t('business.uploadLogo')}
            </Button>
            {info.has_logo && (
              <Button variant="ghost" loading={removeLogo.isPending} onClick={() => removeLogo.mutate()}>
                {t('business.removeLogo')}
              </Button>
            )}
          </div>
        </Card>
      </div>
    </>
  )
}
