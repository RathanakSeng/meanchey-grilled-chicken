import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Icon } from '@/components/icons'
import { Alert, Button, Field, Input } from '@/components/ui'
import { useErrorMessage } from '@/lib/errors'
import { isTelegramMiniApp } from '@/lib/telegram'
import { AuthLayout } from './AuthLayout'

export function LoginPage() {
  const { t } = useTranslation()
  const { login, loginWithTelegram, telegramError } = useAuth()
  const errorMessage = useErrorMessage()
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout>
      <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
        <h1 className="text-xl font-semibold text-stone-900">{t('login.title')}</h1>
        <p className="mt-1 text-sm text-stone-500">{t('login.subtitle')}</p>

        {notice && (
          <Alert tone="success" className="mt-4">
            {notice}
          </Alert>
        )}

        {isTelegramMiniApp && (
          <>
            <Button className="mt-5" block onClick={() => void loginWithTelegram()}>
              <Icon name="telegram" width={18} height={18} />
              {t('login.withTelegram')}
            </Button>
            {telegramError && (
              <Alert tone="error" className="mt-3">
                {t(`errors.${telegramError}`, { defaultValue: t('errors.UNKNOWN') })}
              </Alert>
            )}
            <p className="my-4 text-center text-xs uppercase text-stone-400">{t('login.or')}</p>
          </>
        )}

        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <Field label={t('login.username')} hint={t('login.usernameHint')}>
            {(id) => (
              <Input
                id={id}
                autoComplete="username"
                autoCapitalize="none"
                autoCorrect="off"
                placeholder={t('login.usernamePlaceholder')}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            )}
          </Field>
          <Field label={t('login.password')}>
            {(id) => (
              <Input
                id={id}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            )}
          </Field>
          {error !== null && <Alert tone="error">{errorMessage(error)}</Alert>}
          <Button type="submit" block loading={submitting}>
            {t('login.submit')}
          </Button>
        </form>
        <p className="mt-4 text-xs text-stone-500">{t('login.firstTimeHint')}</p>
      </div>
    </AuthLayout>
  )
}
