import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Icon } from '@/components/icons'
import { Alert, Button, Card, Field, Input, PageHeader, Select, Spinner, cx } from '@/components/ui'
import { useIsMobileLayout } from '@/layouts/useIsMobileLayout'
import { api } from '@/lib/api'
import { getError, useErrorMessage } from '@/lib/errors'
import { useLocalized } from '@/lib/format'
import { paths } from '@/lib/paths'
import {
  ORDER_NOTE_MAX_LENGTH,
  type AvailableItem,
  type BoxColor,
  type DriverOption,
  type Order,
} from '@/lib/types'
import { amountOf, invalidateOrders, orderKeys, parseAmount, toApi, useAmountFormat } from './api'
import { BoxSwatch } from './badges'
import { CustomerPicker, type PickedCustomer } from './CustomerPicker'
import { OrderSummaryView, type SummaryModel, type SummaryRow } from './OrderSummaryView'

interface LineState {
  key: string
  item_code: string
  qty: string
}

interface BoxState {
  key: string
  color: BoxColor
  lines: LineState[]
}

interface FormState {
  customer: PickedCustomer | null
  delivery_date: string
  driver_id: string
  note: string
  boxes: BoxState[]
}

let keySeed = 0
const newKey = () => `k${++keySeed}`

/** Today in the business time zone (Asia/Phnom_Penh), as "YYYY-MM-DD". */
function businessToday(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Phnom_Penh' })
}

const emptyLine = (): LineState => ({ key: newKey(), item_code: '', qty: '' })
const emptyBox = (color: BoxColor): BoxState => ({ key: newKey(), color, lines: [emptyLine()] })

function fromOrder(order: Order): FormState {
  return {
    customer: { ...order.customer },
    delivery_date: order.delivery_date,
    driver_id: order.driver?.id ?? '',
    note: order.note ?? '',
    boxes: order.boxes.map((box) => ({
      key: newKey(),
      color: box.color,
      lines: box.lines.map((line) => ({
        key: newKey(),
        item_code: line.item_code,
        qty: line.unit === 'count' ? String(line.count) : (line.kg ?? ''),
      })),
    })),
  }
}

type Errors = Record<string, string>

/** Client checks, the same as the API's: a customer, ≥ 1 box, ≥ 1 line per box, an item and a
 * valid quantity per line (whole for packs, ≤ 3 decimals for kg, > 0), one line per item per box. */
function validate(form: FormState, items: Map<string, AvailableItem>): Errors {
  const errors: Errors = {}
  if (!form.customer) errors.customer = 'orders.errors.customerRequired'
  if (!form.delivery_date) errors.delivery_date = 'orders.errors.dateRequired'
  if (form.boxes.length === 0) errors.boxes = 'orders.errors.boxesRequired'
  for (const box of form.boxes) {
    if (box.lines.length === 0) errors[`box:${box.key}`] = 'orders.errors.linesRequired'
    const seen = new Set<string>()
    for (const line of box.lines) {
      const item = items.get(line.item_code)
      if (!item) {
        errors[`item:${line.key}`] = 'orders.errors.itemRequired'
        continue
      }
      if (seen.has(line.item_code)) errors[`item:${line.key}`] = 'orders.errors.itemTwice'
      seen.add(line.item_code)
      const amount = parseAmount(item.unit, line.qty)
      if (amount === null || amount <= 0) {
        errors[`qty:${line.key}`] = item.unit === 'count' ? 'orders.errors.countInvalid' : 'orders.errors.kgInvalid'
      }
    }
  }
  return errors
}

