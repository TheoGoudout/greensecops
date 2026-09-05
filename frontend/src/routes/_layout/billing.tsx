import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"
import type {
  OssApplicationPublic,
  PlanPublic,
  SubscriptionStatus,
  UsagePublic,
  UserTier,
} from "@/client"
import { BillingService } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatLongDate } from "@/lib/format"
import { handleApiError, showSuccessToast } from "@/lib/toast"

export const Route = createFileRoute("/_layout/billing")({
  component: Billing,
  head: () => ({
    meta: [{ title: "Billing - GreenSecOps" }],
  }),
})

/**
 * Payment state, as the user should read it. `past_due` is deliberately not
 * alarming: the plan is still working in full and the account has days to fix
 * it, which is exactly what the grace period is for.
 */
const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  incomplete: "Awaiting payment",
  trialing: "Trial",
  active: "Active",
  past_due: "Payment failed",
  unpaid: "Unpaid",
  pending_cancellation: "Cancels at period end",
  canceled: "Cancelled",
}

const STATUS_VARIANTS: Record<
  SubscriptionStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  incomplete: "outline",
  trialing: "secondary",
  active: "default",
  past_due: "destructive",
  unpaid: "destructive",
  pending_cancellation: "secondary",
  canceled: "outline",
}

const ENGINE_LABELS: Record<string, string> = {
  workflow: "CI workflows",
  terraform: "Terraform",
  docker: "Docker",
  cloud: "Cloud posture",
  telemetry: "CI telemetry",
  carryover: "Earlier this period",
}

const METER_LABELS: Record<string, string> = {
  analyses: "Analyses",
  fixes: "AI fixes",
}

function formatDate(value?: string | null): string {
  if (!value) return "—"
  return formatLongDate(value)
}

function formatMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: currency.toUpperCase(),
  }).format(cents / 100)
}

function daysUntil(value?: string | null): number {
  if (!value) return 0
  const ms = new Date(value).getTime() - Date.now()
  return Math.max(Math.ceil(ms / 86_400_000), 0)
}

