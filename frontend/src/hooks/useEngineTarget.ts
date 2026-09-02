import {
  type UseMutationResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"
import type { FixStatus } from "@/client"
import { apiErrorDetail } from "@/lib/api-error"
import { isFixInFlight } from "@/lib/engine-actions"
import { SCAN_POLL_MS } from "@/lib/scan-polling"

/**
 * What the Terraform and Docker scan-target cards do identically, once.
 *
 * Both pages show a list of registered targets, expand one to load its files,
 * findings and fixes, and offer the same six actions: enable/disable, scan now,
 * remove, generate a fix for one file, generate fixes for everything, deliver a
 * PR. The two files each wrote that out — four `useQuery`s and six
 * `useMutation`s apiece, with the same invalidate-then-toast wiring and the same
 * `apiErrorDetail` error handling, differing only in which service method to
 * call and what the toast says.
 *
 * The *rendering* stays per-engine on purpose. A Terraform card shows module
 * paths and a scan history; a Docker card shows build stages and Compose
 * services. Those are different screens that happen to share a data layer, and
 * merging their JSX would mean a component whose body is mostly branches.
 */

export interface EngineTargetCalls<TFile, TFinding, TFix> {
  /** Query-key prefix, e.g. `"terraform"` — keys become `terraform-files` etc. */
  keyPrefix: string
  listFiles: () => Promise<TFile[]>
  listFindings: () => Promise<TFinding[]>
  listFixes: () => Promise<TFix[]>
  toggle: (enabled: boolean) => Promise<unknown>
  scan: () => Promise<unknown>
  remove: () => Promise<unknown>
  /**
   * Empty array means "everything", matching both engines' route contracts.
   * `force` discards the fixes those findings already have and queues them
   * again — without it the route silently skips every file whose fix is not
   * `failed`, which is what "Regenerate" exists to get past.
   */
  generate: (findingIds: string[], force: boolean) => Promise<unknown>
  deliver: (force: boolean) => Promise<unknown>
  /** Noun used in the action toasts: "Terraform root", "Docker target". */
  targetLabel: string
}

type Mutation<TArgs> = UseMutationResult<unknown, Error, TArgs>

/** What a "Generate fixes" click asks for: which findings, and whether to
 * discard the fixes they already have. */
export interface GenerateArgs {
  findingIds: string[]
  force?: boolean
}

export interface EngineTargetState<TFile, TFinding, TFix> {
  files: TFile[] | undefined
  /**
   * Whether the expanded card's contents are still arriving.
   *
   * All three queries, not just the files one: the files list resolves first
   * and the card rendered its rows immediately, so an expanded target showed a
   * list of file names with no findings and no fix under them — which reads as
   * "there is nothing in here" rather than "this is still loading".
   *
   * A collapsed card is not loading: the files query is `enabled: isOpen`, and
   * a disabled query is pending but not fetching, which `isLoading` excludes.
   * Findings and fixes now load whether or not the card is open (see below), so
   * in practice they have usually settled before it is expanded at all.
   */
  isLoading: boolean
  findings: TFinding[] | undefined
  fixes: TFix[] | undefined
  invalidate: () => void
  toggleMutation: Mutation<boolean>
  scanMutation: Mutation<void>
  deleteMutation: Mutation<void>
  generateMutation: Mutation<GenerateArgs>
  deliverMutation: Mutation<boolean>
}

/**
 * One target action: run it, refresh what it changed, then say what happened.
 *
 * A named hook rather than a closure inside `useEngineTarget`, so the
 * rules-of-hooks lint can see that these are hook calls in a fixed order.
 */
function useAction<TArgs>(
  mutationFn: (args: TArgs) => Promise<unknown>,
  invalidate: () => void,
  messages: { success?: string; failure: string },
): Mutation<TArgs> {
  return useMutation<unknown, Error, TArgs>({
    mutationFn,
    onSuccess: () => {
      if (messages.success) toast.success(messages.success)
      invalidate()
    },
    onError: (e) =>
      toast.error(messages.failure, { description: apiErrorDetail(e) }),
  })
}

export function useEngineTarget<
  TFile,
  TFinding,
  TFix extends { status: FixStatus },
>(
  targetId: string,
  isOpen: boolean,
  calls: EngineTargetCalls<TFile, TFinding, TFix>,
  /**
   * Whether this target's latest scan is still running.
   *
   * While it is, the card re-asks for what the scan is about to change. These
   * engines publish no live events, and the only refresh that ever happened
   * was the invalidate fired when the *trigger* request returned — which is
   * before the worker has done anything.
   */
  isScanning = false,
): EngineTargetState<TFile, TFinding, TFix> {
  const queryClient = useQueryClient()
  const { keyPrefix, targetLabel } = calls

  // Fixes come first because everything else's poll depends on them: a fix
  // being generated or delivered is exactly as much "work in flight" as a
  // running scan, and it used to resolve on screen only after a page reload.
  const { data: fixes, isLoading: fixesLoading } = useQuery({
    queryKey: [`${keyPrefix}-fixes`, targetId],
    queryFn: calls.listFixes,
    refetchInterval: (query) =>
      isScanning ||
      (query.state.data ?? []).some((f) => isFixInFlight(f.status))
        ? SCAN_POLL_MS
        : false,
  })
  const refetchInterval =
    isScanning || (fixes ?? []).some((f) => isFixInFlight(f.status))
      ? SCAN_POLL_MS
      : false

  // The file list loads only once the card is expanded — a repo can hold many
  // targets and each one costs a GitHub round-trip for its files.
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: [`${keyPrefix}-files`, targetId],
    queryFn: calls.listFiles,
    enabled: isOpen,
    refetchInterval,
  })
  // Findings and fixes do not wait for the card to open. They are plain
  // database reads, and the card's *header* now needs them: whether a fix is
  // being generated decides whether "Scan now" and "Create PR" are live, and a
  // collapsed card that could not see its own fixes had to show those buttons
  // enabled and let the server refuse them.
  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: [`${keyPrefix}-findings`, targetId],
    queryFn: calls.listFindings,
    refetchInterval,
  })

  const invalidate = () => {
    for (const key of [
      [`${keyPrefix}-targets`, "repo"],
      [`${keyPrefix}-findings`, targetId],
      [`${keyPrefix}-fixes`, targetId],
      [`${keyPrefix}-scans`, targetId],
      [`${keyPrefix}-repo-fixes`],
      ["pull-requests", "repo"],
      // Every action here spends an analysis or a fix, and the allowance those
      // come out of is what greys the buttons out. Left stale, a user who has
      // just spent their last one keeps a live button.
      ["quotas"],
    ]) {
      queryClient.invalidateQueries({ queryKey: key })
    }
  }

  return {
    files,
    isLoading: filesLoading || findingsLoading || fixesLoading,
    findings,
    fixes,
    invalidate,
    // Toggling is silent on success: the switch itself is the feedback.
    toggleMutation: useAction<boolean>(calls.toggle, invalidate, {
      failure: `Could not update ${targetLabel.toLowerCase()}`,
    }),
    scanMutation: useAction<void>(calls.scan, invalidate, {
      success: "Scan queued",
      failure: "Could not queue scan",
    }),
    deleteMutation: useAction<void>(calls.remove, invalidate, {
      success: `${targetLabel} removed`,
      failure: `Could not remove ${targetLabel.toLowerCase()}`,
    }),
    generateMutation: useAction<GenerateArgs>(
      ({ findingIds, force = false }) => calls.generate(findingIds, force),
      invalidate,
      {
        success: "Fix generation queued",
        failure: "Could not queue fixes",
      },
    ),
    deliverMutation: useAction<boolean>(calls.deliver, invalidate, {
      success: "PR queued",
      failure: "Could not queue PR",
    }),
  }
}
