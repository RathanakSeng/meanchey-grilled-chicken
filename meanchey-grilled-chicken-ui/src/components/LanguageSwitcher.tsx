import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ME_QUERY_KEY, useAuth } from '@/auth/AuthProvider'
import { setLanguage } from '@/i18n'
import { api } from '@/lib/api'
import { LANGUAGES, type Language, type Me } from '@/lib/types'
import { cx } from './ui'

/** Switches the UI language and, when signed in, saves it to the user's profile. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { i18n, t } = useTranslation()
  const { me } = useAuth()
  const queryClient = useQueryClient()

  const change = async (lang: Language) => {
    setLanguage(lang)
    // Profile updates are blocked while a password change is pending; keep it local then.
    if (me && !me.user.must_change_password && me.user.language !== lang) {
      try {
        const { data } = await api.patch<Me>('/me', { language: lang })
        queryClient.setQueryData(ME_QUERY_KEY, data)
      } catch {
        /* keep the local choice */
      }
    }
  }

  return (
    <div
      role="group"
      aria-label={t('languages.label')}
      className={cx('inline-flex rounded-lg bg-stone-100 p-0.5 text-xs font-medium', className)}
    >
      {LANGUAGES.map((lang) => (
        <button
          key={lang}
          type="button"
          onClick={() => void change(lang)}
          aria-pressed={i18n.language === lang}
          className={cx(
            'rounded-md px-2.5 py-1 transition',
            i18n.language === lang
              ? 'bg-white text-brand-700 shadow-sm'
              : 'text-stone-600 hover:text-stone-900',
          )}
        >
          {lang === 'km' ? 'ខ្មែរ' : 'EN'}
        </button>
      ))}
    </div>
  )
}
