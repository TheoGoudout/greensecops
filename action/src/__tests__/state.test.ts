import { afterEach, describe, expect, it, mock, spyOn } from "bun:test"
import * as fs from "node:fs"
import { getGitHubContext, killDaemon, loadState } from "../state"

afterEach(() => {
  mock.restore()
  delete process.env.GITHUB_RUN_ID
  delete process.env.GITHUB_REPOSITORY
  delete process.env.GITHUB_REF
  delete process.env.GITHUB_SHA
  delete process.env.GITHUB_WORKFLOW
})

const FAKE_RUNNER_SPECS = {
  os: "Linux",
  arch: "x64",
  runner_name: "runner-1",
  platform: "linux",
  node_version: "v20",
  vcpus: 2,
  ram_total_gb: 8,
}

const FAKE_STATE = {
  daemonPid: 12345,
  greensecopsUrl: "https://app.example.com",
  oidcToken: "token-abc",
  workflowRunId: 99,
  repository: "owner/repo",
  runnerSpecs: FAKE_RUNNER_SPECS,
  startedAt: "2024-01-01T00:00:00.000Z",
}

describe("loadState", () => {
  it("returns parsed ActionState from valid JSON file", () => {
    spyOn(fs, "readFileSync").mockReturnValue(JSON.stringify(FAKE_STATE))

    const state = loadState("/tmp/test-state.json")

    expect(state).toEqual(FAKE_STATE)
  })

  it("returns null when file does not exist", () => {
    spyOn(fs, "readFileSync").mockImplementation(() => {
      throw Object.assign(new Error("ENOENT: no such file or directory"), {
        code: "ENOENT",
      })
    })

    const state = loadState("/tmp/missing.json")

    expect(state).toBeNull()
  })

  it("returns null on invalid JSON", () => {
    spyOn(fs, "readFileSync").mockReturnValue("not valid json{{{")

    const state = loadState("/tmp/bad.json")

    expect(state).toBeNull()
  })
})

describe("killDaemon", () => {
  it("does nothing when pid is 0", () => {
    const killSpy = spyOn(process, "kill").mockImplementation(() => true)

    killDaemon(0)

    expect(killSpy).not.toHaveBeenCalled()
  })

  it("sends SIGTERM to the given pid", () => {
    const killSpy = spyOn(process, "kill").mockImplementation(() => true)

    killDaemon(12345)

    expect(killSpy).toHaveBeenCalledWith(12345, "SIGTERM")
  })

  it("does not throw when process.kill fails", () => {
    spyOn(process, "kill").mockImplementation(() => {
      throw new Error("ESRCH: no such process")
    })

    expect(() => killDaemon(99999)).not.toThrow()
  })
})

describe("getGitHubContext", () => {
  it("reads all fields from environment", () => {
    process.env.GITHUB_RUN_ID = "42"
    process.env.GITHUB_REPOSITORY = "owner/repo"
    process.env.GITHUB_REF = "refs/heads/main"
    process.env.GITHUB_SHA = "abc123"
    process.env.GITHUB_WORKFLOW = "CI"

    const ctx = getGitHubContext()

    expect(ctx.workflowRunId).toBe(42)
    expect(ctx.repository).toBe("owner/repo")
    expect(ctx.branch).toBe("main")
    expect(ctx.commitSha).toBe("abc123")
    expect(ctx.workflowName).toBe("CI")
  })

  it("strips refs/heads/ prefix from branch", () => {
    process.env.GITHUB_REF = "refs/heads/feat/my-feature"

    const ctx = getGitHubContext()

    expect(ctx.branch).toBe("feat/my-feature")
  })

  it("defaults to empty strings and 0 when env vars are absent", () => {
    const ctx = getGitHubContext()

    expect(ctx.workflowRunId).toBe(0)
    expect(ctx.repository).toBe("")
    expect(ctx.branch).toBe("")
    expect(ctx.commitSha).toBe("")
    expect(ctx.workflowName).toBe("")
  })
})
