import type { Cell, Row, Worksheet } from 'exceljs'

/**
 * Delivery note as an Excel file, built in the browser from public/templates/delivery_note_template.xlsx
 * and downloaded straight away: nothing is generated or stored on the server. No React in here.
 *
 * Template layout (sheet "Delivery Note"): supplier B3 name · B4 tel · B5 address; customer B7 name ·
 * B8 tel · B9–B10 address; F7 date; item rows from row 13 (A no. · C description · D unit), the
 * ISSUED BY / CONFIRMED BY blocks right below the table.
 */

export const TEMPLATE_URL = '/templates/delivery_note_template.xlsx'
const XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

const FIRST_ITEM_ROW = 13
/** Item rows the template ships with (styled, numbered 1 and 2). */
const TEMPLATE_ITEM_ROWS = 2
/** Characters that fit across B–D (the customer address, before it continues on row 10). */
const ADDRESS_LINE_CHARS = 52
const MAX_NAME_CHARS = 80

export interface DeliveryNoteParty {
  name: string
  phone: string
  address: string
}

export interface DeliveryNoteInput {
  /** Order number, used in the file name. */
  orderCode: string
  /** The order date as it should read in the sheet (F7). */
  date: string
  /** The order date as YYYY-MM-DD, used in the file name. */
  dateIso: string
  /** The current workspace's business info. */
  supplier: DeliveryNoteParty
  /** The order's customer. */
  customer: DeliveryNoteParty
  /** Name and unit label of each item, in the order they print. */
  items: { name: string; unit: string }[]
  /** UI language: only decides where long Khmer / English addresses may break. */
  lang: 'km' | 'en'
  /** In a Telegram WebView, offer the file through the share sheet first (downloads are often blocked). */
  preferShare?: boolean
}

export type ExportErrorCode = 'noSupplier' | 'noCustomer' | 'noItems' | 'template' | 'build'

export class ExportError extends Error {
  constructor(
    readonly code: ExportErrorCode,
    readonly detail?: unknown,
  ) {
    super(code)
    this.name = 'ExportError'
  }
}

