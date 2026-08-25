import {
  type UseMutationResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { toast } from "sonner"
import { apiErrorDetail } from "@/lib/api-error"

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
  /** Empty array means "everything", matching both engines' route contracts. */
  generate: (findingIds: string[]) => Promise<unknown>
  deliver: (force: boolean) => Promise<unknown>
  /** Noun used in the action toasts: "Terraform root", "Docker target". */
  targetLabel: string
}

type Mutation<TArgs> = UseMutationResult<unknown, Error, TArgs>

export interface EngineTargetState<TFile, TFinding, TFix> {
  files: TFile[] | undefined
  filesLoading: boolean
  findings: TFinding[] | undefined
  fixes: TFix[] | undefined
  invalidate: () => void
  toggleMutation: Mutation<boolean>
  scanMutation: Mutation<void>
  deleteMutation: Mutation<void>
  generateMutation: Mutation<string[]>
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

export function useEngineTarget<TFile, TFinding, TFix>(
  targetId: string,
  isOpen: boolean,
  calls: EngineTargetCalls<TFile, TFinding, TFix>,
): EngineTargetState<TFile, TFinding, TFix> {
  const queryClient = useQueryClient()
  const { keyPrefix, targetLabel } = calls

  // Everything below the fold loads only once the card is expanded — a repo can
  // hold many targets and each one costs a GitHub round-trip for its files.
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: [`${keyPrefix}-files`, targetId],
    queryFn: calls.listFiles,
    enabled: isOpen,
  })
  const { data: findings } = useQuery({
    queryKey: [`${keyPrefix}-findings`, targetId],
    queryFn: calls.listFindings,
    enabled: isOpen,
  })
  const { data: fixes } = useQuery({
    queryKey: [`${keyPrefix}-fixes`, targetId],
    queryFn: calls.listFixes,
    enabled: isOpen,
  })

  const invalidate = () => {
    for (const key of [
      [`${keyPrefix}-targets`, "repo"],
      [`${keyPrefix}-findings`, targetId],
      [`${keyPrefix}-fixes`, targetId],
      [`${keyPrefix}-scans`, targetId],
      ["pull-requests", "repo"],
    ]) {
      queryClient.invalidateQueries({ queryKey: key })
    }
  }

  return {
    files,
    filesLoading,
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
    generateMutation: useAction<string[]>(calls.generate, invalidate, {
      success: "Fix generation queued",
      failure: "Could not queue fixes",
    }),
    deliverMutation: useAction<boolean>(calls.deliver, invalidate, {
      success: "PR queued",
      failure: "Could not queue PR",
    }),
  }
}
