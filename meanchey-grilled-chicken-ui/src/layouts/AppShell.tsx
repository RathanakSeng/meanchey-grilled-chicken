import { DesktopLayout } from './DesktopLayout'
import { MobileLayout } from './MobileLayout'
import { useIsMobileLayout } from './useIsMobileLayout'

export function AppShell() {
  return useIsMobileLayout() ? <MobileLayout /> : <DesktopLayout />
}
