import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
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

const TIER_DESCRIPTIONS: Record<UserTier, string> = {
  free: "Great for personal projects and trying out GreenSecOps.",
  starter: "For small teams with more repositories and analyses.",
  pro: "For growing teams that need advanced features.",
  ultimate: "Unlimited access for large organizations.",
  open_source: "Free for qualifying open source projects.",
}

const TIER_PRICES: Record<UserTier, string> = {
  free: "$0/mo",
  starter: "$19/mo",
  pro: "$79/mo",
  ultimate: "$299/mo",
  open_source: "Free",
}

function UsageBar({
  used,
  limit,
  label,
}: {
  used: number
  limit: number | null
  label: string
}) {
  const isUnlimited = limit === null
  const pct = !isUnlimited ? Math.min((used / limit!) * 100, 100) : 0

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
        {!isUnlimited ? (
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
        ) : (
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

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Billing</h1>
        <p className="text-muted-foreground">Your plan and usage.</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Current plan
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {isLoading ? (
              <Skeleton className="h-8 w-24" />
            ) : (
              <>
                <div className="flex items-baseline gap-3">
                  <span className="text-2xl font-bold">
                    {TIER_LABELS[currentTier]}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {TIER_PRICES[currentTier]}
                  </span>
                  <span className="ml-auto text-xs font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    Active
                  </span>
                </div>
                <p className="text-sm text-muted-foreground">
                  {TIER_DESCRIPTIONS[currentTier]}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Usage this period
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
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
                  used={subscription?.repos_used ?? 0}
                  limit={limitsData?.limits.repos ?? null}
                />
                <Button
                  variant="outline"
                  size="sm"
                  className="w-fit mt-1"
                  disabled
                >
                  Manage subscription
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
