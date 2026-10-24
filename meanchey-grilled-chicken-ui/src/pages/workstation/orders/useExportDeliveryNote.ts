import { useMutation } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/api'
import { useErrorMessage } from '@/lib/errors'
import { useFormatDay, useLocalized } from '@/lib/format'
import { isTelegramMiniApp } from '@/lib/telegram'
import type { BusinessSupplier, Order } from '@/lib/types'
import { useQuantityFormat } from './api'
import { ExportError, exportDeliveryNoteXlsx, saveFile } from './exportDeliveryNote'

export interface ExportResult {
  tone: 'success' | 'error'
  text: string
}

/**
 * Order page → "Export Delivery Note ▾" → Excel: gets the supplier block (the business info, for anyone allowed to
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
    onSuccess: () => report({ tone: 'success', text: t('orders.document.exportedXlsx') }),
    onError: (err) =>
      report({
        tone: 'error',
        text: err instanceof ExportError ? t(`orders.document.exportErrors.${err.code}`) : errorMessage(err),
      }),
  })
}

/**
 * Order page → "Export Delivery Note ▾" → PDF: the API's delivery note (`GET /orders/{id}/document.pdf`,
 * the same PDF Send to my Telegram sends), saved as `<order code>.pdf` like the Excel file (share sheet
 * in the Telegram WebView). The API counts it as a print, so `onCounted` refreshes the order.
 */
export function useExportDeliveryNotePdf(
  order: Order | undefined,
  report: (result: ExportResult | null) => void,
  onCounted: () => void,
) {
  const { t } = useTranslation()
  const errorMessage = useErrorMessage()

  return useMutation({
    mutationFn: async () => {
      if (!order) throw new ExportError('noCustomer')
      let pdf: Blob
      try {
        pdf = (await api.get<Blob>(`/orders/${order.id}/document.pdf`, { responseType: 'blob' })).data
      } catch (err) {
        // With a blob response the API's JSON error arrives as a Blob too: read it back.
        if (isAxiosError(err) && err.response?.data instanceof Blob) {
          try {
            err.response.data = JSON.parse(await err.response.data.text())
          } catch {
            // Not JSON (e.g. a proxy page): the generic message.
          }
        }
        throw err
      }
      onCounted()
      await saveFile(new Blob([pdf], { type: 'application/pdf' }), `${order.code}.pdf`, isTelegramMiniApp)
    },
    onMutate: () => report(null),
    onSuccess: () => report({ tone: 'success', text: t('orders.document.exportedPdf') }),
    onError: (err) =>
      report({
        tone: 'error',
        text: err instanceof ExportError ? t(`orders.document.exportErrors.${err.code}`) : errorMessage(err),
      }),
  })
}
