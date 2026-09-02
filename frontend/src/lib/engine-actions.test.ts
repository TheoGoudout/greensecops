import { describe, expect, it } from "vitest"
import type { FixStatus, PullRequestPublic, ScanStatus } from "@/client"
import {
  type EngineActionInput,
  engineActions,
  isFixInFlight,
  targetActivity,
} from "@/lib/engine-actions"

/**
 * These mirror `backend/tests/services/state_machines/test_engine_target.py`.
 * The rule is stated twice on purpose — the UI has to say in advance what the
 * API would refuse — so it is worth checking that the two agree, in particular
 * on the wording a user reads.
 */

function input(overrides: Partial<EngineActionInput> = {}): EngineActionInput {
  return {
    targetLabel: "Terraform root",
    scope: "target",
    isAccessible: true,
    enabled: true,
    openFindingCount: 1,
    ...overrides,
  }
}

describe("targetActivity", () => {
  it("is idle when nothing is running", () => {
    expect(targetActivity(input())).toBe("idle")
  })

  it.each<[string, ScanStatus]>([
    ["queued", "queued"],
    ["running", "running"],
  ])("reports scanning for a %s scan", (_label, status) => {
    expect(targetActivity(input({ scanStatus: status }))).toBe("scanning")
  })

  it.each<[ScanStatus]>([["completed"], ["failed"], ["no_targets"]])(
    "treats a %s scan as finished, not activity",
    (status) => {
      expect(targetActivity(input({ scanStatus: status }))).toBe("idle")
    },
  )

  it("accepts a list of scan statuses, for a repository-wide scope", () => {
    expect(
      targetActivity(input({ scanStatus: ["completed", "running"] })),
    ).toBe("scanning")
  })

  it.each<[FixStatus, string]>([
    ["pending", "generating"],
    ["generating", "generating"],
    ["delivering", "delivering"],
    ["ready", "idle"],
    ["delivered", "idle"],
    ["failed", "idle"],
  ])("maps a %s fix to %s", (status, expected) => {
    expect(targetActivity(input({ fixStatuses: [status] }))).toBe(expected)
  })

  it("reports the longest wait when several hold at once", () => {
    expect(
      targetActivity(
        input({
          scanStatus: "running",
          fixStatuses: ["generating", "delivering"],
        }),
      ),
    ).toBe("scanning")
    expect(
      targetActivity(input({ fixStatuses: ["generating", "delivering"] })),
    ).toBe("delivering")
  })
})

describe("engineActions", () => {
  it("offers all three on an idle target with work to do", () => {
    const a = engineActions(
      input({ fixStatuses: ["ready"], openFindingCount: 2 }),
    )
    expect(a.scan.disabled).toBe(false)
    expect(a.generate.disabled).toBe(false)
    expect(a.deliver.disabled).toBe(false)
    expect(a.scan.label).toBe("Scan now")
    expect(a.generate.label).toBe("Generate fixes")
    expect(a.deliver.label).toBe("Create PR")
  })

  it("refuses everything while a scan runs, in the API's own words", () => {
    const a = engineActions(input({ scanStatus: "running" }))
    expect(a.scan.disabled).toBe(true)
    expect(a.generate.disabled).toBe(true)
    expect(a.deliver.disabled).toBe(true)
    // Matches the 409 detail the backend raises, minus its target suffix.
    expect(a.generate.reason).toBe(
      "Cannot generate fixes while a scan is already running",
    )
    expect(a.deliver.reason).toBe(
      "Cannot open a pull request while a scan is already running",
    )
    expect(a.scan.label).toBe("Scanning…")
  })

  it("lets a generating target generate another file's fix", () => {
    const a = engineActions(input({ fixStatuses: ["generating"] }))
    expect(a.scan.disabled).toBe(true)
    expect(a.deliver.disabled).toBe(true)
    expect(a.generate.disabled).toBe(false)
    expect(a.generate.label).toBe("Generating…")
  })

  it("refuses everything while a pull request is being opened", () => {
    const a = engineActions(input({ fixStatuses: ["delivering"] }))
    for (const action of [a.scan, a.generate, a.deliver]) {
      expect(action.disabled).toBe(true)
      expect(action.reason).toContain("a pull request is being opened")
    }
  })

  it("names the standing conditions before the temporary ones", () => {
    expect(engineActions(input({ isAccessible: false })).scan.reason).toBe(
      "GitHub access to this repository was lost",
    )
    expect(engineActions(input({ enabled: false })).scan.reason).toBe(
      "Enable this terraform root first",
    )
  })

  it("says what is missing rather than hiding the button", () => {
    const a = engineActions(input({ openFindingCount: 0 }))
    expect(a.generate.disabled).toBe(true)
    expect(a.generate.reason).toBe("No open findings to fix")
    expect(a.deliver.disabled).toBe(true)
    expect(a.deliver.reason).toBe("No fix is ready to deliver")
  })

  it("names one file's action in the singular", () => {
    expect(engineActions(input({ scope: "file" })).generate.label).toBe(
      "Generate fix",
    )
  })

  it("counts the selection into the label", () => {
    expect(engineActions(input({ count: 3 })).generate.label).toBe(
      "Generate fixes (3)",
    )
  })

  it("folds the delivery's three shapes into one button", () => {
    const pr = (state: PullRequestPublic["pr_state"]): PullRequestPublic => ({
      id: "pr-1",
      repo_id: "repo-1",
      pr_branch: "greensecops/terraform-12345678",
      pr_url: "https://github.com/org/repo/pull/1",
      pr_state: state,
    })
    const ready = { fixStatuses: ["ready" as FixStatus] }
    expect(engineActions(input(ready)).deliver.label).toBe("Create PR")
    expect(
      engineActions(input({ ...ready, existingPr: pr("open") })).deliver.label,
    ).toBe("Update PR")
    const reopen = engineActions(
      input({ ...ready, existingPr: pr("closed") }),
    ).deliver
    expect(reopen.label).toBe("Reopen PR")
    // Reopening needs to bypass the closed-PR delivery guard.
    expect(reopen.force).toBe(true)
  })

  it("delivers a fix only its own engine knows is re-openable", () => {
    // The CI engine can reopen a delivered fix whose PR was closed;
    // `deliverAction` decides that and passes the answer in.
    const a = engineActions(
      input({ fixStatuses: ["delivered"], reopenable: true }),
    )
    expect(a.deliver.disabled).toBe(false)
  })

  it("shows the request itself as busy", () => {
    const a = engineActions(input({ pending: { scan: true } }))
    expect(a.scan.label).toBe("Queuing…")
    expect(a.scan.busy).toBe(true)
    expect(a.scan.disabled).toBe(true)
  })
})

describe("isFixInFlight", () => {
  it("is the one definition the engine pages share", () => {
    expect(isFixInFlight("pending")).toBe(true)
    expect(isFixInFlight("generating")).toBe(true)
    expect(isFixInFlight("delivering")).toBe(true)
    expect(isFixInFlight("ready")).toBe(false)
    expect(isFixInFlight(null)).toBe(false)
    expect(isFixInFlight(undefined)).toBe(false)
  })
})
