import type { QueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useQuantityFormat } from '@/lib/quantity'

/** Query keys (see docs/ARCHITECTURE.md). */
export const inventoryKeys = {
  overview: ['inventory'] as const,
  movements: ['inventory-movements'] as const,
  /** One item with its per-batch breakdown (`GET /inventory/items/{code}`). */
  item: (code: string) => ['inventory-item', code] as const,
  /** `GET /inventory/materials` (`{include_archived}`). */
  materials: (params: { include_archived: boolean }) => ['inventory-materials', params] as const,
}

/**
 * After a Finish, reopen or cancel, and after any material change: balances, breakdowns,
 * materials and history are refetched.
 */
export function invalidateInventory(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.overview })
  void queryClient.invalidateQueries({ queryKey: inventoryKeys.movements })
  void queryClient.invalidateQueries({ queryKey: ['inventory-item'] })
  void queryClient.invalidateQueries({ queryKey: ['inventory-materials'] })
}

/**
 * Display helpers for stock amounts (the shared unit rule, lib/quantity.ts): counts as whole
 * numbers with thousands separators, kg always with 3 decimals ("12.500 kg"), g with 1
 * ("2,350.0 g"). `signed` adds "+" to positive values (movements).
 */
export function useStockFormat() {
  const format = useQuantityFormat()
  const count = useCallback((value: number, signed = false) => format(value, 'count', signed), [format])
  const kg = useCallback((value: string | number, signed = false) => format(value, 'kg', signed), [format])
  const g = useCallback((value: string | number, signed = false) => format(value, 'g', signed), [format])
  return { count, kg, g }
}

/** Tone of a signed amount: green when stock goes up, red when it goes down. */
export function deltaTone(value: number | string | null): string {
  const n = Number(value ?? 0)
  return n > 0 ? 'text-green-700' : n < 0 ? 'text-red-700' : 'text-stone-500'
}
