import { AxiosError } from "axios"
import { toast } from "sonner"
import { ApiError } from "./client"

/**
 * A structured billing refusal (HTTP 402/503), as raised by
 * `backend/app/services/billing/errors.py`. `message` is always a complete
 * sentence naming what was used, the cap, when it resets and what to do next,
 * so a caller that only knows how to print a string still shows something
 * useful.
 */
export type BillingErrorDetail = {
  code: string
  message: string
  meter?: string
  engine?: string | null
  tier?: string
  plan?: string
  limit?: number
  used?: number
  requested?: number
  remaining?: number
  resets_at?: string | null
  upgrade_url?: string
  feature?: string
}

function isBillingErrorDetail(value: unknown): value is BillingErrorDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as BillingErrorDetail).code === "string" &&
    typeof (value as BillingErrorDetail).message === "string"
  )
}

/**
 * The structured billing detail behind an error, if it is one.
 *
 * Lets a caller render an Upgrade button pointed at the right plan instead of
 * pattern-matching prose out of a string.
 */
export function billingErrorDetail(
  error: unknown,
): BillingErrorDetail | undefined {
  if (!(error instanceof ApiError)) return undefined
  const detail = (error.body as { detail?: unknown })?.detail
  return isBillingErrorDetail(detail) ? detail : undefined
}

function extractErrorMessage(err: ApiError): string {
  if (err instanceof AxiosError) {
    return err.message
  }

  const errDetail = (err.body as any)?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return errDetail[0].msg
  }
  // Billing refusals send an object, not a string. Without this branch they
  // rendered as "[object Object]" — the least useful possible version of a
  // message that was written to be actionable.
  if (isBillingErrorDetail(errDetail)) {
    return errDetail.message
  }
  return errDetail || "Something went wrong."
}

export function showSuccessToast(description: string) {
  toast.success("Success!", { description })
}

export function showErrorToast(description: string) {
  toast.error("Something went wrong!", { description })
}

/** Show the standard error toast with the message extracted from an ApiError. */
export function handleApiError(err: ApiError) {
  showErrorToast(extractErrorMessage(err))
}

export function apiErrorDetail(error: unknown): string | undefined {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown })?.detail
    if (typeof detail === "string") return detail
  }
  return undefined
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}
