import { describe, expect, it } from "vitest"
import type { PullRequestPublic } from "@/client"
import {
  type EngineFlowInput,
  engineFlow,
  type FlowStageId,
  type FlowStageState,
} from "@/lib/engine-flow"

/**
 * The rail's one invariant is that it cannot contradict the buttons under it:
 * it asks `targetActivity` the same question `engineActions` does. These check
 * that, and that a stage says something true when it has nothing to report.
 */

function input(overrides: Partial<EngineFlowInput> = {}): EngineFlowInput {
  return {
    targetLabel: "Terraform root",
    scope: "target",
    isAccessible: true,
    enabled: true,
    capabilities: { sync: false },
    ...overrides,
  }
}

function byId(stages: ReturnType<typeof engineFlow>) {
  return new Map(stages.map((s) => [s.id, s]))
}

function stateOf(
  overrides: Partial<EngineFlowInput>,
  id: FlowStageId,
): FlowStageState | undefined {
  return byId(engineFlow(input(overrides))).get(id)?.state
}

const openPr = { pr_state: "open" } as PullRequestPublic
const closedPr = { pr_state: "closed" } as PullRequestPublic

describe("engineFlow", () => {
  it("draws only the stages the engine declares", () => {
    expect(engineFlow(input()).map((s) => s.id)).toEqual([
      "scan",
      "fix",
      "deliver",
    ])
    // Cloud: no files to rewrite, so two stages rather than two dead ones.
    expect(
      engineFlow(
        input({ capabilities: { sync: false, fix: false, deliver: false } }),
      ).map((s) => s.id),
    ).toEqual(["scan"])
    // The CI engine is the only one that re-reads its files from GitHub.
    expect(
      engineFlow(input({ capabilities: {} })).map((s) => s.id),
    ).toEqual(["sync", "scan", "fix", "deliver"])
  })

  it("never marks more than one stage running", () => {
    // Three activities at once — a scan, a fix being written, a PR being
    // opened — still resolve to the single one `PRECEDENCE` names.
    const stages = engineFlow(
      input({
        capabilities: {},
        syncPending: false,
        scanStatus: "running",
        fixStatuses: ["pending", "delivering"],
      }),
    )
    const running = stages.filter((s) => s.state === "running")
    expect(running.map((s) => s.id)).toEqual(["scan"])
  })

  it("lights the stage the activity belongs to", () => {
    expect(stateOf({ scanStatus: "queued" }, "scan")).toBe("running")
    expect(stateOf({ fixStatuses: ["generating"] }, "fix")).toBe("running")
    expect(stateOf({ fixStatuses: ["delivering"] }, "deliver")).toBe("running")
  })

  it("reports a pending trigger as running, like the buttons do", () => {
    // The same pin `engineActions` uses, so the rail and the greyed bar say
    // the same thing during the window before the row exists.
    expect(stateOf({ pending: { scan: true } }, "scan")).toBe("running")
  })

  it("says a stage is done only while it has something to show", () => {
    expect(stateOf({ hasCompletedScan: true }, "scan")).toBe("done")
    expect(stateOf({ hasCompletedScan: false }, "scan")).toBe("todo")
    // A written fix counts whether or not it has shipped; a withdrawn one does
    // not, or the rail would report work that is no longer there.
    expect(stateOf({ fixStatuses: ["delivered"] }, "fix")).toBe("done")
    expect(stateOf({ fixStatuses: ["rejected_by_user"] }, "fix")).toBe(
      "blocked",
    )
    expect(stateOf({ fixStatuses: ["no_op"] }, "fix")).toBe("blocked")
  })

  it("does not call a closed pull request done", () => {
    expect(stateOf({ existingPr: openPr }, "deliver")).toBe("done")
    expect(
      stateOf({ existingPr: closedPr, fixStatuses: ["ready"] }, "deliver"),
    ).toBe("todo")
  })

  it("gives a blocked stage the sentence the button would have given", () => {
    const stages = byId(engineFlow(input({ isAccessible: false })))
    for (const id of ["scan", "fix", "deliver"] as const) {
      expect(stages.get(id)?.state).toBe("blocked")
      expect(stages.get(id)?.reason).toBe(
        "GitHub access to this repository was lost",
      )
    }
  })

  it("distinguishes nothing to fix from nothing wrong", () => {
    expect(byId(engineFlow(input())).get("fix")?.reason).toBe(
      "No open findings to fix",
    )
    expect(
      byId(engineFlow(input({ openFindingCount: 2 }))).get("fix")?.state,
    ).toBe("todo")
  })

  it("counts what each stage has, in its caption", () => {
    const stages = byId(
      engineFlow(
        input({
          hasCompletedScan: true,
          grade: "B",
          openFindingCount: 1,
          fixStatuses: ["ready", "ready"],
        }),
      ),
    )
    expect(stages.get("scan")?.detail).toBe("Grade B · 1 finding")
    expect(stages.get("fix")?.detail).toBe("2 fixes ready")
  })

  it("says what the sync stage last read, and when", () => {
    const stages = byId(
      engineFlow(
        input({
          capabilities: {},
          fileCount: 3,
          syncedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
        }),
      ),
    )
    expect(stages.get("sync")?.state).toBe("done")
    expect(stages.get("sync")?.detail).toBe("3 files · 3m ago")
  })
})
