import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { CheckCircle2, Zap } from "lucide-react"
import type { UserTier } from "@/client"
import { BillingService } from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

export const Route = createFileRoute("/_layout/billing")({
  component: Billing,
  head: () => ({
    meta: [{ title: "Billing - GreenSecOps" }],
  }),
})

const TIER_LABELS: Record<UserTier, string> = {
  free: "Free",
  starter: "Starter",
  pro: "Pro",
  ultimate: "Ultimate",
  open_source: "Open Source",
}

const TIER_PRICES: Record<UserTier, string> = {
  free: "$0/mo",
  starter: "$19/mo",
  pro: "$79/mo",
  ultimate: "$299/mo",
  open_source: "Free",
}

const UPGRADE_ORDER: UserTier[] = ["free", "starter", "pro", "ultimate"]

function UsageBar({
  used,
  limit,
  label,
}: {
  used: number
  limit: number | null
  label: string
}) {
  const pct = limit !== null ? Math.min((used / limit) * 100, 100) : 0
  const isUnlimited = limit === null

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">
          {used.toLocaleString()}{" "}
          <span className="text-muted-foreground font-normal">
            / {isUnlimited ? "∞" : limit!.toLocaleString()}
          </span>
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        {!isUnlimited && (
          <div
            className={`h-full rounded-full transition-all ${
              pct >= 90
                ? "bg-destructive"
                : pct >= 70
                  ? "bg-orange-500"
                  : "bg-primary"
            }`}
            style={{ width: `${pct}%` }}
          />
        )}
        {isUnlimited && (
          <div className="h-full rounded-full bg-primary/30 w-full" />
        )}
      </div>
    </div>
  )
}

function Billing() {
  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: BillingService.getSubscription,
  })

  type TierLimits = {
    tier: UserTier
    limits: {
      analyses: number | null
      fixes: number | null
      repos: number | null
    }
  }
  const { data: limitsRaw, isLoading: limitsLoading } = useQuery({
    queryKey: ["billing", "limits"],
    queryFn: BillingService.getTierLimits,
  })
  const limitsData = limitsRaw as TierLimits | undefined

  const currentTier = subscription?.tier ?? "free"
  const isLoading = subLoading || limitsLoading

  const upgradeTargets = UPGRADE_ORDER.filter(
    (t) => UPGRADE_ORDER.indexOf(t) > UPGRADE_ORDER.indexOf(currentTier),
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Billing</h1>
        <p className="text-muted-foreground">
          Manage your subscription and monitor usage
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground font-normal">
              Current plan
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <div className="flex items-baseline gap-3">
                <span className="text-2xl font-bold">
                  {TIER_LABELS[currentTier]}
                </span>
                <span className="text-muted-foreground text-sm">
                  {TIER_PRICES[currentTier]}
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-muted-foreground font-normal">
              Billing period
            </CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <Skeleton className="h-8 w-40" />
            ) : subscription?.period_start && subscription.period_end ? (
              <p className="text-sm font-medium">
                {new Date(subscription.period_start).toLocaleDateString()} –{" "}
                {new Date(subscription.period_end).toLocaleDateString()}
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">No active period</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Usage this period</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {isLoading ? (
            <>
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </>
          ) : (
            <>
              <UsageBar
                label="Analyses"
                used={subscription?.analyses_used ?? 0}
                limit={limitsData?.limits.analyses ?? null}
              />
              <UsageBar
                label="AI Fixes"
                used={subscription?.fixes_used ?? 0}
                limit={limitsData?.limits.fixes ?? null}
              />
              <UsageBar
                label="Repositories"
                used={0}
                limit={limitsData?.limits.repos ?? null}
              />
            </>
          )}
        </CardContent>
      </Card>

      {upgradeTargets.length > 0 && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              Upgrade your plan
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {upgradeTargets.map((tier) => (
                <div
                  key={tier}
                  className="flex flex-col gap-3 rounded-lg border p-4"
                >
                  <div>
                    <p className="font-semibold">{TIER_LABELS[tier]}</p>
                    <p className="text-sm text-muted-foreground">
                      {TIER_PRICES[tier]}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant={tier === "pro" ? "default" : "outline"}
                    className="gap-1.5"
                    disabled
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Upgrade to {TIER_LABELS[tier]}
                  </Button>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-4">
              Stripe billing integration coming soon.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
