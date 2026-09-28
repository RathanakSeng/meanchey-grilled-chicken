import type { ReactNode } from 'react'
import { LanguageSwitcher } from '@/components/LanguageSwitcher'
import { Brand } from '@/layouts/Brand'

/** Centered card layout for sign-in and password pages. */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full flex-col bg-gradient-to-b from-brand-50 to-stone-50">
      <header className="flex items-center justify-between px-4 py-4 sm:px-6">
        <Brand />
        <LanguageSwitcher />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pb-10 pt-6 sm:items-center sm:pt-0">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  )
}
