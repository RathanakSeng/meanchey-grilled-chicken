import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/auth/AuthProvider'
import { api } from '@/lib/api'
import { ClientError, useErrorMessage } from '@/lib/errors'
import { normalizeUsername } from '@/lib/format'
import { isSuperadmin, SUPERADMIN_LOGIN } from '@/lib/roles'
import { Alert, Button, Field, Input } from './ui'

const MIN_LENGTH = 8

export function ChangePasswordForm({
  showFirstLoginHint = false,
  onSuccess,
}: {
  showFirstLoginHint?: boolean
  onSuccess?(): void
}) {
  const { t } = useTranslation()
  const { me, refreshMe } = useAuth()
  const errorMessage = useErrorMessage()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const validate = () => {
    if (next.length < MIN_LENGTH) throw new ClientError('PASSWORD_TOO_SHORT', { min_length: MIN_LENGTH })
    const username = isSuperadmin(me?.user.role) ? SUPERADMIN_LOGIN : me?.user.telegram_username
    if (username && normalizeUsername(next) === username) {
      throw new ClientError('PASSWORD_EQUALS_USERNAME')
    }
    if (next !== confirm) throw new ClientError('PASSWORDS_DO_NOT_MATCH')
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setDone(false)
    try {
      validate()
      setSubmitting(true)
      await api.post('/auth/change-password', { current_password: current, new_password: next })
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
      await refreshMe()
      onSuccess?.()
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <Field
        label={t('changePassword.current')}
        hint={showFirstLoginHint ? t('changePassword.currentHint') : undefined}
      >
        {(id) => (
          <Input
            id={id}
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        )}
      </Field>
      <Field label={t('changePassword.new')} hint={t('changePassword.rules')}>
        {(id) => (
          <Input
            id={id}
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        )}
      </Field>
      <Field label={t('changePassword.confirm')}>
        {(id) => (
          <Input
            id={id}
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        )}
      </Field>
      {error !== null && <Alert tone="error">{errorMessage(error)}</Alert>}
      {done && <Alert tone="success">{t('changePassword.success')}</Alert>}
      <Button type="submit" loading={submitting}>
        {t('changePassword.submit')}
      </Button>
    </form>
  )
}
