import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { Icon } from '@/components/icons'
import { Button } from '@/components/ui'
import { AuthLayout } from './AuthLayout'

function Message({ title, body, children }: { title: string; body?: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center py-16 text-center">
      <span className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
        <Icon name="alert" />
      </span>
      <h1 className="text-lg font-semibold text-stone-900">{title}</h1>
      {body && <p className="mt-2 text-sm text-stone-600">{body}</p>}
      {children && <div className="mt-6 flex flex-col gap-2">{children}</div>}
    </div>
  )
}

export function ForbiddenPage() {
  const { t } = useTranslation()
  return (
    <Message title={t('forbidden.title')} body={t('forbidden.body')}>
      <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
        {t('notFound.home')}
      </Link>
    </Message>
  )
}

export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <Message title={t('notFound.title')}>
      <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
        {t('notFound.home')}
      </Link>
    </Message>
  )
}

export function OfflinePage({ onRetry }: { onRetry(): void }) {
  const { t } = useTranslation()
  return (
    <AuthLayout>
      <Message title={t('errors.NETWORK_ERROR')}>
        <Button onClick={onRetry}>{t('common.retry')}</Button>
      </Message>
    </AuthLayout>
  )
}

/** Shown inside the Mini App when the automatic Telegram sign-in fails. */
export function TelegramErrorPage({ code }: { code: string }) {
  const { t } = useTranslation()
  const { loginWithTelegram } = useAuth()
  const navigate = useNavigate()
  const body = code === 'USER_NOT_REGISTERED' ? t('telegram.notRegisteredBody') : undefined
  return (
    <AuthLayout>
      <Message
        title={t(`errors.${code}`, { defaultValue: t('telegram.errorTitle') })}
        body={body}
      >
        <Button onClick={() => void loginWithTelegram()}>{t('common.retry')}</Button>
        <Button variant="ghost" onClick={() => navigate('/login')}>
          {t('telegram.usePassword')}
        </Button>
      </Message>
    </AuthLayout>
  )
}
