import { describe, expect, it } from "vitest"
import type { FixPublic, PullRequestPublic } from "@/client"
import {
  deliverAction,
  labelForBranch,
  repoFixBranch,
  workflowFixBranch,
} from "./fixes"

function makePr(overrides: Partial<PullRequestPublic> = {}): PullRequestPublic {
  return {
    id: "pr-1",
    repo_id: "repo-1",
    pr_branch: "greensecops/fixes-wf-12345678",
    pr_url: "https://github.com/org/repo/pull/1",
    pr_state: "open",
    ...overrides,
  }
}

function makeFix(overrides: Partial<FixPublic> = {}): FixPublic {
  return {
    id: "fix-1",
    workflow_file_id: "12345678-aaaa-bbbb-cccc-000000000000",
    llm_provider: "anthropic",
    llm_model: "claude",
    status: "ready",
    ...overrides,
  } as FixPublic
}

describe("workflowFixBranch / repoFixBranch", () => {
  it("mirrors the backend's deterministic branch naming", () => {
    expect(workflowFixBranch("12345678-aaaa-bbbb-cccc-000000000000")).toBe(
      "greensecops/fixes-wf-12345678",
    )
    expect(repoFixBranch("87654321-aaaa-bbbb-cccc-000000000000")).toBe(
      "greensecops/fixes-87654321",
    )
  })
})

describe("labelForBranch", () => {
  it("labels Create when no PR exists for the branch", () => {
    const result = labelForBranch(
      new Map(),
      "greensecops/fixes-wf-12345678",
      "PR",
    )
    expect(result).toEqual({ label: "Create PR", force: false })
  })

  it("labels Update when an open PR already exists for the branch", () => {
    const pr = makePr({ pr_state: "open" })
    const prByBranch = new Map([[pr.pr_branch, pr]])
    const result = labelForBranch(prByBranch, pr.pr_branch, "PR")
    expect(result).toEqual({ label: "Update PR", force: false })
  })

  it("labels Reopen with force when the existing PR was closed", () => {
    const pr = makePr({ pr_state: "closed" })
    const prByBranch = new Map([[pr.pr_branch, pr]])
    const result = labelForBranch(prByBranch, pr.pr_branch, "PR")
    expect(result).toEqual({ label: "Reopen PR", force: true })
  })
})

describe("deliverAction", () => {
  it("reads Create/Update/Reopen for a ready fix from the real PR list, not fix.pr_state", () => {
    // Regression: a `ready` fix always has pr_state === null/undefined even
    // when a matching PR already exists (e.g. right after regenerating fixes
    // for a repo that already has an open PR). The label must still say
    // "Update PR", not "Create PR".
    const fix = makeFix({ status: "ready", pr_state: undefined })
    const branch = workflowFixBranch(fix.workflow_file_id)
    const pr = makePr({ pr_branch: branch, pr_state: "open" })
    const prByBranch = new Map([[pr.pr_branch, pr]])

    expect(deliverAction(fix, prByBranch)).toEqual({
      label: "Update PR",
      force: false,
    })
  })

  it("labels Create for a ready fix whose branch has no PR yet", () => {
    const fix = makeFix({ status: "ready" })
    expect(deliverAction(fix, new Map())).toEqual({
      label: "Create PR",
      force: false,
    })
  })

  it("labels Reopen with force for a ready fix whose branch PR was closed", () => {
    const fix = makeFix({ status: "ready" })
    const branch = workflowFixBranch(fix.workflow_file_id)
    const pr = makePr({ pr_branch: branch, pr_state: "closed" })
    const prByBranch = new Map([[pr.pr_branch, pr]])

    expect(deliverAction(fix, prByBranch)).toEqual({
      label: "Reopen PR",
      force: true,
    })
  })

  it("offers Reopen for a delivered fix whose PR was closed without merging", () => {
    const fix = makeFix({ status: "delivered", pr_state: "closed" })
    expect(deliverAction(fix, new Map())).toEqual({
      label: "Reopen PR",
      force: true,
    })
  })

  it("returns null when a delivered fix's PR is still open (nothing to do)", () => {
    const fix = makeFix({ status: "delivered", pr_state: "open" })
    expect(deliverAction(fix, new Map())).toBeNull()
  })

  it("returns null for in-flight statuses like delivering", () => {
    const fix = makeFix({ status: "delivering" })
    expect(deliverAction(fix, new Map())).toBeNull()
  })
})
