import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Alert, Button, Card, ConfirmDialog, Field, FullScreenSpinner, Input, PageHeader, Select } from '@/components/ui'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { ClientError, useErrorMessage } from '@/lib/errors'
import { normalizeUsername, useFormatDay } from '@/lib/format'
import {
  LANGUAGES,
  POSITION_MAX_LENGTH,
  type Language,
  type Role,
  type User,
} from '@/lib/types'
import { TRACKED_ROLES } from '@/lib/roles'
import { normalizePosition, POSITIONS_QUERY_KEY, usePositions } from '@/lib/usePositions'
import { invalidateRoleCapacity, useRoleCapacity } from '@/lib/useRoleCapacity'
import { attendanceKeys, businessToday, useWorkplaceOptions } from '@/pages/attendance/api'

interface FormState {
  role: Role
  position: string
  full_name: string
  telegram_username: string
  phone: string
  language: Language
  /** Staff and supervisors: '' = the default workplace (create) / unchanged (edit). */
  workplace_id: string
  /** Staff and supervisors: the first tracked day (YYYY-MM-DD). */
  attendance_start_date: string
  /** Supervisors (edit): switched on or off. */
  attendance_tracked: boolean
}

export function UserFormPage({ mode }: { mode: 'create' | 'edit' }) {
  const { t } = useTranslation()
  const formatDay = useFormatDay()
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
    workplace_id: '',
    attendance_start_date: businessToday(),
    attendance_tracked: true,
  })
  const [confirmUntrack, setConfirmUntrack] = useState(false)
  const tracked = TRACKED_ROLES.includes(form.role)
  const workplaces = useWorkplaceOptions(tracked)

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
      workplace_id: u.workplace?.id ?? '',
      attendance_start_date: u.attendance_start_date ?? businessToday(),
      attendance_tracked: u.attendance_tracked !== false,
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

  // The start date is editable while it is still in the future (always when creating).
  const savedStart = existing.data?.attendance_start_date
  const startEditable = mode === 'create' || !savedStart || savedStart > businessToday()
  const turningOff =
    mode === 'edit' &&
    form.role === 'supervisor' &&
    !form.attendance_tracked &&
    existing.data?.attendance_tracked !== false

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
      const workplace_id = tracked && form.workplace_id ? form.workplace_id : null
      const { attendance_start_date, attendance_tracked, ...fields } = form
      if (mode === 'create') {
        const body = {
          ...fields,
          phone,
          position,
          workplace_id,
          ...(tracked ? { attendance_start_date } : {}),
        }
        return (await api.post<User>('/users', body)).data
      }
      const body = {
        full_name: form.full_name,
        telegram_username: form.telegram_username,
        phone,
        language: form.language,
        ...(form.role === 'staff' ? { position } : {}),
        ...(workplace_id && workplace_id !== existing.data?.workplace?.id ? { workplace_id } : {}),
        ...(tracked && startEditable && attendance_start_date !== existing.data?.attendance_start_date
          ? { attendance_start_date }
          : {}),
        ...(form.role === 'supervisor' && attendance_tracked !== (existing.data?.attendance_tracked !== false)
          ? { attendance_tracked }
          : {}),
      }
      return (await api.patch<User>(`/users/${id}`, body)).data
    },
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      if (mode === 'create') invalidateRoleCapacity(queryClient)
      void queryClient.invalidateQueries({ queryKey: POSITIONS_QUERY_KEY })
      // Employee counts and lists of the workplaces.
      void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplacesAll })
      void queryClient.invalidateQueries({ queryKey: attendanceKeys.workplaceAll })
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
    // Switching a supervisor's attendance off takes effect now: ask first.
    if (turningOff) setConfirmUntrack(true)
    else mutation.mutate()
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

          {tracked && (
            <Field label={t('userForm.workplace')} hint={t('userForm.workplaceHint')}>
              {(fid) =>
                workplaces.data ? (
                  <Select id={fid} value={form.workplace_id} onChange={(e) => set('workplace_id', e.target.value)}>
                    {/* Nothing chosen: the API assigns the default workplace. */}
                    {!form.workplace_id && (
                      <option value="">
                        {workplaces.data.find((w) => w.is_default)?.name ?? t('userForm.workplaceDefault')}
                      </option>
                    )}
                    {workplaces.data
                      .filter((w) => form.workplace_id || !w.is_default)
                      .map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.name}
                        </option>
                      ))}
                    {/* Their current workplace was archived: keep showing it. */}
                    {form.workplace_id && !workplaces.data.some((w) => w.id === form.workplace_id) && (
                      <option value={form.workplace_id}>{existing.data?.workplace?.name}</option>
                    )}
                  </Select>
                ) : (
                  <Input
                    id={fid}
                    value={existing.data?.workplace?.name ?? t('userForm.workplaceDefault')}
                    readOnly
                    disabled
                  />
                )
              }
            </Field>
          )}

          {tracked && (
            <Field
              label={t('userForm.attendanceStart')}
              hint={startEditable ? t('userForm.attendanceStartHint') : t('userForm.attendanceStartLocked')}
            >
              {(fid) =>
                startEditable ? (
                  <Input
                    id={fid}
                    type="date"
                    value={form.attendance_start_date}
                    min={businessToday()}
                    onChange={(e) => set('attendance_start_date', e.target.value)}
                    required
                  />
                ) : (
                  <Input id={fid} value={formatDay(savedStart)} readOnly disabled />
                )
              }
            </Field>
          )}

          {mode === 'edit' && form.role === 'supervisor' && (
            <div className="flex items-start gap-3 sm:col-span-2">
              <input
                id="track-attendance"
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-stone-300 accent-brand-600"
                checked={form.attendance_tracked}
                onChange={(e) => set('attendance_tracked', e.target.checked)}
              />
              <label htmlFor="track-attendance" className="cursor-pointer text-sm">
                <span className="block font-medium text-stone-800">{t('userForm.trackAttendance')}</span>
                <span className="block text-xs text-stone-500">{t('userForm.trackAttendanceHint')}</span>
              </label>
            </div>
          )}

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
      <ConfirmDialog
        open={confirmUntrack}
        title={t('userForm.confirmUntrackTitle', { name: form.full_name })}
        body={t('userForm.confirmUntrackBody')}
        confirmLabel={t('userForm.confirmUntrack')}
        tone="danger"
        loading={mutation.isPending}
        onClose={() => setConfirmUntrack(false)}
        onConfirm={() => {
          setConfirmUntrack(false)
          mutation.mutate()
        }}
      />
    </>
  )
}
