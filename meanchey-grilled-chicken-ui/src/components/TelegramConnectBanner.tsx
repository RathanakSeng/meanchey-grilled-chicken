import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/auth/AuthProvider'
import { api } from '@/lib/api'
import { storage } from '@/lib/storage'
import { openTelegramLink } from '@/lib/telegram'
import { Icon } from './icons'
import { Button } from './ui'

const dismissedKey = (userId: string) => `mc.telegramBannerDismissed.${userId}`

/**
 * Home: "Connect Telegram to get alerts". Shown to a GM, supervisor or staff member who gets
 * alerts or attendance reminders (`me.telegram_alerts`) while their Telegram isn't linked yet;
 * pressing Start in the bot links it by username, and the banner goes away when the window gets
 * focus again. Dismissed per user on this device. The superadmin links from its profile instead
 * (TelegramLinkCard).
 */
export function TelegramConnectBanner() {
  const { t } = useTranslation()
  const { me, refreshMe } = useAuth()
  const userId = me?.user.id ?? ''
  const [dismissed, setDismissed] = useState(() => Boolean(userId && storage.get(dismissedKey(userId))))
  const show =
    !!me && me.user.role !== 'superadmin' && me.telegram_alerts && !me.user.telegram_linked && !dismissed

  const bot = useQuery({
    queryKey: ['telegram-bot'],
    queryFn: async () => (await api.get<{ url: string }>('/me/telegram-bot')).data.url,
    enabled: show,
    staleTime: Infinity,
    retry: false,
  })

  // Back from Telegram: pick up the new status.
  useEffect(() => {
    if (!show) return
    const onFocus = () => void refreshMe()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [show, refreshMe])

  if (!show) return null

  const dismiss = () => {
    storage.set(dismissedKey(userId), '1')
    setDismissed(true)
  }

  return (
    <div
      role="status"
      className="flex items-start gap-3 rounded-xl bg-sky-50 p-4 text-sm text-sky-900 ring-1 ring-inset ring-sky-200"
    >
      <Icon name="telegram" className="mt-0.5 shrink-0 text-sky-700" width={18} height={18} />
      <div className="min-w-0 flex-1">
        <p>{t('telegramLink.connectBanner')}</p>
        {bot.data && (
          <Button className="mt-3" onClick={() => openTelegramLink(bot.data)}>
            <Icon name="telegram" width={18} height={18} />
            {t('telegramLink.open')}
          </Button>
        )}
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label={t('common.close')}
        className="-m-1 rounded-full p-1 text-sky-700 hover:bg-sky-100"
      >
        <Icon name="close" width={16} height={16} />
      </button>
    </div>
  )
}
