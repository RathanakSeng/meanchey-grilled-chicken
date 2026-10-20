import { useTranslation } from 'react-i18next'
import { useRefreshMeWhenStale } from '@/auth/AuthProvider'
import { NavTile } from '@/components/NavTile'
import { PageHeader } from '@/components/ui'
import { useNavChildren } from '@/layouts/nav'
import { paths } from '@/lib/paths'
import { useIsTracked } from './api'
import { AttendanceHomeCard } from './AttendanceCard'

/** Attendance hub: the action card for tracked employees, then My day / Today (nav tree). */
export function AttendancePage() {
  const { t } = useTranslation()
  useRefreshMeWhenStale()
  const items = useNavChildren(paths.attendance)
  const tracked = useIsTracked()
  return (
    <>
      <PageHeader title={t('nav.attendance')} back={paths.home} />
      <div className="space-y-4">
        {tracked && <AttendanceHomeCard />}
        <div className="grid gap-3 md:grid-cols-2">
          {items.map((item) => (
            <NavTile key={item.to} item={item} />
          ))}
        </div>
      </div>
    </>
  )
}
