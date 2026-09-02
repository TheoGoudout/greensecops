import { useQuery } from "@tanstack/react-query"
import { BillingService } from "@/client"
import type { QuotaReasons } from "@/lib/engine-actions"

/**
 * The allowances an organization has spent, as the refusals they would draw.
 *
 * Distinct from `GET /billing/usage`, which reports the *caller's* own
 * subscription: enforcement measures the org's billing **owner**, so a teammate
 * shown their own numbers would be greyed — or not greyed — against an
 * allowance they are not spending against.
 *
 * Returns `undefined` until the answer is in, which `engine-actions` reads as
 * "not known here" rather than "nothing left": a button must not go grey
 * because a query has not landed yet. The 402 is still the authority, and a
 * click that beats this query reads the same sentence it would have shown.
 */
export function useOrgQuotas(
  orgId: string | undefined,
): QuotaReasons | undefined {
  const { data } = useQuery({
    queryKey: ["quotas", orgId],
    queryFn: () => BillingService.getOrgQuotas({ orgId: orgId as string }),
    enabled: !!orgId,
    // Usage only moves when work is queued, and the pages that queue it
    // invalidate this key. A minute keeps a tab left open from re-asking on
    // every focus.
    staleTime: 60_000,
  })
  if (!data) return undefined
  return {
    analyses: data.analyses.exhausted_reason ?? null,
    fixes: data.fixes.exhausted_reason ?? null,
  }
}
