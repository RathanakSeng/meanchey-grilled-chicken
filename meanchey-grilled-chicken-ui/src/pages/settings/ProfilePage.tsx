import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { ME_QUERY_KEY, useAuth } from '@/auth/AuthProvider'
import { RoleBadge } from '@/components/badges'
import { ChangePasswordForm } from '@/components/ChangePasswordForm'
import { Alert, Badge, Button, Card, ConfirmDialog, Field, Input, PageHeader, Select } from '@/components/ui'
import { setLanguage } from '@/i18n'
import { api } from '@/lib/api'
import { paths } from '@/lib/paths'
import { useErrorMessage } from '@/lib/errors'
import { isSuperadmin } from '@/lib/roles'
import { LANGUAGES, type Language, type Me, type Role } from '@/lib/types'
import { TelegramLinkCard } from './TelegramLinkCard'

/** What a self-reset returns the password to. */
function useDefaultPasswordLabel() {
  const { t } = useTranslation()
  return (role: Role | undefined) =>
    isSuperadmin(role) ? t('profile.defaultSuperadmin') : t('profile.defaultTelegram')
}

export function ProfilePage() {
  const { t } = useTranslation()
  const defaultPasswordLabel = useDefaultPasswordLabel()
  const { me, logout } = useAuth()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const errorMessage = useErrorMessage()

  const [fullName, setFullName] = useState('')
  const [phone, setPhone] = useState('')
  const [language, setLang] = useState<Language>('km')
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    if (!me) return
    setFullName(me.user.full_name)
    setPhone(me.user.phone ?? '')
    setLang(me.user.language)
  }, [me])

  const save = useMutation({
    mutationFn: async () =>
      (
        await api.patch<Me>('/me', {
          full_name: fullName,
          phone: phone.trim() || null,
          language,
        })
      ).data,
    onSuccess: (data) => {
      queryClient.setQueryData(ME_QUERY_KEY, data)
      setLanguage(data.user.language)
    },
  })

  const selfReset = useMutation({
    mutationFn: () => api.post('/me/reset-password'),
    onSuccess: async () => {
      const value = defaultPasswordLabel(me?.user.role)
      // All sessions were revoked server-side.
      await logout({ skipServer: true })
      navigate('/login', {
        replace: true,
        state: { notice: t('profile.selfResetDone', { value }) },
      })
    },
  })

  if (!me) return null
  const { user } = me
  const defaultValue = defaultPasswordLabel(user.role)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <>
      <PageHeader title={t('profile.title')} back={paths.settings} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={t('profile.info')}>
          <form onSubmit={onSubmit} className="space-y-4">
            <Field label={t('userForm.fullName')}>
              {(id) => (
                <Input
                  id={id}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  maxLength={120}
                  required
                />
              )}
            </Field>
            <Field label={t('userForm.phone')}>
              {(id) => (
                <Input
                  id={id}
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  maxLength={32}
                  placeholder="+855 12 345 678"
                />
              )}
            </Field>
            <Field label={t('userForm.language')}>
              {(id) => (
                <Select id={id} value={language} onChange={(e) => setLang(e.target.value as Language)}>
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>
                      {t(`languages.${l}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {save.isError && <Alert tone="error">{errorMessage(save.error)}</Alert>}
            {save.isSuccess && <Alert tone="success">{t('common.saved')}</Alert>}
            <Button type="submit" loading={save.isPending}>
              {t('common.save')}
            </Button>
          </form>
        </Card>

        <div className="space-y-4">
          <Card title={t('profile.account')}>
            <dl className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <dt className="text-stone-500">{t('userForm.role')}</dt>
                <dd>
                  <RoleBadge role={user.role} position={user.position} />
                </dd>
              </div>
              {user.telegram_username && (
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-stone-500">{t('userForm.telegramUsername')}</dt>
                  <dd className="flex items-center gap-2">
                    @{user.telegram_username}
                    <Badge tone={user.telegram_linked ? 'blue' : 'neutral'}>
                      {t(user.telegram_linked ? 'status.telegramLinked' : 'status.telegramNotLinked')}
                    </Badge>
                  </dd>
                </div>
              )}
            </dl>
          </Card>

          {isSuperadmin(user.role) && <TelegramLinkCard />}

          <Card title={t('profile.changePassword')}>
            <ChangePasswordForm />
          </Card>

          {me.can_self_reset_password && (
            <Card title={t('profile.selfResetTitle')}>
              <p className="mb-4 text-sm text-stone-600">
                {t('profile.selfResetBody', { value: defaultValue })}
              </p>
              <Button variant="danger" onClick={() => setConfirmReset(true)}>
                {t('profile.selfResetButton')}
              </Button>
            </Card>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmReset}
        title={t('profile.selfResetConfirmTitle')}
        body={t('profile.selfResetBody', { value: defaultValue })}
        confirmLabel={t('profile.selfResetButton')}
        tone="danger"
        loading={selfReset.isPending}
        error={selfReset.isError ? errorMessage(selfReset.error) : null}
        onConfirm={() => selfReset.mutate()}
        onClose={() => {
          setConfirmReset(false)
          selfReset.reset()
        }}
      />
    </>
  )
}
