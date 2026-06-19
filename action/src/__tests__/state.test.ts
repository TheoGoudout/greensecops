import { afterEach, describe, expect, it, mock, spyOn } from "bun:test"
import * as fs from "node:fs"
import { killDaemon, loadState } from "../state"

afterEach(() => {
  mock.restore()
})

const FAKE_STATE = {
  daemonPid: 12345,
  greensecopsUrl: "https://app.example.com",
  oidcToken: "token-abc",
  workflowRunId: 99,
  repository: "owner/repo",
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
