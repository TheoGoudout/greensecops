import { useQueryClient } from "@tanstack/react-query"
import { useCallback } from "react"
import { toast } from "sonner"
import { type SSEEventData, useSSE } from "./useSSE"

function invalidateRepoQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoId: string,
) {
  qc.invalidateQueries({ queryKey: ["repositories"] })
  qc.invalidateQueries({ queryKey: ["repository", repoId] })
}

function invalidateAnalysisQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoId: string,
  analysisId?: string | null,
) {
  qc.invalidateQueries({ queryKey: ["scans", "recent"] })
  qc.invalidateQueries({ queryKey: ["scans", repoId] })
  if (analysisId) {
    qc.invalidateQueries({ queryKey: ["scan", analysisId] })
  }
}

function invalidateIssueQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoId: string,
  analysisId?: string | null,
) {
  qc.invalidateQueries({ queryKey: ["findings", "open"] })
  qc.invalidateQueries({ queryKey: ["findings", "repo", repoId] })
  if (analysisId) {
    qc.invalidateQueries({ queryKey: ["findings", analysisId] })
  }
}

function invalidateFixQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoId: string,
  fixId?: string | null,
) {
  qc.invalidateQueries({ queryKey: ["fixes", "repo", repoId] })
  if (fixId) {
    qc.invalidateQueries({ queryKey: ["fix", fixId] })
  }
}

function invalidateInstallationQueries(
  qc: ReturnType<typeof useQueryClient>,
  orgId?: string | null,
) {
  qc.invalidateQueries({ queryKey: ["installations"] })
  qc.invalidateQueries({ queryKey: ["repositories"] })
  if (orgId) {
    qc.invalidateQueries({ queryKey: ["organizations", orgId] })
  }
}

function invalidateTelemetryQueries(
  qc: ReturnType<typeof useQueryClient>,
  repoId: string,
) {
  qc.invalidateQueries({ queryKey: ["telemetry", "summary", repoId] })
  qc.invalidateQueries({ queryKey: ["telemetry", "findings", repoId] })
}

/**
 * Subscribes to SSE and invalidates TanStack Query caches + shows toasts
 * when the server emits events for repos, analyses, fixes, PRs, or installations.
 *
 * Mount once at the authenticated layout level — covers all child routes.
 */
