import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Loader2,
  Play,
  Plus,
  Trash2,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import type { CloudAccountPublic } from "@/client"
import { CloudService, OrganizationsService } from "@/client"
import { CloudFindingRow } from "@/components/CloudFindingRow"
import { GradeBadge } from "@/components/GradeBadge"
import { StatusPill } from "@/components/StatusPill"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import {
  cloudAccountStatusColor,
  cloudAccountStatusLabel,
  scanStatusColor,
  scanStatusLabel,
} from "@/lib/status-colors"
import { apiErrorDetail } from "@/utils"

export const Route = createFileRoute("/_layout/infrastructure/cloud")({
  component: CloudPage,
  head: () => ({
    meta: [{ title: "Cloud - GreenSecOps" }],
  }),
})

function CloudPage() {
  const queryClient = useQueryClient()

  const [selectedOrgId, setSelectedOrgId] = useState<string>("")
  const [displayName, setDisplayName] = useState("")
  const [roleArn, setRoleArn] = useState("")
  const [regions, setRegions] = useState("us-east-1")
  const [openAccounts, setOpenAccounts] = useState<Set<string>>(new Set())
  const [historyOpenAccounts, setHistoryOpenAccounts] = useState<Set<string>>(
    new Set(),
  )

  const invalidateAccounts = () =>
    queryClient.invalidateQueries({ queryKey: ["cloud-accounts"] })

  const { data: orgs } = useQuery({
    queryKey: ["organizations"],
    queryFn: OrganizationsService.listMyOrganizations,
  })

  const { data: accounts, isLoading: accountsLoading } = useQuery({
    queryKey: ["cloud-accounts"],
    queryFn: () => CloudService.listCloudAccounts({}),
  })

  const createMutation = useMutation({
    mutationFn: (vars: {
      orgId: string
      displayName: string
      roleArn: string
      regions: string[]
    }) =>
      CloudService.createCloudAccount({
        requestBody: {
          org_id: vars.orgId,
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
      CloudService.toggleCloudAccount(vars),
    onSuccess: invalidateAccounts,
    onError: (error) =>
      toast.error("Failed to update account", {
        description: apiErrorDetail(error),
      }),
  })

  const deleteMutation = useMutation({
    mutationFn: (accountId: string) =>
      CloudService.deleteCloudAccount({ accountId }),
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
    mutationFn: (accountId: string) =>
      CloudService.triggerCloudScan({ accountId }),
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
      if (next.has(accountId)) next.delete(accountId)
      else next.add(accountId)
      return next
    })
  }

  function toggleHistoryOpen(accountId: string) {
    setHistoryOpenAccounts((prev) => {
      const next = new Set(prev)
      if (next.has(accountId)) next.delete(accountId)
      else next.add(accountId)
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
    if (!name || !arn || !selectedOrgId) return
    createMutation.mutate({
      orgId: selectedOrgId,
      displayName: name,
      roleArn: arn,
      regions: regionList,
    })
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Cloud</h1>
        <p className="text-muted-foreground">
          AWS cloud posture scanning across every account you connect —
          read-only, via sts:AssumeRole.
        </p>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 py-4">
          <div className="flex items-center gap-2 flex-wrap">
            <Select value={selectedOrgId} onValueChange={setSelectedOrgId}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder="Select an organization" />
              </SelectTrigger>
              <SelectContent>
                {(orgs ?? []).map((org) => (
                  <SelectItem key={org.id} value={org.id}>
                    {org.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
                !selectedOrgId ||
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

      {accountsLoading ? (
        <div className="flex flex-col gap-4">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : !accounts?.length ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground text-sm">
            No cloud accounts connected. Add an AWS account above to start
            scanning its posture.
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
            onDelete={() => {
              if (
                window.confirm(
                  `Remove cloud account "${account.display_name}"? This deletes its scan history and findings.`,
                )
              ) {
                deleteMutation.mutate(account.id)
              }
            }}
            deleteMutationPending={
              deleteMutation.isPending &&
              deleteMutation.variables === account.id
            }
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
}: CloudAccountCardProps) {
  const [copiedText, copy] = useCopyToClipboard()
  const copied = copiedText === account.external_id

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["cloud-findings", account.id],
    queryFn: () => CloudService.listCloudFindings({ accountId: account.id }),
    enabled: isOpen,
  })

  const { data: scans } = useQuery({
    queryKey: ["cloud-scans", account.id],
    queryFn: () => CloudService.listCloudScans({ accountId: account.id }),
    enabled: isOpen && historyOpen,
  })

  const enabled = account.status !== "disabled"

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
          <div className="flex items-center gap-3 shrink-0">
            <div className="flex items-center gap-2">
              <Switch
                checked={enabled}
                onCheckedChange={onToggleEnabled}
                disabled={toggleMutationPending}
              />
              <span className="text-xs text-muted-foreground">
                {enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5"
              onClick={onScan}
              disabled={!enabled || scanMutationPending}
              title={
                enabled
                  ? "Scan this account now"
                  : "Enable this account to scan it"
              }
            >
              {scanMutationPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              Scan now
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs gap-1.5 text-destructive hover:text-destructive"
              onClick={onDelete}
              disabled={deleteMutationPending}
            >
              {deleteMutationPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
              Remove
            </Button>
          </div>
        </div>
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
      {isOpen && (
        <CardContent className="flex flex-col gap-3">
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
                  <CloudFindingRow key={finding.id} finding={finding} />
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
