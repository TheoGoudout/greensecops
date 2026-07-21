import { afterEach, describe, expect, it, mock, spyOn } from "bun:test"
import * as childProcess from "node:child_process"
import { getTopProcesses } from "../native"

const originalPlatform = process.platform
const originalArch = process.arch

function setPlatformArch(platform: string, arch: string): void {
  Object.defineProperty(process, "platform", { value: platform })
  Object.defineProperty(process, "arch", { value: arch })
}

afterEach(() => {
  mock.restore()
  Object.defineProperty(process, "platform", { value: originalPlatform })
  Object.defineProperty(process, "arch", { value: originalArch })
})

const SAMPLE_JSON = JSON.stringify([
  {
    pid: 1,
    name: "bash",
    cpu_percent: 12.3,
    mem_percent: 4.5,
    mem_rss_mb: 10.2,
  },
])

describe("getTopProcesses", () => {
  it("returns null on non-linux platforms without spawning anything", () => {
    setPlatformArch("darwin", "x64")
    const spy = spyOn(childProcess, "execFileSync")

    const result = getTopProcesses()

    expect(result).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it("returns null for an unmapped architecture", () => {
    setPlatformArch("linux", "mips")
    const spy = spyOn(childProcess, "execFileSync")

    const result = getTopProcesses()

    expect(result).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it("parses valid JSON output on linux/x64", () => {
    setPlatformArch("linux", "x64")
    spyOn(childProcess, "execFileSync").mockReturnValue(SAMPLE_JSON)

    const result = getTopProcesses()

    expect(result).toEqual([
      {
        pid: 1,
        name: "bash",
        cpu_percent: 12.3,
        mem_percent: 4.5,
        mem_rss_mb: 10.2,
      },
    ])
  })

  it("returns null when the binary throws (missing/failed/timeout)", () => {
    setPlatformArch("linux", "arm64")
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("ENOENT")
    })

    const result = getTopProcesses()

    expect(result).toBeNull()
  })

  it("returns null when output is not valid JSON", () => {
    setPlatformArch("linux", "x64")
    spyOn(childProcess, "execFileSync").mockReturnValue("not json")

    const result = getTopProcesses()

    expect(result).toBeNull()
  })

  it("returns null when output is valid JSON but not an array", () => {
    setPlatformArch("linux", "x64")
    spyOn(childProcess, "execFileSync").mockReturnValue(
      JSON.stringify({ not: "an array" }),
    )

    const result = getTopProcesses()

    expect(result).toBeNull()
  })
})
