import { useTranslation } from 'react-i18next'
import type { Role, User } from '@/lib/types'
import { Badge } from './ui'
import { Icon } from './icons'

const roleTones = {
  superadmin: 'red',
  general_manager: 'brand',
  supervisor: 'blue',
  staff: 'neutral',
} as const

export function RoleBadge({ role, position }: { role: Role; position?: string | null }) {
  const { t } = useTranslation()
  return (
    <Badge tone={roleTones[role]}>
      {t(`roles.${role}`)}
      {/* Free-text job title, shown exactly as entered (never translated). */}
      {position && ` · ${position}`}
    </Badge>
  )
}

export function isLocked(user: User): boolean {
  return user.locked_until !== null && new Date(user.locked_until) > new Date()
}

export function UserStatusBadges({ user }: { user: User }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex flex-wrap gap-1">
      {user.is_active ? (
        <Badge tone="green">{t('status.active')}</Badge>
      ) : (
        <Badge tone="red">{t('status.inactive')}</Badge>
      )}
      {isLocked(user) && (
        <Badge tone="amber">
          <Icon name="lock" width={12} height={12} />
          {t('status.locked')}
        </Badge>
      )}
      {user.is_active && user.must_change_password && (
        <Badge tone="amber">{t('status.mustChangePassword')}</Badge>
      )}
    </span>
  )
}
