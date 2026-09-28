import { ClientError } from '@/lib/errors'
import {
  PARTNER_LOCATION_MAX_LENGTH,
  PARTNER_NAME_MAX_LENGTH,
  PHONE_MAX_DIGITS,
  PHONE_MIN_DIGITS,
} from '@/lib/types'

export type PartnerField = 'name' | 'location' | 'phone'

export interface PartnerFormValues {
  name: string
  location: string
  phone: string
}

/** Same rules as the API's normalization, so the stored value matches what the user sees. */
export function normalizeName(value: string) {
  return value.replace(/\s+/g, ' ').trim()
}

/** Strip spaces, dashes, dots and parentheses; keep an optional leading +. */
export function compactPhone(value: string) {
  return value.replace(/[\s\-.()]+/g, '')
}

const PHONE_RE = new RegExp(`^\\+?\\d{${PHONE_MIN_DIGITS},${PHONE_MAX_DIGITS}}$`)

/**
 * Client-side checks mirroring the API. Errors use the same codes the server would send
 * (INVALID_PHONE) plus client codes for field-level messages the server reports as
 * VALIDATION_ERROR (NAME_REQUIRED, FIELD_TOO_LONG).
 */
export function validatePartner(values: PartnerFormValues): Partial<Record<PartnerField, ClientError>> {
  const errors: Partial<Record<PartnerField, ClientError>> = {}
  const name = normalizeName(values.name)
  if (!name) errors.name = new ClientError('NAME_REQUIRED')
  else if (name.length > PARTNER_NAME_MAX_LENGTH) {
    errors.name = new ClientError('FIELD_TOO_LONG', { max: PARTNER_NAME_MAX_LENGTH })
  }
  if (values.location.trim().length > PARTNER_LOCATION_MAX_LENGTH) {
    errors.location = new ClientError('FIELD_TOO_LONG', { max: PARTNER_LOCATION_MAX_LENGTH })
  }
  const phone = compactPhone(values.phone)
  if (phone && !PHONE_RE.test(phone)) {
    errors.phone = new ClientError('INVALID_PHONE', {
      min_digits: PHONE_MIN_DIGITS,
      max_digits: PHONE_MAX_DIGITS,
    })
  }
  return errors
}

/** Request body: empty location / phone are sent as null (the API stores NULL either way). */
export function toPayload(values: PartnerFormValues) {
  return {
    name: normalizeName(values.name),
    location: values.location.trim() || null,
    phone: values.phone.trim() || null,
  }
}