export function useRepoEvents(): void {
  const queryClient = useQueryClient()

  const handleEvent = useCallback(
    (data: SSEEventData) => {
      const repoId = data.repo_id
      const orgId = data.org_id
      const analysisId = data.analysis_id
      const fixId = data.fix_id
      const fixIds = data.fix_ids
      const repoIds = data.repo_ids

      switch (data.event) {
        case "analysis.queued":
        case "analysis.started":
          if (repoId) {
            invalidateRepoQueries(queryClient, repoId)
            invalidateAnalysisQueries(queryClient, repoId, analysisId)
          }
          break

        case "analysis.completed": {
          if (repoId) {
            invalidateRepoQueries(queryClient, repoId)
            invalidateAnalysisQueries(queryClient, repoId, analysisId)
            invalidateIssueQueries(queryClient, repoId, analysisId)
            // A completed run may have soft-deleted workflow files that vanished
            // from the repo; refresh the list so their cards drop out.
            queryClient.invalidateQueries({
              queryKey: ["workflow-files", repoId],
            })
          }
          const grade = data.grade
          const score = data.score
          const issuesCount = data.issues_count
          // `!= null` rather than `!== undefined`: the wire sends JSON null for
          // an absent field, which the old `as number | undefined` cast hid —
          // the guard passed and `Math.round(null)` rendered "Score 0".
          if (grade != null && score != null) {
            toast.success("Analysis complete", {
              description: `Grade ${grade} · Score ${Math.round(score)} · ${issuesCount ?? 0} issue${issuesCount === 1 ? "" : "s"}`,
            })
          }
          break
        }

        case "analysis.failed": {
          if (repoId) {
            invalidateRepoQueries(queryClient, repoId)
            invalidateAnalysisQueries(queryClient, repoId, analysisId)
          }
          const error = data.error
          toast.error("Analysis failed", {
            description: error ?? "Unknown error",
          })
          break
        }

        case "analysis.skipped":
          if (repoId) {
            invalidateAnalysisQueries(queryClient, repoId, analysisId)
            // A per-file re-analysis of a since-deleted workflow reports
            // "skipped"; refresh the list so its card drops out.
            queryClient.invalidateQueries({
              queryKey: ["workflow-files", repoId],
            })
          }
          break

        case "analysis.no_workflows":
          if (repoId) {
            invalidateRepoQueries(queryClient, repoId)
            invalidateAnalysisQueries(queryClient, repoId, analysisId)
            queryClient.invalidateQueries({
              queryKey: ["workflow-files", repoId],
            })
          }
          toast.info("No workflow files", {
            description:
              "This repository has no GitHub Actions workflows to analyse.",
          })
          break

        case "fix.skipped":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId)
          }
          break

        case "fix.generating":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId)
          }
          break

        case "fix.ready": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
            invalidateIssueQueries(queryClient, repoId)
            queryClient.invalidateQueries({
              queryKey: ["workflow-files", repoId],
            })
            if (fixIds) {
              for (const id of fixIds) {
                queryClient.invalidateQueries({ queryKey: ["fix", id] })
              }
            }
          }
          const count = fixIds?.length ?? (fixId ? 1 : 0)
          toast.success(count > 1 ? `${count} fixes ready` : "Fix ready", {
            description: "Review and deliver from the Fixes tab",
          })
          break
        }

        case "fix.delivering":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
            if (fixIds) {
              for (const id of fixIds) {
                queryClient.invalidateQueries({ queryKey: ["fix", id] })
              }
            }
          }
          break

        case "fix.delivered": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
            if (fixIds) {
              for (const id of fixIds) {
                queryClient.invalidateQueries({ queryKey: ["fix", id] })
              }
            }
          }
          const prUrl = data.pr_url
          if (prUrl) {
            toast.success("Fix delivered", {
              description: "Pull request created",
              action: {
                label: "View PR",
                onClick: () => window.open(prUrl, "_blank"),
              },
            })
          } else {
            toast.success("Fix delivered")
          }
          break
        }

        case "fix.failed": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
            invalidateIssueQueries(queryClient, repoId)
            if (fixIds) {
              for (const id of fixIds) {
                queryClient.invalidateQueries({ queryKey: ["fix", id] })
              }
            }
          }
          const failedCount = fixIds?.length ?? (fixId ? 1 : 0)
          const failErr = data.error
          toast.error(
            failedCount > 1 ? `${failedCount} fixes failed` : "Fix failed",
            {
              description: failErr ?? "Unknown error",
            },
          )
          break
        }

        case "fix.pending":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
          }
          break

        case "fix.landed": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
            invalidateIssueQueries(queryClient, repoId)
          }
          toast.success("Fix merged", {
            description: "The fix's pull request was merged.",
          })
          break
        }

        case "fix.rejected":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId, fixId)
          }
          break

        case "pr.opened": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId)
          }
          const openedUrl = data.pr_url
          if (openedUrl) {
            toast.info("Pull request opened", {
              action: {
                label: "View PR",
                onClick: () => window.open(openedUrl, "_blank"),
              },
            })
          }
          break
        }

        case "pr.updated":
          if (repoId) {
            invalidateFixQueries(queryClient, repoId)
          }
          break

        case "pr.merged":
        case "pr.closed": {
          if (repoId) {
            invalidateFixQueries(queryClient, repoId)
          }
          const merged = data.event === "pr.merged"
          const closedUrl = data.pr_url
          toast.info(merged ? "Pull request merged" : "Pull request closed", {
            ...(closedUrl && {
              action: {
                label: "View PR",
                onClick: () => window.open(closedUrl, "_blank"),
              },
            }),
          })
          break
        }

        case "installation.syncing":
          break

        case "installation.synced": {
          invalidateInstallationQueries(queryClient, orgId)
          const repoCount = data.repo_count
          toast.success("Installation synced", {
            description:
              repoCount != null
                ? `${repoCount} repositor${repoCount === 1 ? "y" : "ies"} synced`
                : undefined,
          })
          break
        }

        case "installation.created":
          invalidateInstallationQueries(queryClient, orgId)
          toast.success("GitHub App installed")
          break

        case "installation.deleted":
          invalidateInstallationQueries(queryClient, orgId)
          toast.info("GitHub App uninstalled")
          break

        case "installation.suspended":
          invalidateInstallationQueries(queryClient, orgId)
          toast.warning("GitHub App suspended")
          break

        case "installation.unsuspended":
          invalidateInstallationQueries(queryClient, orgId)
          toast.success("GitHub App unsuspended")
          break

        case "installation.updated":
          invalidateInstallationQueries(queryClient, orgId)
          toast.info("GitHub App permissions updated")
          break

        case "repository.added":
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          break

        case "repository.disabled":
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          break

        case "repository.toggled": {
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          if (repoId) {
            queryClient.invalidateQueries({ queryKey: ["repository", repoId] })
          }
          const enabled = data.enabled
          if (enabled != null) {
            toast.info(enabled ? "Repository enabled" : "Repository disabled")
          }
          break
        }

        case "repository.action_pr_opened":
          if (repoId) {
            queryClient.invalidateQueries({ queryKey: ["repository", repoId] })
          }
          break

        // Repository accessibility lifecycle (RepositoryMachine) — payloads
        // carry repo_ids (a batch), not a single repo_id.
        case "repository.suspended":
        case "repository.archived":
        case "repository.inaccessible": {
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          for (const id of repoIds ?? []) {
            queryClient.invalidateQueries({ queryKey: ["repository", id] })
          }
          const count = repoIds?.length ?? 0
          const suffix = count > 1 ? `${count} repositories` : "A repository"
          if (data.event === "repository.suspended") {
            toast.warning("Repository access suspended", {
              description: `${suffix} can no longer be acted on.`,
            })
          } else if (data.event === "repository.archived") {
            toast.info("Repository archived", {
              description: `${suffix} was archived on GitHub.`,
            })
          } else {
            toast.warning("Repository access lost", {
              description: `${suffix} is no longer accessible.`,
            })
          }
          break
        }

        case "repository.restored": {
          queryClient.invalidateQueries({ queryKey: ["repositories"] })
          for (const id of repoIds ?? []) {
            queryClient.invalidateQueries({ queryKey: ["repository", id] })
          }
          toast.success("Repository access restored")
          break
        }

        // Dynamic analysis (TelemetryMachine). Refresh the Telemetry tab and the
        // Issues-page runtime section as runs advance; no toast (findings are
        // low-signal recommendations, not actionable alerts).
        case "dynamic.queued":
        case "dynamic.running":
        case "dynamic.enriched":
        case "dynamic.failed":
          if (repoId) {
            invalidateRepoQueries(queryClient, repoId)
            invalidateAnalysisQueries(queryClient, repoId)
            invalidateTelemetryQueries(queryClient, repoId)
          }
          break
      }
    },
    [queryClient],
  )

  useSSE(handleEvent)
}
