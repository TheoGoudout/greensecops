/**
 * Date formatting, in one place.
 *
 * `relativeTime` used to live in `lib/engine-meta.ts` — a module about which
 * icon and blurb each analysis engine gets — while route files inlined their
 * own `toLocaleDateString(undefined, {...})` with slightly different option
 * objects. Same job, several spellings, and no way to change how the product
 * shows a timestamp without finding them all.
 *
 * The two absolute shapes below are the ones the UI actually uses; they are
 * reproduced exactly as their call sites had them, so nothing a user sees moves.
 */

/** Short timestamp without a year: "3 Feb, 14:05". For recent activity. */
export function formatDateTime(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** Full date, no time: "3 February 2026". For billing periods. */
export function formatLongDate(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
    year: "numeric",
  })
}

/** A short relative-time string ("3h ago"), or "never" for a missing date. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never"
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return "never"
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  return months < 12 ? `${months}mo ago` : `${Math.round(months / 12)}y ago`
}