/** The live summary from the form: complete lines only. */
function liveSummary(form: FormState, items: Map<string, AvailableItem>, order: string[]): SummaryModel {
  const add = (target: Map<string, SummaryRow>, line: LineState) => {
    const item = items.get(line.item_code)
    const amount = item ? parseAmount(item.unit, line.qty) : null
    if (!item || amount === null || amount <= 0) return
    const row = target.get(item.item_code)
    if (row) row.amount += amount
    else target.set(item.item_code, { ...item, amount })
  }
  const sorted = (m: Map<string, SummaryRow>) =>
    [...m.values()].sort((a, b) => order.indexOf(a.item_code) - order.indexOf(b.item_code))
  const total = new Map<string, SummaryRow>()
  const colors = (['white', 'black'] as BoxColor[]).flatMap((color) => {
    const boxes = form.boxes.filter((b) => b.color === color)
    if (boxes.length === 0) return []
    const rows = new Map<string, SummaryRow>()
    for (const box of boxes) for (const line of box.lines) add(rows, line)
    return [{ color, boxes: boxes.length, items: sorted(rows) }]
  })
  for (const box of form.boxes) for (const line of box.lines) add(total, line)
  return { colors, total: { boxes: form.boxes.length, items: sorted(total) } }
}

function body(form: FormState, items: Map<string, AvailableItem>) {
  return {
    customer_id: form.customer?.id,
    delivery_date: form.delivery_date,
    driver_id: form.driver_id || null,
    note: form.note.trim() || null,
    boxes: form.boxes.map((box) => ({
      color: box.color,
      lines: box.lines.map((line) => {
        const item = items.get(line.item_code)!
        return { item_code: line.item_code, ...toApi(item.unit, parseAmount(item.unit, line.qty) ?? 0) }
      }),
    })),
  }
}

function BoxCard({
  box,
  index,
  items,
  available,
  errors,
  onChange,
  onDuplicate,
  onRemove,
}: {
  box: BoxState
  index: number
  items: AvailableItem[]
  available: Record<string, number>
  errors: Errors
  onChange(box: BoxState): void
  onDuplicate(): void
  onRemove(): void
}) {
  const { t } = useTranslation()
  const localized = useLocalized()
  const format = useAmountFormat()
  const setLine = (key: string, changes: Partial<LineState>) =>
    onChange({ ...box, lines: box.lines.map((l) => (l.key === key ? { ...l, ...changes } : l)) })
  const used = new Set(box.lines.map((l) => l.item_code))

  return (
    <section
      className={cx(
        'rounded-xl bg-white shadow-sm ring-1',
        errors[`box:${box.key}`] ? 'ring-red-300' : 'ring-stone-200',
      )}
      aria-label={t('orders.boxTitle', { n: index + 1 })}
    >
      <header className="flex items-center justify-between gap-2 border-b border-stone-100 px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold text-stone-900">
          <BoxSwatch color={box.color} className="h-4 w-4" />
          {t('orders.boxTitle', { n: index + 1 })}
          <span className="font-normal text-stone-500">· {t(`orders.colors.${box.color}`)}</span>
        </span>
        <span className="flex items-center gap-1">
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={onDuplicate}>
            {t('orders.duplicateBox')}
          </Button>
          <Button variant="ghost" className="px-2 py-1 text-xs text-red-700 hover:bg-red-50" onClick={onRemove}>
            {t('orders.removeBox')}
          </Button>
        </span>
      </header>
      <div className="space-y-2 p-3 sm:p-4">
        {box.lines.map((line) => {
          const item = items.find((i) => i.item_code === line.item_code)
          const itemError = errors[`item:${line.key}`]
          const qtyError = errors[`qty:${line.key}`]
          return (
            <div key={line.key} className="grid grid-cols-[1fr_7rem_auto] items-start gap-2 sm:grid-cols-[1fr_9rem_auto]">
              <div>
                <Select
                  aria-label={t('orders.item')}
                  aria-invalid={Boolean(itemError) || undefined}
                  className={cx('h-11 sm:h-10', itemError && 'ring-red-400')}
                  value={line.item_code}
                  onChange={(e) => setLine(line.key, { item_code: e.target.value, qty: '' })}
                >
                  <option value="">{t('orders.chooseItem')}</option>
                  {items.map((i) => (
                    <option key={i.item_code} value={i.item_code} disabled={i.item_code !== line.item_code && used.has(i.item_code)}>
                      {t('orders.itemOption', {
                        name: localized(i),
                        amount: format(i.unit, available[i.item_code] ?? 0),
                      })}
                    </option>
                  ))}
                </Select>
                {itemError && <p className="mt-1 text-xs text-red-700">{t(itemError)}</p>}
              </div>
              <div>
                <div className="relative">
                  <Input
                    aria-label={t('orders.quantity')}
                    aria-invalid={Boolean(qtyError) || undefined}
                    inputMode={item?.unit === 'kg' ? 'decimal' : 'numeric'}
                    className={cx('h-11 text-right tabular-nums sm:h-10', item?.unit === 'kg' && 'pr-9', qtyError && 'ring-red-400')}
                    placeholder={item?.unit === 'kg' ? '0.000' : '0'}
                    disabled={!item}
                    value={line.qty}
                    onChange={(e) => setLine(line.key, { qty: e.target.value })}
                  />
                  {item?.unit === 'kg' && (
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-stone-500">
                      {t('orders.kgUnit')}
                    </span>
                  )}
                </div>
                {qtyError && <p className="mt-1 text-xs text-red-700">{t(qtyError)}</p>}
              </div>
              <button
                type="button"
                onClick={() => onChange({ ...box, lines: box.lines.filter((l) => l.key !== line.key) })}
                className="mt-1.5 rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
                aria-label={t('orders.removeLine')}
              >
                <Icon name="close" width={18} height={18} />
              </button>
            </div>
          )
        })}
        {errors[`box:${box.key}`] && <p className="text-xs text-red-700">{t(errors[`box:${box.key}`])}</p>}
        <Button
          variant="ghost"
          className="px-2 py-1 text-sm text-brand-700"
          disabled={box.lines.length >= items.length}
          onClick={() => onChange({ ...box, lines: [...box.lines, emptyLine()] })}
        >
          <Icon name="plus" width={16} height={16} />
          {t('orders.addLine')}
        </Button>
      </div>
    </section>
  )
}