function UsageBar({
  used,
  limit,
  label,
}: {
  used: number
  limit: number | null | undefined
  label: string
}) {
  const isUnlimited = limit === null || limit === undefined
  const pct = !isUnlimited ? Math.min((used / limit) * 100, 100) : 0

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">
          {used.toLocaleString()}{" "}
          <span className="text-muted-foreground font-normal">
            / {isUnlimited ? "∞" : limit.toLocaleString()}
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

/**
 * The banner that appears when payment has failed or the grace period has
 * closed. Leads with what still works, because the most useful thing to say
 * about a failed payment is that nothing has been deleted.
 */
function PaymentStateBanner({
  status,
  graceExpiresAt,
  tier,
  onManage,
  canManage,
}: {
  status: SubscriptionStatus
  graceExpiresAt?: string | null
  tier: UserTier
  onManage: () => void
  canManage: boolean
}) {
  if (status !== "past_due" && status !== "unpaid") return null

  const remaining = daysUntil(graceExpiresAt)
  const isGrace = status === "past_due"

  return (
    <div
      role="alert"
      className={`rounded-lg border p-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between ${
        isGrace
          ? "border-orange-500/50 bg-orange-500/10"
          : "border-destructive/50 bg-destructive/10"
      }`}
    >
      <div className="flex flex-col gap-1">
        <span className="font-medium">
          {isGrace
            ? "We could not take your last payment"
            : "Your account is on Free plan limits"}
        </span>
        <span className="text-sm text-muted-foreground">
          {isGrace
            ? `Your ${tier} plan is still working in full. You have ${remaining} day${
                remaining === 1 ? "" : "s"
              } to update your payment details — until ${formatDate(
                graceExpiresAt,
              )}.`
            : "Your plan will be restored the moment a payment succeeds. Nothing has been deleted."}
        </span>
      </div>
      {canManage && (
        <Button
          size="sm"
          variant={isGrace ? "outline" : "destructive"}
          onClick={onManage}
          className="shrink-0"
        >
          Update payment method
        </Button>
      )}
    </div>
  )
}

function PlanCard({
  plan,
  isCurrent,
  isDowngrade,
  onSelect,
  pending,
}: {
  plan: PlanPublic
  isCurrent: boolean
  isDowngrade: boolean
  onSelect: (tier: UserTier) => void
  pending: boolean
}) {
  return (
    <Card className={isCurrent ? "border-primary" : undefined}>
      <CardHeader className="pb-2">
        <div className="flex items-baseline justify-between gap-2">
          <CardTitle className="text-base">{plan.name}</CardTitle>
          <span className="text-sm font-medium">{plan.price_display}</span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">{plan.tagline}</p>
        <ul className="text-sm flex flex-col gap-1">
          <li>
            {plan.limits.analyses === null
              ? "Unlimited analyses"
              : `${plan.limits.analyses?.toLocaleString()} analyses / month`}
          </li>
          <li>
            {plan.limits.fixes === null
              ? "Unlimited AI fixes"
              : `${plan.limits.fixes?.toLocaleString()} AI fixes / month`}
          </li>
          <li>
            {plan.public_repos_only
              ? "Unlimited public repositories"
              : plan.limits.repos === null
                ? "Unlimited repositories"
                : `${plan.limits.repos?.toLocaleString()} repositories`}
          </li>
        </ul>
        {isCurrent ? (
          <Badge variant="secondary" className="w-fit">
            Current plan
          </Badge>
        ) : plan.is_purchasable ? (
          <Button
            size="sm"
            variant="outline"
            className="w-fit"
            disabled={pending}
            onClick={() => onSelect(plan.tier)}
          >
            {isDowngrade ? "Downgrade" : "Upgrade"} to {plan.name}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}

function UsageBreakdown({ usage }: { usage: UsagePublic }) {
  const rows = usage.breakdown ?? []
  if (rows.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">Where it went</span>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Meter</TableHead>
            <TableHead>Engine</TableHead>
            <TableHead className="text-right">Used</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${row.meter}-${row.engine}`}>
              <TableCell>{METER_LABELS[row.meter] ?? row.meter}</TableCell>
              <TableCell>{ENGINE_LABELS[row.engine] ?? row.engine}</TableCell>
              <TableCell className="text-right">
                {row.quantity.toLocaleString()}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function OssApplicationForm({
  applications,
}: {
  applications: OssApplicationPublic[]
}) {
  const queryClient = useQueryClient()
  const [repoUrl, setRepoUrl] = useState("")
  const [license, setLicense] = useState("")
  const [justification, setJustification] = useState("")

  const pendingApplication = applications.find((a) => a.status === "pending")
  const latest = applications[0]

  const mutation = useMutation({
    mutationFn: () =>
      BillingService.createOssApplication({
        requestBody: {
          repo_url: repoUrl,
          license_name: license,
          justification,
        },
      }),
    onSuccess: () => {
      showSuccessToast("Application submitted — we'll be in touch.")
      setRepoUrl("")
      setLicense("")
      setJustification("")
      queryClient.invalidateQueries({ queryKey: ["billing", "oss"] })
    },
    onError: handleApiError,
  })

  if (pendingApplication) {
    return (
      <p className="text-sm text-muted-foreground">
        Your application for <strong>{pendingApplication.repo_url}</strong> is
        under review. We'll email you when it's been looked at.
      </p>
    )
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        mutation.mutate()
      }}
    >
      {latest?.status === "rejected" && (
        <p className="text-sm text-muted-foreground">
          Your last application was declined
          {latest.review_note ? `: ${latest.review_note}` : "."} You're welcome
          to apply again.
        </p>
      )}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oss-repo">Repository URL</Label>
        <Input
          id="oss-repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="https://github.com/org/project"
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oss-license">Licence</Label>
        <Input
          id="oss-license"
          value={license}
          onChange={(e) => setLicense(e.target.value)}
          placeholder="MIT, Apache-2.0, …"
          required
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="oss-why">Why does this project qualify?</Label>
        <Input
          id="oss-why"
          value={justification}
          onChange={(e) => setJustification(e.target.value)}
          placeholder="A sentence or two about the project"
          required
        />
      </div>
      <Button
        type="submit"
        size="sm"
        variant="outline"
        className="w-fit"
        disabled={mutation.isPending}
      >
        Apply for the Open Source plan
      </Button>
    </form>
  )
}

function Billing() {
  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: BillingService.getSubscription,
  })
  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ["billing", "usage"],
    queryFn: BillingService.getUsage,
  })
  const { data: plans } = useQuery({
    queryKey: ["billing", "plans"],
    queryFn: BillingService.listPlans,
  })
  const { data: invoices } = useQuery({
    queryKey: ["billing", "invoices"],
    queryFn: BillingService.listInvoices,
  })
  const { data: ossApplications } = useQuery({
    queryKey: ["billing", "oss"],
    queryFn: BillingService.listOssApplications,
  })

  // Every way of choosing a plan ends on a page hosted by Stripe, so this only
  // ever navigates. A new subscription is a Checkout session; a change to a
  // live one is the Customer Portal's confirmation flow, which names the
  // amount due today for an upgrade and the date the cheaper plan starts for a
  // downgrade. Both are deliberate: money moving is confirmed where the terms
  // are shown, not on a button here, and card details never touch this app.
  const checkout = useMutation({
    mutationFn: (tier: UserTier) =>
      BillingService.createCheckoutSession({ requestBody: { tier } }),
    onSuccess: (data) => {
      window.location.href = data.url
    },
    onError: handleApiError,
  })
  const portal = useMutation({
    mutationFn: () => BillingService.createPortalSession(),
    onSuccess: (data) => {
      window.location.href = data.url
    },
    onError: handleApiError,
  })

  const isLoading = subLoading || usageLoading
  const status = subscription?.status ?? "active"
  const currentTier = subscription?.tier ?? "free"
  const effectiveTier = subscription?.effective_tier ?? currentTier
  const billingEnabled = subscription?.billing_enabled ?? false
  const currentPlan = plans?.find((p) => p.tier === currentTier)
  // Which direction a plan card's button moves the account, by price. Price is
  // the ladder the catalog already orders the plans by, and the only plans that
  // render a button are the purchasable ones, so this never has to rank the two
  // $0 plans against each other — Free and Open Source both show no button.
  // Falling back to 0 means "everything is an upgrade", which is what an
  // account whose tier is missing from the catalog should see.
  const currentPriceCents = currentPlan?.price_cents ?? 0
  // A plan the user bought but is not currently getting, because payment
  // lapsed. Worth naming explicitly rather than silently showing the lower one.
  const isDowngraded = effectiveTier !== currentTier

  // Nothing local changes on a click any more — the answer is a URL to visit,
  // and the plan itself only moves once Stripe's webhook says it did.
  const handleSelectPlan = (tier: UserTier) => checkout.mutate(tier)

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Billing</h1>
        <p className="text-muted-foreground">Your plan and usage.</p>
      </div>

      {subscription && (
        <PaymentStateBanner
          status={status}
          graceExpiresAt={subscription.grace_expires_at}
          tier={currentTier}
          onManage={() => portal.mutate()}
          canManage={billingEnabled}
        />
      )}

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
                    {currentPlan?.name ?? currentTier}
                  </span>
                  <span className="text-sm text-muted-foreground">
                    {currentPlan?.price_display ?? ""}
                  </span>
                  <Badge
                    variant={STATUS_VARIANTS[status]}
                    className="ml-auto text-xs"
                  >
                    {STATUS_LABELS[status]}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {currentPlan?.tagline ?? ""}
                </p>
                {isDowngraded && (
                  <p className="text-sm text-destructive">
                    Currently limited to{" "}
                    {plans?.find((p) => p.tier === effectiveTier)?.name ??
                      effectiveTier}{" "}
                    allowances until payment succeeds.
                  </p>
                )}
                {subscription?.cancel_at_period_end && (
                  <p className="text-sm text-muted-foreground">
                    Cancels on {formatDate(subscription.period_end)}. You keep
                    this plan until then.
                  </p>
                )}
                {billingEnabled && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-fit mt-1"
                    disabled={portal.isPending}
                    onClick={() => portal.mutate()}
                  >
                    Manage subscription
                  </Button>
                )}
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
                  used={usage?.analyses_used ?? 0}
                  limit={usage?.limits.analyses}
                />
                <UsageBar
                  label="AI Fixes"
                  used={usage?.fixes_used ?? 0}
                  limit={usage?.limits.fixes}
                />
                <UsageBar
                  label="Repositories"
                  used={usage?.repos_used ?? 0}
                  limit={usage?.limits.repos}
                />
                <p className="text-xs text-muted-foreground">
                  Resets on {formatDate(usage?.period_end)}. Analyses cover
                  workflows, Terraform, Docker, cloud and CI telemetry.
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {usage && (usage.breakdown?.length ?? 0) > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Usage breakdown
            </CardTitle>
          </CardHeader>
          <CardContent>
            <UsageBreakdown usage={usage} />
          </CardContent>
        </Card>
      )}

      {plans && plans.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold">Plans</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {plans.map((plan) => (
              <PlanCard
                key={plan.tier}
                plan={plan}
                isCurrent={plan.tier === currentTier}
                isDowngrade={plan.price_cents < currentPriceCents}
                onSelect={handleSelectPlan}
                pending={checkout.isPending}
              />
            ))}
          </div>
        </div>
      )}

      {invoices && invoices.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Invoices
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>Number</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoices.map((invoice) => (
                  <TableRow key={invoice.id}>
                    <TableCell>{formatDate(invoice.created_at)}</TableCell>
                    <TableCell>{invoice.number ?? "—"}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          invoice.status === "paid" ? "default" : "secondary"
                        }
                      >
                        {invoice.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {formatMoney(
                        invoice.amount_due_cents,
                        invoice.currency ?? "usd",
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {invoice.hosted_invoice_url && (
                        <a
                          className="text-primary text-sm underline"
                          href={invoice.hosted_invoice_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View
                        </a>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {currentTier !== "open_source" && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Open source
            </CardTitle>
          </CardHeader>
          <CardContent>
            <OssApplicationForm applications={ossApplications ?? []} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
