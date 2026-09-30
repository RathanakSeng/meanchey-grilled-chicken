import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Alert, Button, Card, Field, FullScreenSpinner, Input, PageHeader, Select } from '@/components/ui'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { ClientError, useErrorMessage } from '@/lib/errors'
import { normalizeUsername } from '@/lib/format'
import {
  LANGUAGES,
  POSITION_MAX_LENGTH,
  type Language,
  type Role,
  type User,
} from '@/lib/types'
import { normalizePosition, POSITIONS_QUERY_KEY, usePositions } from '@/lib/usePositions'
import { invalidateRoleCapacity, useRoleCapacity } from '@/lib/useRoleCapacity'

interface FormState {
  role: Role
  position: string
  full_name: string
  telegram_username: string
  phone: string
  language: Language
}

export function UserFormPage({ mode }: { mode: 'create' | 'edit' }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const { id } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const errorMessage = useErrorMessage()
  const roles = me?.manageable_roles ?? []
  const capacity = useRoleCapacity()
  const isFull = (r: Role) => capacity.byRole(r)?.full ?? false
  const roleLabel = (r: Role) => {
    const c = capacity.byRole(r)
    if (!c) return t(`roles.${r}`)
    return t(c.full ? 'roleCapacity.optionFull' : 'roleCapacity.option', {
      role: t(`roles.${r}`),
      count: c.active,
      limit: c.limit ?? t('roleCapacity.noLimit'),
    })
  }

  const existing = useQuery({
    queryKey: ['user', id],
    queryFn: async () => (await api.get<User>(`/users/${id}`)).data,
    enabled: mode === 'edit' && !!id,
  })

  const [form, setForm] = useState<FormState>({
    // Default to the lowest role the actor can create (usually staff).
    role: roles[roles.length - 1] ?? 'staff',
    position: '',
    full_name: '',
    telegram_username: '',
    phone: '',
    language: 'km',
  })

  useEffect(() => {
    const u = existing.data
    if (!u) return
    setForm({
      role: u.role,
      position: u.position ?? '',
      full_name: u.full_name,
      telegram_username: u.telegram_username ?? '',
      phone: u.phone ?? '',
      language: u.language,
    })
  }, [existing.data])

  const positions = usePositions()

  // Start on a role with a free slot (the lowest one, usually staff).
  useEffect(() => {
    if (mode !== 'create' || !capacity.data || !isFull(form.role)) return
    const free = [...roles].reverse().find((r) => !isFull(r))
    if (free) setForm((f) => ({ ...f, role: free }))
  }, [capacity.data])

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const mutation = useMutation({
    mutationFn: async (): Promise<User> => {
      const phone = form.phone.trim() || null
      let position: string | null = null
      if (form.role === 'staff') {
        // Same rules as the API: required for staff, at most 50 characters after normalizing.
        position = normalizePosition(form.position)
        if (!position) throw new ClientError('POSITION_REQUIRED')
        if (position.length > POSITION_MAX_LENGTH) throw new ClientError('VALIDATION_ERROR')
      }
      if (mode === 'create') {
        const body = { ...form, phone, position }
        return (await api.post<User>('/users', body)).data
      }
      const body = {
        full_name: form.full_name,
        telegram_username: form.telegram_username,
        phone,
        language: form.language,
        ...(form.role === 'staff' ? { position } : {}),
      }
      return (await api.patch<User>(`/users/${id}`, body)).data
    },
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      if (mode === 'create') invalidateRoleCapacity(queryClient)
      void queryClient.invalidateQueries({ queryKey: POSITIONS_QUERY_KEY })
      queryClient.setQueryData(['user', user.id], user)
      navigate(paths.user(user.id), {
        replace: mode === 'edit',
        state: mode === 'create' ? { created: user.telegram_username } : undefined,
      })
    },
  })

  if (mode === 'edit' && existing.isPending) return <FullScreenSpinner />
  if (mode === 'edit' && existing.isError) {
    return <Alert tone="error">{errorMessage(existing.error)}</Alert>
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    mutation.mutate()
  }
  const allFull =
    mode === 'create' && capacity.data !== undefined && roles.length > 0 && roles.every(isFull)
  const backTo = mode === 'create' || !id ? paths.users : paths.user(id)
  const normalized = normalizeUsername(form.telegram_username)
  const usernameChanged =
    mode === 'edit' &&
    existing.data?.telegram_linked &&
    normalized !== existing.data.telegram_username

  // Every role the actor can create is full: say so instead of showing a form that can't succeed.
  if (allFull) {
    return (
      <>
        <PageHeader title={t('userForm.createTitle')} back={backTo} />
        <Card className="max-w-2xl">
          <Alert tone="warning">{t('roleCapacity.allFull')}</Alert>
          <Button variant="secondary" className="mt-4" onClick={() => navigate(backTo)}>
            {t('common.back')}
          </Button>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title={t(mode === 'create' ? 'userForm.createTitle' : 'userForm.editTitle')}
        back={backTo}
      />
      <Card className="max-w-2xl">
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2">
          {mode === 'create' ? (
            <Field label={t('userForm.role')}>
              {(fid) => (
                <Select
                  id={fid}
                  value={form.role}
                  onChange={(e) => set('role', e.target.value as Role)}
                >
                  {roles.map((r) => (
                    <option key={r} value={r} disabled={isFull(r)}>
                      {roleLabel(r)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          ) : (
            <Field label={t('userForm.role')}>
              {(fid) => <Input id={fid} value={t(`roles.${form.role}`)} disabled />}
            </Field>
          )}

          {form.role === 'staff' ? (
            <Field label={t('userForm.position')} hint={t('userForm.positionHint')}>
              {(fid) => (
                <>
                  <Input
                    id={fid}
                    list={`${fid}-suggestions`}
                    value={form.position}
                    onChange={(e) => set('position', e.target.value)}
                    placeholder={t('userForm.positionPlaceholder')}
                    maxLength={POSITION_MAX_LENGTH}
                    autoComplete="off"
                  />
                  <datalist id={`${fid}-suggestions`}>
                    {positions.data?.map((p) => <option key={p} value={p} />)}
                  </datalist>
                </>
              )}
            </Field>
          ) : (
            <div className="hidden sm:block" />
          )}

          <Field label={t('userForm.fullName')} className="sm:col-span-2">
            {(fid) => (
              <Input
                id={fid}
                value={form.full_name}
                onChange={(e) => set('full_name', e.target.value)}
                maxLength={120}
                required
              />
            )}
          </Field>

          <Field
            label={t('userForm.telegramUsername')}
            hint={
              normalized
                ? t('userForm.loginAs', { username: normalized })
                : t('userForm.telegramHint')
            }
          >
            {(fid) => (
              <Input
                id={fid}
                value={form.telegram_username}
                onChange={(e) => set('telegram_username', e.target.value)}
                placeholder="@username"
                autoCapitalize="none"
                autoCorrect="off"
                maxLength={40}
                required
              />
            )}
          </Field>

          <Field label={t('userForm.phone')}>
            {(fid) => (
              <Input
                id={fid}
                type="tel"
                value={form.phone}
                onChange={(e) => set('phone', e.target.value)}
                placeholder="+855 12 345 678"
                maxLength={32}
              />
            )}
          </Field>

          <Field label={t('userForm.language')}>
            {(fid) => (
              <Select
                id={fid}
                value={form.language}
                onChange={(e) => set('language', e.target.value as Language)}
              >
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>
                    {t(`languages.${l}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <div className="space-y-3 sm:col-span-2">
            {mode === 'create' && roles.some(isFull) && (
              <Alert tone="warning">{t('roleCapacity.someFull')}</Alert>
            )}
            {mode === 'create' && <Alert tone="info">{t('userForm.initialPasswordNote')}</Alert>}
            {usernameChanged && <Alert tone="warning">{t('userForm.usernameChangeNote')}</Alert>}
            {mutation.isError && <Alert tone="error">{errorMessage(mutation.error)}</Alert>}
          </div>

          <div className="flex gap-2 sm:col-span-2">
            <Button
              type="submit"
              loading={mutation.isPending}
              disabled={mode === 'create' && isFull(form.role)}
            >
              {mode === 'create' ? t('userForm.create') : t('common.save')}
            </Button>
            <Button variant="secondary" onClick={() => navigate(backTo)}>
              {t('common.cancel')}
            </Button>
          </div>
        </form>
      </Card>
    </>
  )
}
