import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthProvider'
import { ChangePasswordForm } from '@/components/ChangePasswordForm'
import { Alert, Button } from '@/components/ui'
import { AuthLayout } from './AuthLayout'

/** Forced password change: new users (except the superadmin) and users whose password was reset. */
export function ChangePasswordPage() {
  const { t } = useTranslation()
  const { logout } = useAuth()
  const navigate = useNavigate()

  return (
    <AuthLayout>
      <div className="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-stone-200">
        <h1 className="text-xl font-semibold text-stone-900">{t('changePassword.title')}</h1>
        <Alert tone="warning" className="mb-5 mt-3">
          {t('changePassword.forcedNotice')}
        </Alert>
        <ChangePasswordForm showFirstLoginHint onSuccess={() => navigate('/', { replace: true })} />
      </div>
      <div className="mt-4 text-center">
        <Button
          variant="ghost"
          onClick={async () => {
            await logout()
            navigate('/login', { replace: true })
          }}
        >
          {t('nav.logout')}
        </Button>
      </div>
    </AuthLayout>
  )
}
