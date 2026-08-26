import type { PullRequestPublic, WorkflowFixPublic } from "@/client"

// Mirrors the deterministic branch names delivery mints server-side (see
// backend/app/services/delivery_pr.py wf_fix_branch / repo_fix_branch).
export function workflowFixBranch(workflowFileId: string): string {
  return `greensecops/fixes-wf-${workflowFileId.slice(0, 8)}`
}

export function repoFixBranch(repoId: string): string {
  return `greensecops/fixes-${repoId.slice(0, 8)}`
}

// Mirrors tf_fix_branch server-side (backend/app/services/delivery_pr.py): one
// PR branch per Terraform root, distinct prefix from the workflow branches so
// the Infrastructure PRs tab can tell a Terraform PR from a CI-workflow PR.
export function tfFixBranch(terraformRootId: string): string {
  return `greensecops/terraform-${terraformRootId.slice(0, 8)}`
}

// Mirrors docker_fix_branch server-side (backend/app/services/delivery_pr.py):
// one PR branch per Docker target, with a third distinct prefix so the
// Infrastructure PRs tab can tell a Docker PR from a Terraform or CI-workflow
// one by branch name alone.
export function dockerFixBranch(dockerTargetId: string): string {
  return `greensecops/docker-${dockerTargetId.slice(0, 8)}`
}

// Mirrors ansible_fix_branch server-side (backend/app/services/delivery_pr.py):
// one PR branch per Ansible project, with a fourth distinct prefix so the
// Infrastructure PRs tab can tell an Ansible PR from a Terraform, Docker or
// CI-workflow one by branch name alone.
export function ansibleFixBranch(ansibleProjectId: string): string {
  return `greensecops/ansible-${ansibleProjectId.slice(0, 8)}`
}

// Mirrors the fixed branch name delivery mints server-side for the
// "Integrate action" PR (see backend/app/api/routes/repositories.py
// integrate_action).
export const INTEGRATE_ACTION_BRANCH = "greensecops/integrate-action"

// A ready fix never carries pr_id/pr_state (it never had a PR through the
// Fix record), so whether a PR already exists for its branch must come from
// the real PullRequest rows, not from the fix itself.
export function labelForBranch(
  prByBranch: Map<string, PullRequestPublic>,
  branch: string,
  verb: string,
): { label: string; force: boolean } {
  const pr = prByBranch.get(branch)
  if (pr?.pr_state === "closed") return { label: `Reopen ${verb}`, force: true }
  if (pr) return { label: `Update ${verb}`, force: false }
  return { label: `Create ${verb}`, force: false }
}

// What the delivery button on a fix card should do, if anything. Reopening
// after the user closed the PR without merging needs force=true to bypass the
// closed-PR delivery guard.
export function deliverAction(
  fix: WorkflowFixPublic,
  prByBranch: Map<string, PullRequestPublic>,
): { label: string; force: boolean } | null {
  if (fix.status === "ready") {
    return labelForBranch(
      prByBranch,
      workflowFixBranch(fix.workflow_file_id),
      "PR",
    )
  }
  if (
    (fix.status === "delivered" ||
      fix.status === "rejected_by_user" ||
      fix.status === "superseded_by_closed_pr") &&
    fix.pr_state === "closed"
  ) {
    return { label: "Reopen PR", force: true }
  }
  return null
}
