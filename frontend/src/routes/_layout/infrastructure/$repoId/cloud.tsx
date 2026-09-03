import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Plus,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { CloudAccountPublic } from "@/client"
import { CloudService } from "@/client"
import { CloudFindingRow } from "@/components/CloudFindingRow"
import { ConfirmRemoveDialog } from "@/components/ConfirmRemoveDialog"
import { EngineActionBar, overflowItem } from "@/components/EngineActionBar"
import { EngineFlowRail } from "@/components/EngineFlowRail"
import { GradeBadge } from "@/components/GradeBadge"
import { ScanRunningBadge } from "@/components/ScanRunningBadge"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import { useOrgQuotas } from "@/hooks/useOrgQuotas"
import { useRepository } from "@/hooks/useRepository"
import { apiErrorDetail } from "@/lib/api-error"
import {
  type EngineActionInput,
  engineActions,
  type QuotaReasons,
  removeAction,
} from "@/lib/engine-actions"
import { pollForActivity } from "@/lib/scan-polling"
import {
  cloudAccountStatusColor,
  cloudAccountStatusLabel,
  scanStatusColor,
  scanStatusLabel,
} from "@/lib/status-colors"

export const Route = createFileRoute("/_layout/infrastructure/$repoId/cloud")({
  component: CloudTab,
  head: () => ({
    meta: [{ title: "Cloud - GreenSecOps" }],
  }),
})

function CloudTab() {
  const { repoId } = Route.useParams()
  const queryClient = useQueryClient()
  const { repo, isLoading: repoLoading } = useRepository(repoId)
  const orgId = repo?.org_id
  // Cloud has no fixes, so the only allowance it can spend is analyses.
  const quota = useOrgQuotas(orgId)

  const [displayName, setDisplayName] = useState("")
  const [roleArn, setRoleArn] = useState("")
  const [regions, setRegions] = useState("us-east-1")
  const [openAccounts, setOpenAccounts] = useState<Set<string>>(new Set())
  const [historyOpenAccounts, setHistoryOpenAccounts] = useState<Set<string>>(
    new Set(),
  )

  const invalidateAccounts = () =>
    queryClient.invalidateQueries({ queryKey: ["cloud-accounts", orgId] })

  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ["cloud-accounts", orgId],
    queryFn: () => CloudService.listAccounts({ orgId }),
    enabled: !!orgId,
    // This engine publishes no live events either, and its scans are the
    // longest of any (a cloud scan holds its lock for an hour), so a card that
    // greyed itself for a running scan and then never un-greyed was the most
    // visible here of anywhere.
    refetchInterval: (query) =>
      pollForActivity(
        (query.state.data ?? []).map((account) => account.activity),
      ),
  })

  const createMutation = useMutation({
    mutationFn: (vars: {
      displayName: string
      roleArn: string
      regions: string[]
    }) =>
      CloudService.createAccount({
        requestBody: {
          org_id: orgId!,
          display_name: vars.displayName,
          role_arn: vars.roleArn,
          regions: vars.regions,
        },
      }),
    onSuccess: () => {
      toast.success(
        "Cloud account added — copy its External ID into your IAM role's trust policy",
      )
      setDisplayName("")
      setRoleArn("")
      setRegions("us-east-1")
      invalidateAccounts()
    },
    onError: (error) =>
      toast.error("Failed to add cloud account", {
        description: apiErrorDetail(error),
      }),
  })

  const toggleMutation = useMutation({
    mutationFn: (vars: { accountId: string; enabled: boolean }) =>
      CloudService.updateAccount({
        accountId: vars.accountId,
        requestBody: { enabled: vars.enabled },
      }),
    onSuccess: invalidateAccounts,
    onError: (error) =>
      toast.error("Failed to update account", {
        description: apiErrorDetail(error),
      }),
  })

  const deleteMutation = useMutation({
    mutationFn: (accountId: string) =>
      CloudService.deleteAccount({ accountId }),
    onSuccess: () => {
      toast.success("Cloud account removed")
      invalidateAccounts()
    },
    onError: (error) =>
      toast.error("Failed to remove account", {
        description: apiErrorDetail(error),
      }),
  })

  const scanMutation = useMutation({
    mutationFn: (accountId: string) => CloudService.triggerScan({ accountId }),
    onSuccess: () => {
      toast.success("Scan queued")
      invalidateAccounts()
    },
    onError: (error) =>
      toast.error("Failed to queue scan", {
        description: apiErrorDetail(error),
      }),
  })

  function toggleAccountOpen(accountId: string) {
    setOpenAccounts((prev) => {
      const next = new Set(prev)
      next.has(accountId) ? next.delete(accountId) : next.add(accountId)
      return next
    })
  }

  function toggleHistoryOpen(accountId: string) {
    setHistoryOpenAccounts((prev) => {
      const next = new Set(prev)
      next.has(accountId) ? next.delete(accountId) : next.add(accountId)
      return next
    })
  }

  function handleConnect() {
    const name = displayName.trim()
    const arn = roleArn.trim()
    const regionList = regions
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean)
    if (!name || !arn || !orgId) return
    createMutation.mutate({
      displayName: name,
      roleArn: arn,
      regions: regionList,
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-muted-foreground text-sm">
          AWS cloud posture scanning for this repository's organization —
          read-only, via <code className="font-mono">sts:AssumeRole</code>.
          Accounts are shared across every repo in the organization.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Input
              placeholder="Display name (e.g. prod)"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="max-w-48"
            />
            <Input
              placeholder="arn:aws:iam::123456789012:role/greensecops"
              value={roleArn}
              onChange={(e) => setRoleArn(e.target.value)}
              className="font-mono text-sm max-w-96"
            />
            <Input
              placeholder="us-east-1,eu-west-1"
              value={regions}
              onChange={(e) => setRegions(e.target.value)}
              className="font-mono text-sm max-w-56"
            />
            <Button
              size="sm"
              variant="outline"
              className="gap-2"
              onClick={handleConnect}
              disabled={
                !orgId ||
                !displayName.trim() ||
                !roleArn.trim() ||
                createMutation.isPending
              }
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Connect account
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            The role's trust policy must allow this account to assume it with
            the External ID shown once it's connected below.
          </p>
        </CardContent>
      </Card>

      {repoLoading || accountsLoading ? (
        <div className="flex flex-col gap-4">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : !accounts?.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            No cloud accounts connected for this organization. Add an AWS
            account above to start scanning its posture.
          </CardContent>
        </Card>
      ) : (
        accounts.map((account) => (
          <CloudAccountCard
            key={account.id}
            account={account}
            isOpen={openAccounts.has(account.id)}
            onToggleOpen={() => toggleAccountOpen(account.id)}
            historyOpen={historyOpenAccounts.has(account.id)}
            onToggleHistory={() => toggleHistoryOpen(account.id)}
            onToggleEnabled={(enabled) =>
              toggleMutation.mutate({ accountId: account.id, enabled })
            }
            toggleMutationPending={
              toggleMutation.isPending &&
              toggleMutation.variables?.accountId === account.id
            }
            onScan={() => scanMutation.mutate(account.id)}
            scanMutationPending={
              scanMutation.isPending && scanMutation.variables === account.id
            }
            // The card owns the confirmation (`ConfirmRemoveDialog`); this
            // used to `window.confirm` on top of it, so removing an account
            // asked twice.
            onDelete={() => deleteMutation.mutate(account.id)}
            deleteMutationPending={
              deleteMutation.isPending &&
              deleteMutation.variables === account.id
            }
            quota={quota}
          />
        ))
      )}
    </div>
  )
}

