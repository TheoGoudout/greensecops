import { describe, expect, it } from "vitest"
import type { FixStatus, PullRequestPublic, ScanStatus } from "@/client"
import {
  actionBlockedReason,
  type EngineActionInput,
  engineActions,
  fixActions,
  ignoreAction,
  isFixInFlight,
  isSpentFix,
  queueableFindings,
  removeAction,
  syncAction,
  type TargetActionId,
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

describe("the blocking table", () => {
  // The mirror of `BLOCKS` in
  // `backend/app/services/state_machines/engine_target.py`. Spelled out as a
  // table rather than derived, so a change on either side has to be made twice
  // deliberately instead of once by accident.
  const table: Record<TargetActionId, [boolean, boolean, boolean]> = {
    //          scanning  generating  delivering
    scan: [true, true, true],
    generate: [true, false, true],
    deliver: [true, true, true],
    remove: [true, true, true],
    ignore: [true, false, false],
    sync: [true, false, false],
  }
  const cases: [string, EngineActionInput][] = [
    ["scanning", input({ scanStatus: "running" })],
    ["generating", input({ fixStatuses: ["generating"] })],
    ["delivering", input({ fixStatuses: ["delivering"] })],
  ]

  for (const [action, blocked] of Object.entries(table) as [
    TargetActionId,
    [boolean, boolean, boolean],
  ][]) {
    cases.forEach(([activity, given], i) => {
      it(`${blocked[i] ? "refuses" : "allows"} ${action} while ${activity}`, () => {
        expect(actionBlockedReason(action, given) !== null).toBe(blocked[i])
      })
    })
    it(`allows ${action} on an idle target`, () => {
      expect(actionBlockedReason(action, input())).toBeNull()
    })
  }

  it("phrases each refusal the way the 409 does", () => {
    const scanning = input({ scanStatus: "running" })
    expect(actionBlockedReason("remove", scanning)).toBe(
      "Cannot remove this target while a scan is already running",
    )
    expect(actionBlockedReason("ignore", scanning)).toBe(
      "Cannot change a finding while a scan is already running",
    )
    expect(actionBlockedReason("sync", scanning)).toBe(
      "Cannot sync from GitHub while a scan is already running",
    )
  })
})

describe("quota", () => {
  const spent = "You've used all 50 analyses included in the Free plan."

  it("greys the action that spends the exhausted meter", () => {
    const a = engineActions(input({ quota: { analyses: spent } }))
    expect(a.scan.disabled).toBe(true)
    // Verbatim: the tooltip is the sentence the 402 would have carried.
    expect(a.scan.reason).toBe(spent)
    expect(a.generate.disabled).toBe(false)
  })

  it("greys generation on the fixes meter, not the analyses one", () => {
    const a = engineActions(input({ quota: { fixes: spent } }))
    expect(a.generate.reason).toBe(spent)
    expect(a.scan.disabled).toBe(false)
  })

  it("says nothing when the allowance is unspent or unknown", () => {
    expect(engineActions(input({ quota: {} })).scan.reason).toBeNull()
    expect(
      engineActions(input({ quota: { analyses: null } })).scan.reason,
    ).toBeNull()
    expect(engineActions(input()).scan.reason).toBeNull()
  })

  it("names a standing condition before a temporary one", () => {
    const a = engineActions(
      input({ quota: { analyses: spent }, scanStatus: "running" }),
    )
    expect(a.scan.reason).toBe(spent)
  })

  it("leaves the actions that spend nothing alone", () => {
    const given = input({ quota: { analyses: spent, fixes: spent } })
    expect(actionBlockedReason("deliver", given)).toBeNull()
    expect(actionBlockedReason("remove", given)).toBeNull()
    expect(actionBlockedReason("ignore", given)).toBeNull()
  })
})

describe("removeAction", () => {
  it("is refused by anything a worker holds", () => {
    expect(removeAction(input({ scanStatus: "running" })).disabled).toBe(true)
    expect(removeAction(input({ fixStatuses: ["delivering"] })).disabled).toBe(
      true,
    )
  })

  it("survives lost access and a disabled target", () => {
    // Cleaning up a target on a repository the App was uninstalled from is
    // exactly when someone reaches for this, and the DELETE has no such check.
    expect(removeAction(input({ isAccessible: false })).disabled).toBe(false)
    expect(removeAction(input({ enabled: false })).disabled).toBe(false)
  })
})

describe("syncAction", () => {
  it("keeps the access check the other GitHub actions have", () => {
    expect(syncAction(input({ isAccessible: false })).reason).toBe(
      "GitHub access to this repository was lost",
    )
  })

  it("waits for a scan but not for fix work", () => {
    expect(syncAction(input({ scanStatus: "queued" })).disabled).toBe(true)
    expect(syncAction(input({ fixStatuses: ["generating"] })).disabled).toBe(
      false,
    )
  })
})

describe("ignoreAction", () => {
  it("names the direction it would move the finding", () => {
    expect(ignoreAction("open", input()).label).toBe("Ignore")
    expect(ignoreAction("ignored", input()).label).toBe("Unignore")
  })

  it("refuses a resolved finding", () => {
    // `FindingMachine.ignore` is legal only from open/fix_in_progress; this
    // used to return the row unchanged and toast as though it had worked.
    const a = ignoreAction("resolved", input())
    expect(a.disabled).toBe(true)
    expect(a.reason).toBe("This finding is already resolved")
  })

  it("still allows muting while fixes are being written", () => {
    expect(
      ignoreAction("open", input({ fixStatuses: ["generating"] })).disabled,
    ).toBe(false)
    expect(
      ignoreAction("open", input({ scanStatus: "running" })).disabled,
    ).toBe(true)
  })

  it("needs no GitHub access — muting is a database write", () => {
    expect(ignoreAction("open", input({ isAccessible: false })).disabled).toBe(
      false,
    )
  })
})

describe("queueableFindings", () => {
  const finding = (file_path: string, status?: "open" | "ignored") => ({
    file_path,
    status,
  })

  it("drops a file whose fix is already written", () => {
    // `prepare_pending_fix` returns None for it, so the request would answer
    // 202 `{queued: 0}` while the page toasted "Fix generation queued".
    const fixes = new Map([["a.tf", { status: "ready" as FixStatus }]])
    expect(
      queueableFindings([finding("a.tf"), finding("b.tf")], fixes),
    ).toHaveLength(1)
  })

  it("keeps a file whose fix failed — that one is re-queued in place", () => {
    const fixes = new Map([["a.tf", { status: "failed" as FixStatus }]])
    expect(queueableFindings([finding("a.tf")], fixes)).toHaveLength(1)
  })

  it("keeps a file whose fix is still being written", () => {
    // It queues nothing either, but the button already says "Generating…" over
    // a spinner, which is the truthful account of that.
    const fixes = new Map([["a.tf", { status: "generating" as FixStatus }]])
    expect(queueableFindings([finding("a.tf")], fixes)).toHaveLength(1)
  })

  it("drops findings that are no longer open", () => {
    expect(queueableFindings([finding("a.tf", "ignored")], new Map())).toEqual(
      [],
    )
  })
})

describe("isSpentFix", () => {
  it("is true exactly where a plain generate would queue nothing", () => {
    for (const status of [
      "ready",
      "delivered",
      "landed",
      "no_op",
      "rejected_by_user",
      "superseded_by_closed_pr",
      "superseded_by_deleted_file",
    ] as FixStatus[]) {
      expect(isSpentFix(status)).toBe(true)
    }
    // A failed fix is re-queued in place; an in-flight one is being written.
    for (const status of [
      "failed",
      "pending",
      "generating",
      "delivering",
    ] as FixStatus[]) {
      expect(isSpentFix(status)).toBe(false)
    }
    expect(isSpentFix(undefined)).toBe(false)
  })

  it("turns the generate button into a regenerate", () => {
    const a = engineActions(input({ scope: "file", regenerate: true }))
    expect(a.generate.label).toBe("Regenerate fix")
    expect(a.generate.force).toBe(true)
  })
})

describe("fixActions", () => {
  const ready = { label: "Create PR", force: false }

  it("offers all three even where only one is live", () => {
    const a = fixActions({ status: "ready", delivery: ready })
    expect(a.deliver.disabled).toBe(false)
    expect(a.reject.disabled).toBe(false)
    expect(a.retry.disabled).toBe(true)
    expect(a.retry.reason).toBe("Only a failed fix can be retried")
  })

  it("accounts for every terminal status rather than hiding the button", () => {
    const cases: [FixStatus, string][] = [
      ["failed", "This fix failed to generate — retry it first"],
      ["landed", "This fix has already been merged"],
      ["no_op", "This rewrite changed nothing, so there is nothing to deliver"],
      ["rejected_by_user", "This fix was rejected"],
      ["superseded_by_deleted_file", "The file this fix targets was deleted"],
    ]
    for (const [status, reason] of cases) {
      const a = fixActions({ status, delivery: null })
      expect(a.deliver.disabled).toBe(true)
      expect(a.deliver.reason).toBe(reason)
    }
  })

  it("mirrors FixMachine on which statuses can be rejected", () => {
    // `reject` has no edge from these four; the DELETE is a silent no-op there.
    for (const status of [
      "failed",
      "landed",
      "no_op",
      "rejected_by_user",
    ] as FixStatus[]) {
      expect(fixActions({ status, delivery: null }).reject.disabled).toBe(true)
    }
    // It does have one from `delivering`, so that stays live.
    expect(
      fixActions({ status: "delivering", delivery: null }).reject.disabled,
    ).toBe(false)
  })

  it("retries only a failed fix, and not while the repo is scanning", () => {
    expect(fixActions({ status: "failed" }).retry.disabled).toBe(false)
    expect(
      fixActions({ status: "failed", activity: "scanning" }).retry.reason,
    ).toBe("Cannot generate fixes while a scan is already running")
  })

  it("has nothing to say about a fix that does not exist yet", () => {
    const a = fixActions({ status: null })
    for (const action of [a.deliver, a.retry, a.reject]) {
      expect(action.disabled).toBe(true)
      expect(action.reason).toBe("Generate a fix first")
    }
  })

  it("takes the delivery's own label and force flag", () => {
    const a = fixActions({
      status: "superseded_by_closed_pr",
      delivery: { label: "Reopen PR", force: true },
    })
    expect(a.deliver.disabled).toBe(false)
    expect(a.deliver.label).toBe("Reopen PR")
    expect(a.deliver.force).toBe(true)
  })

  it("refuses a delivery on a repository it cannot reach", () => {
    expect(
      fixActions({ status: "ready", delivery: ready, isAccessible: false })
        .deliver.reason,
    ).toBe("GitHub access to this repository was lost")
  })
})

describe("the three sources of an activity", () => {
  it("takes the server's answer even with nothing else to go on", () => {
    // A list row carries `activity` and no fix statuses at all; before it was
    // published, a collapsed card had to fetch a fix list it never rendered
    // just to know whether its buttons were live.
    expect(targetActivity(input({ activity: "generating" }))).toBe("generating")
    expect(engineActions(input({ activity: "delivering" })).scan.reason).toBe(
      "Cannot start a scan while a pull request is being opened",
    )
  })

  it("still derives from statuses the server has not caught up with", () => {
    // `idle` from the wire does not mean idle: the row may predate the fix this
    // page has just watched go `pending`.
    expect(
      targetActivity(input({ activity: "idle", fixStatuses: ["pending"] })),
    ).toBe("generating")
  })

  it("takes whichever source outranks the others", () => {
    expect(
      targetActivity(
        input({ activity: "generating", scanStatus: "running" }),
      ),
    ).toBe("scanning")
  })

  it("greys the whole bar the moment a trigger is in flight", () => {
    // The window this closes: the scan row does not exist until the POST
    // returns, so `generate` and `deliver` used to stay live over an analysis
    // already on its way.
    const a = engineActions(
      input({ fixStatuses: ["ready"], pending: { scan: true } }),
    )
    expect(a.generate.disabled).toBe(true)
    expect(a.generate.reason).toBe(
      "Cannot generate fixes while a scan is already running",
    )
    expect(a.deliver.disabled).toBe(true)
    expect(a.deliver.reason).toBe(
      "Cannot open a pull request while a scan is already running",
    )
  })

  it("lets a second file's fix be queued while the first is being written", () => {
    // The one engine action `generating` allows, and a pending generate must
    // not accidentally take it away.
    expect(
      engineActions(input({ pending: { generate: true } })).scan.reason,
    ).toBe("Cannot start a scan while fixes are being generated")
    expect(
      actionBlockedReason("generate", input({ pending: { generate: true } })),
    ).toBeNull()
  })

  it("carries the pin into the actions outside the bar", () => {
    expect(
      removeAction(input({ pending: { deliver: true } })).reason,
    ).toBe("Cannot remove this target while a pull request is being opened")
    expect(syncAction(input({ pending: { scan: true } })).reason).toBe(
      "Cannot sync from GitHub while a scan is already running",
    )
  })
})
