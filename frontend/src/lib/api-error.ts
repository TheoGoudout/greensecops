import { ApiError } from "@/client"

/**
 * A structured billing refusal (HTTP 402/503), as raised by
 * `backend/app/services/billing/errors.py`. `message` is always a complete
 * sentence naming what was used, the cap, when it resets and what to do next,
 * so a caller that only knows how to print a string still shows something
 * useful.
 */
type BillingErrorDetail = {
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
 * Whatever the API said, in the shape it said it.
 *
 * The three shapes a FastAPI `detail` arrives in — a validation array, a
 * billing refusal object, a plain string — read out here once, so a caller
 * cannot handle two of them and quietly drop the third.
 */
function detailMessage(errDetail: unknown): string | undefined {
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return String((errDetail[0] as { msg?: unknown })?.msg ?? "") || undefined
  }
  // Billing refusals send an object, not a string. Without this branch they
  // rendered as "[object Object]" — the least useful possible version of a
  // message that was written to be actionable.
  if (isBillingErrorDetail(errDetail)) {
    return errDetail.message
  }
  return typeof errDetail === "string" && errDetail ? errDetail : undefined
}

/** The best human-readable message an ApiError carries. */
export function extractErrorMessage(err: ApiError): string {
  return (
    detailMessage((err.body as { detail?: unknown })?.detail) ??
    "Something went wrong."
  )
}

/**
 * The message to show under an action's own failure title, if the API sent one.
 *
 * Used by every "Scan now" / "Generate fixes" / "Open PR" button, whose toast
 * supplies its own title and puts this underneath. It used to accept only a
 * plain-string `detail`, so a quota refusal — which arrives as an *object*
 * carrying a sentence naming what was used, the cap, when it resets and what
 * to do next — returned `undefined` and the user saw "Could not queue scan"
 * and nothing else. The most useful message the API sends was the one message
 * these buttons could not show.
 *
 * Still `undefined` when there is genuinely nothing to add: the caller's title
 * already says what failed, and a generic sentence under it is noise.
 */
export function apiErrorDetail(error: unknown): string | undefined {
  if (error instanceof ApiError) {
    return detailMessage((error.body as { detail?: unknown })?.detail)
  }
  return undefined
}