interface CloudAccountCardProps {
  account: CloudAccountPublic
  isOpen: boolean
  onToggleOpen: () => void
  historyOpen: boolean
  onToggleHistory: () => void
  onToggleEnabled: (enabled: boolean) => void
  toggleMutationPending: boolean
  onScan: () => void
  scanMutationPending: boolean
  onDelete: () => void
  deleteMutationPending: boolean
  quota: QuotaReasons | undefined
}

function CloudAccountCard({
  account,
  isOpen,
  onToggleOpen,
  historyOpen,
  onToggleHistory,
  onToggleEnabled,
  toggleMutationPending,
  onScan,
  scanMutationPending,
  onDelete,
  deleteMutationPending,
  quota,
}: CloudAccountCardProps) {
  const [copiedText, copy] = useCopyToClipboard()
  const copied = copiedText === account.external_id
  const [confirmRemove, setConfirmRemove] = useState(false)

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["cloud-findings", account.id],
    queryFn: () => CloudService.listFindings({ accountId: account.id }),
    enabled: isOpen,
  })

  const { data: scans } = useQuery({
    queryKey: ["cloud-scans", account.id],
    queryFn: () => CloudService.listScans({ accountId: account.id }),
    enabled: isOpen && historyOpen,
  })

  const enabled = account.status !== "disabled"
  // Cloud has no fixes, so its only activity is a scan — but the rule that
  // decides whether "Scan now" is live is the same one every engine uses, and
  // so is the one that greys it when the org's analyses are spent.
  const accountState: EngineActionInput = {
    targetLabel: "Cloud account",
    scope: "target",
    enabled,
    quota,
    // The server's own answer, so a scan started elsewhere greys the button
    // here too — cloud posture scans are the longest-running of the lot.
    activity: account.activity,
    scanStatus: account.latest_scan_status,
  }
  const actions = engineActions({
    ...accountState,
    pending: { scan: scanMutationPending },
  })

  return (
    <Card>
      <CardHeader className="pb-2 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 min-w-0">
          <CardTitle className="text-sm font-mono flex flex-wrap items-center gap-2 min-w-0 flex-1">
            <button
              type="button"
              onClick={onToggleOpen}
              className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
              aria-expanded={isOpen}
              title={isOpen ? "Collapse account" : "Expand account"}
            >
              {isOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </button>
            <span className="truncate min-w-0 flex-1">
              {account.display_name}
            </span>
            <StatusPill
              colorClass={cloudAccountStatusColor(account.status)}
              className="capitalize"
            >
              {cloudAccountStatusLabel(account.status)}
            </StatusPill>
            <GradeBadge
              grade={account.latest_grade ?? null}
              className="shrink-0"
            />
          </CardTitle>
          {/* Cloud posture has no files to rewrite, so it declares neither
              `generate` nor `deliver` rather than showing two dead buttons. */}
          <EngineActionBar
            actions={actions}
            capabilities={{ generate: false, deliver: false }}
            onScan={onScan}
            leading={
              <>
                <ScanRunningBadge status={account.latest_scan_status} />
                <div className="flex items-center gap-2">
                  <Switch
                    checked={enabled}
                    onCheckedChange={onToggleEnabled}
                    disabled={toggleMutationPending}
                    aria-label="Enable this account"
                  />
                  <span className="text-xs text-muted-foreground">
                    {enabled ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </>
            }
            overflow={[
              overflowItem(
                removeAction({
                  ...accountState,
                  pending: { remove: deleteMutationPending },
                }),
                () => setConfirmRemove(true),
                { destructive: true },
              ),
            ]}
          />
        </div>
        <ConfirmRemoveDialog
          open={confirmRemove}
          onOpenChange={setConfirmRemove}
          name={account.display_name}
          targetLabel="Cloud account"
          description="This deletes its scan history and findings. It cannot be undone."
          onConfirm={onDelete}
        />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {account.role_arn && (
            <span className="font-mono truncate">{account.role_arn}</span>
          )}
          {(account.regions ?? []).length > 0 && (
            <span>{(account.regions ?? []).join(", ")}</span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">External ID:</span>
          <code className="font-mono bg-muted rounded px-1.5 py-0.5">
            {account.external_id}
          </code>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={() => copy(account.external_id)}
            title="Copy External ID"
          >
            {copied ? (
              <Check className="h-3 w-3 text-primary" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
          </Button>
        </div>
      </CardHeader>
      {/* Two stages, not four: cloud posture has no files to rewrite, so it
          declares neither `fix` nor `deliver` rather than showing two chips
          that could never leave `blocked`. Same idea as the action bar's
          capabilities above. */}
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
          <EngineFlowRail
            {...accountState}
            capabilities={{ sync: false, fix: false, deliver: false }}
            hasCompletedScan={!!account.last_synced_at}
            grade={account.latest_grade}
            openFindingCount={findings?.length ?? 0}
            pending={{ scan: scanMutationPending }}
          />
          <div className="rounded-md border">
            <div className="px-4 py-2 text-xs font-medium text-muted-foreground border-b">
              Open findings
            </div>
            {findingsLoading ? (
              <div className="p-4">
                <Skeleton className="h-16 w-full" />
              </div>
            ) : !findings?.length ? (
              <p className="text-sm text-muted-foreground p-6 text-center">
                No open findings.
                {!account.last_synced_at &&
                  " Run a scan to check this account."}
              </p>
            ) : (
              <div className="divide-y">
                {findings.map((finding) => (
                  <CloudFindingRow
                    key={finding.id}
                    finding={finding}
                    targetState={accountState}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="rounded-md border">
            <button
              type="button"
              onClick={onToggleHistory}
              className="flex w-full items-center gap-2 px-4 py-2 text-left text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
            >
              {historyOpen ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              Scan history
            </button>
            {historyOpen && (
              <div className="divide-y border-t">
                {!scans?.length ? (
                  <p className="text-sm text-muted-foreground p-6 text-center">
                    No scans yet.
                  </p>
                ) : (
                  scans.map((scan) => (
                    <div
                      key={scan.id}
                      className="flex items-center justify-between gap-4 px-4 py-2.5 text-xs"
                    >
                      <StatusPill colorClass={scanStatusColor(scan.status)}>
                        {scanStatusLabel(scan.status)}
                      </StatusPill>
                      <span className="text-muted-foreground capitalize">
                        {scan.triggered_by.replace(/_/g, " ")}
                      </span>
                      <span className="text-muted-foreground">
                        {scan.resource_count} resources
                      </span>
                      <GradeBadge grade={scan.grade ?? null} />
                      <span className="text-muted-foreground tabular-nums">
                        {scan.created_at
                          ? new Date(scan.created_at).toLocaleDateString(
                              undefined,
                              {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )
                          : "—"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  )
}
