import type { QueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

/** Query keys (see docs/ARCHITECTURE.md). */
export const inventoryKeys = {
  overview: ['inventory'] as const,
  movements: ['inventory-movements'] as const,
}

/** After a Finish, reopen, cancel or adjustment: balances and history are refetched. */
export function invalidateInventory(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.overview })
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.movements })
}

/**
 * Display helpers for stock amounts: counts as whole numbers with thousands separators, kg (API
 * strings like "4.200") always with 3 decimals and the unit ("12.500 kg"). `signed` adds "+" to
 * positive values (movements).
 */
export function useStockFormat() {
  const { t, i18n } = useTranslation()
  const locale = i18n.language === 'km' ? 'km-KH' : 'en-GB'
  const count = useCallback(
    (value: number, signed = false) =>
      new Intl.NumberFormat(locale, { signDisplay: signed ? 'exceptZero' : 'auto' }).format(value),
    [locale],
  )
  const kg = useCallback(
    (value: string | number, signed = false) =>
      t('inventory.kgValue', {
        value: new Intl.NumberFormat(locale, {
          minimumFractionDigits: 3,
          maximumFractionDigits: 3,
          signDisplay: signed ? 'exceptZero' : 'auto',
        }).format(Number(value)),
      }),
    [locale, t],
  )
  return { count, kg }
}

/** Tone of a signed amount: green when stock goes up, red when it goes down. */
export function deltaTone(value: number | string | null): string {
  const n = Number(value ?? 0)
  return n > 0 ? 'text-green-700' : n < 0 ? 'text-red-700' : 'text-stone-500'
}
