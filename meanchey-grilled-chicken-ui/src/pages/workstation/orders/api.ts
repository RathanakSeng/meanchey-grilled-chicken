import type { QueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import type { OrderQuantity, OrderStatus, OrderUnit } from '@/lib/types'
import { invalidateInventory, useStockFormat } from '@/pages/workstation/inventory/api'

/** Query keys (see docs/ARCHITECTURE.md). */
export const orderKeys = {
  list: ['orders'] as const,
  stats: ['orders-stats'] as const,
  order: (id: string) => ['order', id] as const,
  customerOptions: (q: string) => ['orders-customer-options', q] as const,
  driverOptions: ['orders-driver-options'] as const,
  availableStock: ['orders-available-stock'] as const,
}

/** After any change: lists, figures and (stock moves at Delivering and the review) inventory. */
export function invalidateOrders(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: orderKeys.list })
  void queryClient.invalidateQueries({ queryKey: orderKeys.stats })
  void queryClient.invalidateQueries({ queryKey: orderKeys.availableStock })
  invalidateInventory(queryClient)
}

export const COMPLETED_STATUSES: OrderStatus[] = ['success', 'partly_returned', 'fully_returned']

export const STATUS_TONES: Record<OrderStatus, 'neutral' | 'brand' | 'green' | 'red' | 'amber' | 'blue'> = {
  created: 'neutral',
  delivering: 'blue',
  return_pending: 'amber',
  success: 'green',
  partly_returned: 'brand',
  fully_returned: 'red',
  cancelled: 'neutral',
}

// --- Quantities ----------------------------------------------------------------------------------
// Kilograms are handled as whole grams ("1.250" → 1250) so sums are exact; counts as integers.

const KG_PATTERN = /^\d+(\.\d{0,3})?$/
const COUNT_PATTERN = /^\d+$/

/** The typed value as an integer amount (count, or grams), or null when it isn't valid. */
export function parseAmount(unit: OrderUnit, raw: string): number | null {
  const value = raw.trim().replace(',', '.')
  if (!value) return null
  if (unit === 'count') return COUNT_PATTERN.test(value) ? Number(value) : null
  if (!KG_PATTERN.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  return Number(whole) * 1000 + Number(fraction.padEnd(3, '0'))
}

/** An API quantity as an integer amount (count, or grams). */
export function amountOf(q: { count: number | null; kg: string | null }): number {
  if (q.count !== null) return q.count
  return parseAmount('kg', q.kg ?? '0') ?? 0
}

/** Back to the API's form: a count, or kg with 3 decimals ("1.250"). */
export function toApi(unit: OrderUnit, amount: number): { count?: number; kg?: string } {
  return unit === 'count' ? { count: amount } : { kg: (amount / 1000).toFixed(3) }
}

/** "3" / "1.250 kg" for an integer amount, in the UI language. */
export function useAmountFormat() {
  const fmt = useStockFormat()
  return useCallback(
    (unit: OrderUnit, amount: number) => (unit === 'count' ? fmt.count(amount) : fmt.kg(amount / 1000)),
    [fmt],
  )
}

/** "3" / "1.250 kg" for an API quantity. */
export function useQuantityFormat() {
  const format = useAmountFormat()
  return useCallback((q: OrderQuantity) => format(q.unit, amountOf(q)), [format])
}