export async function exportDeliveryNoteXlsx(input: DeliveryNoteInput): Promise<void> {
  if (!input.supplier.name.trim()) throw new ExportError('noSupplier')
  if (!input.customer.name.trim() && !input.customer.phone.trim()) throw new ExportError('noCustomer')
  if (input.items.length === 0) throw new ExportError('noItems')

  let template: ArrayBuffer
  try {
    const response = await fetch(TEMPLATE_URL, { cache: 'no-cache' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    template = await response.arrayBuffer()
  } catch (cause) {
    throw new ExportError('template', cause)
  }

  let buffer: ArrayBuffer
  try {
    const { default: ExcelJS } = await import('exceljs')
    const workbook = new ExcelJS.Workbook()
    await workbook.xlsx.load(template)
    const sheet = workbook.getWorksheet('Delivery Note') ?? workbook.worksheets[0]
    if (!sheet) throw new Error('The template has no sheet')
    fill(sheet, input)
    buffer = (await workbook.xlsx.writeBuffer()) as ArrayBuffer
  } catch (cause) {
    throw new ExportError('build', cause)
  }

  const blob = new Blob([buffer], { type: XLSX_MIME })
  await saveFile(blob, fileName(input), input.preferShare ?? false)
}

// --- Filling the sheet ---------------------------------------------------------------------------

function fill(sheet: Worksheet, input: DeliveryNoteInput) {
  const { supplier, customer } = input
  put(sheet.getCell('B3'), supplier.name)
  put(sheet.getCell('B4'), supplier.phone)
  put(sheet.getCell('B5'), oneLine(supplier.address))

  put(sheet.getCell('B7'), customer.name)
  put(sheet.getCell('B8'), customer.phone)
  const [first, second] = addressLines(customer.address, input.lang)
  put(sheet.getCell('B9'), first)
  put(sheet.getCell('B10'), second)
  put(sheet.getCell('F7'), input.date)
  // Ref. Invoice (F8) and Ref. PO (F9) stay blank.

  fillItems(sheet, input.items)
}

function fillItems(sheet: Worksheet, items: DeliveryNoteInput['items']) {
  const extra = items.length - TEMPLATE_ITEM_ROWS
  if (extra > 0) insertItemRows(sheet, FIRST_ITEM_ROW + TEMPLATE_ITEM_ROWS, extra)

  items.forEach((item, i) => {
    const row = sheet.getRow(FIRST_ITEM_ROW + i)
    row.getCell('A').value = i + 1
    put(row.getCell('C'), item.name)
    put(row.getCell('D'), item.unit)
  })
  // Fewer items than the template's sample rows: clear their leftover numbers.
  for (let i = items.length; i < TEMPLATE_ITEM_ROWS; i++) {
    sheet.getRow(FIRST_ITEM_ROW + i).getCell('A').value = null
  }
}

/**
 * Insert `count` rows at `at` (just after the last item row), styled like the first item row.
 * Everything below shifts down; ExcelJS doesn't move merged ranges when it splices, so they're
 * taken off first and put back moved.
 */
function insertItemRows(sheet: Worksheet, at: number, count: number) {
  const merges = [...Object.values(sheet.model.merges ?? {})].map(String)
  merges.forEach((range) => sheet.unMergeCells(range))

  sheet.spliceRows(at, 0, ...Array.from({ length: count }, () => []))

  const source = sheet.getRow(FIRST_ITEM_ROW)
  for (let r = at; r < at + count; r++) copyRowStyle(source, sheet.getRow(r))

  merges.forEach((range) => sheet.mergeCells(shiftRange(range, at, count)))
}

function copyRowStyle(from: Row, to: Row) {
  if (from.height != null) to.height = from.height
  from.eachCell({ includeEmpty: true }, (cell: Cell, col: number) => {
    to.getCell(col).style = structuredClone(cell.style)
  })
}

/** "A18:B19" → rows at or below `at` move down by `count`. */
function shiftRange(range: string, at: number, count: number): string {
  return range.replace(/([A-Z]+)(\d+)/g, (_, col: string, row: string) => {
    const n = Number(row)
    return `${col}${n >= at ? n + count : n}`
  })
}

// --- Text ----------------------------------------------------------------------------------------

function oneLine(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .join(', ')
}

const KHMER = /[ក-៿᧠-᧿]/
const KHMER_FONT = 'Khmer OS Siemreap'

/** Set a cell's text; Khmer text gets Khmer OS Siemreap (the rest of the cell's font is kept). */
function put(cell: Cell, value: string) {
  cell.value = value
  if (KHMER.test(value)) cell.font = { ...cell.font, name: KHMER_FONT }
}

/** The customer address over B9 and B10: its own line break, else split at a word near the width. */
function addressLines(address: string, lang: 'km' | 'en'): [string, string] {
  const lines = address
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines.length > 1) return [lines[0], lines.slice(1).join(', ')]
  const text = lines[0] ?? ''
  if (text.length <= ADDRESS_LINE_CHARS) return [text, '']

  // Khmer has no spaces: break between dictionary words (never inside a character cluster).
  const words = wordsOf(text, lang)
  let head = ''
  for (const word of words) {
    if (head && head.length + word.length > ADDRESS_LINE_CHARS) break
    head += word
  }
  return [head.trimEnd(), text.slice(head.length).trim()]
}

/** Words of a text (Intl.Segmenter knows Khmer's), or its characters where it's missing. */
function wordsOf(text: string, lang: string): string[] {
  type Segmenter = new (locale: string, options: { granularity: 'word' }) => {
    segment(input: string): Iterable<{ segment: string }>
  }
  const Segmenter = (Intl as unknown as { Segmenter?: Segmenter }).Segmenter
  if (!Segmenter) return Array.from(text)
  return Array.from(new Segmenter(lang, { granularity: 'word' }).segment(text), (part) => part.segment)
}

// --- File ----------------------------------------------------------------------------------------

/** DeliveryNote_<customer>_<order number>_<YYYY-MM-DD>.xlsx; Khmer letters are fine. */
export function fileName({ customer, orderCode, dateIso }: DeliveryNoteInput): string {
  const clean = (text: string) =>
    // eslint-disable-next-line no-control-regex
    text.replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ').replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '')
  const name = clean(customer.name).slice(0, MAX_NAME_CHARS) || 'Direct order'
  return `DeliveryNote_${name}_${clean(orderCode)}_${dateIso}.xlsx`.replace(/ /g, '_')
}

async function saveFile(blob: Blob, name: string, preferShare: boolean): Promise<void> {
  if (preferShare) {
    const file = new File([blob], name, { type: XLSX_MIME })
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file] })
        return
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return // closed the sheet
        // Blocked (no user gesture left, unsupported): fall back to the download link.
      }
    }
  }
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Some browsers start the download a tick later: revoke after it has begun.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