/**
 * Create an order, or edit a Created one (`orders.update`): customer, delivery date, driver, note
 * and the boxes builder (+ White box / + Black box, lines with the stock available, Duplicate /
 * Remove), with a live per-colour summary (sticky on desktop; a bar that opens at the bottom on
 * phones) and amber warnings when a total is above the stock. Saving opens the order page.
 */
export function OrderFormPage({ mode }: { mode: 'create' | 'edit' }) {
  const { t } = useTranslation()
  const { orderId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isMobile = useIsMobileLayout()
  const errorMessage = useErrorMessage()

  const existing = useQuery({
    queryKey: orderKeys.order(orderId),
    queryFn: async () => (await api.get<Order>(`/orders/${orderId}`)).data,
    enabled: mode === 'edit',
  })
  const stock = useQuery({
    queryKey: orderKeys.availableStock,
    queryFn: async () => (await api.get<AvailableItem[]>('/orders/available-stock')).data,
  })
  const drivers = useQuery({
    queryKey: orderKeys.driverOptions,
    queryFn: async () => (await api.get<DriverOption[]>('/orders/driver-options')).data,
  })

  const [form, setForm] = useState<FormState | null>(
    mode === 'create'
      ? { customer: null, delivery_date: businessToday(), driver_id: '', note: '', boxes: [emptyBox('white')] }
      : null,
  )
  const [version, setVersion] = useState<number | null>(null)
  const [showErrors, setShowErrors] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [summaryOpen, setSummaryOpen] = useState(false)

  useEffect(() => {
    if (mode === 'edit' && existing.data && form === null) {
      setForm(fromOrder(existing.data))
      setVersion(existing.data.version)
    }
  }, [mode, existing.data, form])

  const itemList = useMemo(() => stock.data ?? [], [stock.data])
  const items = useMemo(() => new Map(itemList.map((i) => [i.item_code, i])), [itemList])
  const available = useMemo(
    () => Object.fromEntries(itemList.map((i) => [i.item_code, amountOf(i)])),
    [itemList],
  )
  const order = useMemo(() => itemList.map((i) => i.item_code), [itemList])

  const save = useMutation({
    mutationFn: async (f: FormState) => {
      const payload = body(f, items)
      if (mode === 'create') return (await api.post<Order>('/orders', payload)).data
      return (await api.patch<Order>(`/orders/${orderId}`, { ...payload, version })).data
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(orderKeys.order(saved.id), saved)
      invalidateOrders(queryClient)
      navigate(paths.order(saved.id), { replace: true })
    },
    onError: (err) => {
      const { code, details } = getError(err)
      if (code === 'ORDER_CONFLICT' && details.order) {
        // Someone else saved first: show their version.
        const current = details.order as Order
        queryClient.setQueryData(orderKeys.order(current.id), current)
        setForm(fromOrder(current))
        setVersion(current.version)
        setNotice(t('orders.conflictReloaded'))
      }
    },
  })

  if (mode === 'edit' && existing.isPending) {
    return (
      <div className="flex justify-center py-16 text-brand-600">
        <Spinner />
      </div>
    )
  }
  if (mode === 'edit' && !existing.data) {
    return (
      <>
        <PageHeader back={paths.orders} title={t('orders.editTitle')} />
        <Alert tone="error">{errorMessage(existing.error)}</Alert>
      </>
    )
  }
  if (mode === 'edit' && existing.data && existing.data.status !== 'created') {
    return (
      <>
        <PageHeader back={paths.order(orderId)} title={t('orders.editTitle')} />
        <Alert tone="warning">
          {t('orders.notEditable')}{' '}
          <Link to={paths.order(orderId)} className="font-medium underline">
            {t('orders.openOrder')}
          </Link>
        </Alert>
      </>
    )
  }
  if (!form) return null

  const errors = validate(form, items)
  const visibleErrors = showErrors ? errors : {}
  const summary = liveSummary(form, items, order)
  const setBoxes = (boxes: BoxState[]) => setForm({ ...form, boxes })
  const submit = () => {
    setNotice(null)
    if (Object.keys(errors).length > 0) {
      setShowErrors(true)
      return
    }
    save.mutate(form)
  }
  const back = mode === 'edit' ? paths.order(orderId) : paths.orders
  const saveButton = (
    <Button onClick={submit} loading={save.isPending} block={isMobile}>
      {mode === 'create' ? t('orders.createOrder') : t('common.save')}
    </Button>
  )
  const shortCount = summary.total.items.filter((r) => r.amount > (available[r.item_code] ?? 0)).length

  const details = (
    <Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('orders.fields.customer')} className="sm:col-span-2">
          {() => (
            <>
              <CustomerPicker
                value={form.customer}
                invalid={Boolean(visibleErrors.customer)}
                onChange={(c) => setForm({ ...form, customer: c })}
              />
              {visibleErrors.customer && <p className="mt-1 text-xs text-red-700">{t(visibleErrors.customer)}</p>}
            </>
          )}
        </Field>
        <Field label={t('orders.fields.deliveryDate')}>
          {(id) => (
            <Input
              id={id}
              type="date"
              className="h-11 sm:h-10"
              value={form.delivery_date}
              onChange={(e) => setForm({ ...form, delivery_date: e.target.value })}
            />
          )}
        </Field>
        <Field label={t('orders.fields.driver')} hint={t('orders.driverHint')}>
          {(id) => (
            <Select
              id={id}
              className="h-11 sm:h-10"
              value={form.driver_id}
              onChange={(e) => setForm({ ...form, driver_id: e.target.value })}
            >
              <option value="">{t('orders.noDriver')}</option>
              {/* The current driver stays listed even if no longer active. */}
              {existing.data?.driver?.id &&
                !drivers.data?.some((d) => d.id === existing.data?.driver?.id) && (
                  <option value={existing.data.driver.id}>{existing.data.driver.full_name}</option>
                )}
              {drivers.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.full_name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={t('orders.fields.note')} className="sm:col-span-2">
          {(id) => (
            <textarea
              id={id}
              rows={2}
              maxLength={ORDER_NOTE_MAX_LENGTH}
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              placeholder={t('orders.notePlaceholder')}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-base text-stone-900 shadow-sm ring-1 ring-inset ring-stone-300 placeholder:text-stone-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 sm:text-sm"
            />
          )}
        </Field>
      </div>
    </Card>
  )

  const builder = (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-stone-900">{t('orders.boxes')}</h2>
        <div className="flex gap-2">
          {(['white', 'black'] as BoxColor[]).map((color) => (
            <Button key={color} variant="secondary" onClick={() => setBoxes([...form.boxes, emptyBox(color)])}>
              <Icon name="plus" width={16} height={16} />
              <BoxSwatch color={color} />
              {t(`orders.addBox.${color}`)}
            </Button>
          ))}
        </div>
      </div>
      {visibleErrors.boxes && <Alert tone="error">{t(visibleErrors.boxes)}</Alert>}
      {stock.isError && <Alert tone="error">{errorMessage(stock.error)}</Alert>}
      {form.boxes.map((box, index) => (
        <BoxCard
          key={box.key}
          box={box}
          index={index}
          items={itemList}
          available={available}
          errors={visibleErrors}
          onChange={(next) => setBoxes(form.boxes.map((b) => (b.key === box.key ? next : b)))}
          onDuplicate={() => {
            const copy = { ...box, key: newKey(), lines: box.lines.map((l) => ({ ...l, key: newKey() })) }
            const at = form.boxes.findIndex((b) => b.key === box.key)
            setBoxes([...form.boxes.slice(0, at + 1), copy, ...form.boxes.slice(at + 1)])
          }}
          onRemove={() => setBoxes(form.boxes.filter((b) => b.key !== box.key))}
        />
      ))}
    </div>
  )

  const messages = (
    <>
      {notice && <Alert tone="warning">{notice}</Alert>}
      {save.isError && getError(save.error).code !== 'ORDER_CONFLICT' && (
        <Alert tone="error">{errorMessage(save.error)}</Alert>
      )}
      {showErrors && Object.keys(errors).length > 0 && (
        <Alert tone="error">{t('orders.errors.fixHighlighted')}</Alert>
      )}
    </>
  )

  return (
    <>
      <PageHeader
        back={back}
        title={mode === 'create' ? t('orders.newTitle') : t('orders.editTitle')}
        subtitle={mode === 'edit' && existing.data ? existing.data.code : undefined}
      />
      {isMobile ? (
        <div className="space-y-4">
          {details}
          {builder}
          {messages}
          {/* Space so the bar never covers the last box. */}
          <div className={summaryOpen ? 'h-80' : 'h-28'} aria-hidden />
          <div
            className="fixed inset-x-0 z-20 border-t border-stone-200 bg-white/95 px-4 py-2 backdrop-blur"
            style={{ bottom: 'calc(3.6rem + env(safe-area-inset-bottom))' }}
          >
            <button
              type="button"
              onClick={() => setSummaryOpen(!summaryOpen)}
              aria-expanded={summaryOpen}
              className="mb-2 flex w-full items-center justify-between gap-2 text-sm font-medium text-stone-800"
            >
              <span className="flex items-center gap-2">
                {t('orders.summary')}
                <span className="tabular-nums text-stone-500">· {t('orders.boxesCount', { count: summary.total.boxes })}</span>
                {shortCount > 0 && <Icon name="alert" width={16} height={16} className="text-amber-600" />}
              </span>
              <Icon name="chevronRight" width={18} height={18} className={cx('transition', summaryOpen ? '-rotate-90' : 'rotate-90')} />
            </button>
            {summaryOpen && (
              <div className="mb-2 max-h-[45vh] overflow-y-auto">
                <OrderSummaryView summary={summary} available={available} />
              </div>
            )}
            {saveButton}
          </div>
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-4">
            {details}
            {builder}
            {messages}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => navigate(back)}>
                {t('common.cancel')}
              </Button>
              {saveButton}
            </div>
          </div>
          <aside className="lg:sticky lg:top-4">
            <Card title={t('orders.summary')}>
              <OrderSummaryView summary={summary} available={available} />
            </Card>
          </aside>
        </div>
      )}
    </>
  )
}
