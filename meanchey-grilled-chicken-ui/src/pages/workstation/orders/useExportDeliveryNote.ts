import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDay, useLocalized } from '@/lib/format'
import { isTelegramMiniApp } from '@/lib/telegram'
import type { BusinessSupplier, Order } from '@/lib/types'
import { useQuantityFormat } from './api'
import { ExportError, exportDeliveryNoteXlsx } from './exportDeliveryNote'

export interface ExportResult {
  tone: 'success' | 'error'
  text: string
}

/**
 * Order page → "Export Delivery Note": gets the supplier block (the business info, for anyone allowed to
 * export), maps the order into plain data and hands it to the Excel builder. Nothing is stored.
 */
export function useExportDeliveryNote(order: Order | undefined, report: (result: ExportResult | null) => void) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language === 'en' ? 'en' : 'km'
  const localized = useLocalized()
  const formatDay = useFormatDay()
  const errorMessage = useErrorMessage()
  const quantity = useQuantityFormat()

  return useMutation({
    mutationFn: async () => {
      if (!order) throw new ExportError('noCustomer')
      const supplier = (await api.get<BusinessSupplier>('/orders/delivery-note/supplier')).data
      const other = lang === 'km' ? 'en' : 'km'
      const { customer } = order
      await exportDeliveryNoteXlsx({
        orderCode: order.code,
        date: formatDay(order.delivery_date),
        dateIso: order.delivery_date,
        supplier: {
          name: supplier[`name_${lang}`] || supplier[`name_${other}`],
          phone: supplier.phone_display ?? '',
          address: supplier[`address_${lang}`] ?? supplier[`address_${other}`] ?? '',
        },
        customer: {
          name: customer.name ?? t('orders.directOrder'),
          phone: customer.phone_display ?? customer.phone ?? '',
          address: customer.location ?? '',
        },
        items: order.summary.total.items.map((item) => ({
          name: localized(item),
          unit: quantity(item),
        })),
        lang,
        preferShare: isTelegramMiniApp,
      })
    },
    onMutate: () => report(null),
    onSuccess: () => report({ tone: 'success', text: t('orders.document.exported') }),
    onError: (err) =>
      report({
        tone: 'error',
        text: err instanceof ExportError ? t(`orders.document.exportErrors.${err.code}`) : errorMessage(err),
      }),
  })
}
