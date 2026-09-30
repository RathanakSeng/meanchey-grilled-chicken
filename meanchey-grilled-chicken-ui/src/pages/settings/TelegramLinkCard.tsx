import { useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/auth/AuthProvider'
import { Icon } from '@/components/icons'
import { Alert, Badge, Button, Card, ConfirmDialog } from '@/components/ui'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { openTelegramLink } from '@/lib/telegram'
import type { TelegramLink } from '@/lib/types'

/**
 * Superadmin only (it has no Telegram username to sign in with): link a Telegram account through
 * a one-time deep link to the bot, so production alerts reach it there. The status refreshes
 * when the window gets focus again (after tapping Start in Telegram).
 */
export function TelegramLinkCard() {
  const { t } = useTranslation()
  const { me, refreshMe } = useAuth()
  const errorMessage = useErrorMessage()
  const [confirmUnlink, setConfirmUnlink] = useState(false)
  const linked = me?.user.telegram_linked ?? false

  const create = useMutation({
    mutationFn: async () => (await api.post<TelegramLink>('/me/telegram-link')).data,
  })
  const unlink = useMutation({
    mutationFn: () => api.delete('/me/telegram-link'),
    onSuccess: async () => {
      setConfirmUnlink(false)
      create.reset()
      await refreshMe()
    },
  })

  // Back from Telegram: pick up the new status.
  useEffect(() => {
    if (linked) return
    const onFocus = () => void refreshMe()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [linked, refreshMe])

  return (
    <Card
      title={t('telegramLink.title')}
      actions={
        <Badge tone={linked ? 'blue' : 'neutral'}>
          {t(linked ? 'status.telegramLinked' : 'status.telegramNotLinked')}
        </Badge>
      }
    >
      <p className="mb-4 text-sm text-stone-600">{t(linked ? 'telegramLink.linkedBody' : 'telegramLink.body')}</p>
      {!linked && create.data && (
        <div className="mb-4 space-y-2">
          <Button onClick={() => openTelegramLink(create.data.url)}>
            <Icon name="telegram" width={18} height={18} />
            {t('telegramLink.open')}
          </Button>
          <p className="text-xs text-stone-500">{t('telegramLink.validFor')}</p>
        </div>
      )}
      {(create.isError || unlink.isError) && (
        <Alert tone="error" className="mb-4">
          {errorMessage(create.error ?? unlink.error)}
        </Alert>
      )}
      {linked ? (
        <Button variant="secondary" onClick={() => setConfirmUnlink(true)}>
          {t('telegramLink.unlink')}
        </Button>
      ) : (
        <Button variant={create.data ? 'secondary' : 'primary'} loading={create.isPending} onClick={() => create.mutate()}>
          {t(create.data ? 'telegramLink.newLink' : 'telegramLink.link')}
        </Button>
      )}

      <ConfirmDialog
        open={confirmUnlink}
        title={t('telegramLink.unlinkTitle')}
        body={t('telegramLink.unlinkBody')}
        confirmLabel={t('telegramLink.unlink')}
        tone="danger"
        loading={unlink.isPending}
        error={unlink.isError ? errorMessage(unlink.error) : null}
        onConfirm={() => unlink.mutate()}
        onClose={() => setConfirmUnlink(false)}
      />
    </Card>
  )
}
