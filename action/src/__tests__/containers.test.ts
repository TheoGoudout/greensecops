import { afterEach, describe, expect, mock, spyOn, test } from "bun:test"
import * as childProcess from "node:child_process"
import * as fs from "node:fs"
import {
  accumulate,
  drainEvents,
  parseStatsSize,
  readCgroupThrottling,
  sampleContainers,
} from "../containers"
import type { ContainerUsageMap } from "../types"

afterEach(() => {
  mock.restore()
})

/** Route docker subcommands the same way docker.test.ts does. */
function mockDocker(responses: Record<string, string | Error>) {
  spyOn(childProcess, "execFileSync").mockImplementation(((
    _cmd: string,
    args: string[],
  ) => {
    const reply = responses[args[0]]
    if (reply === undefined || reply instanceof Error) {
      throw reply ?? new Error(`no mock for docker ${args[0]}`)
    }
    return reply
  }) as unknown as typeof childProcess.execFileSync)
}

/** Serve cgroup files by suffix; anything unmapped throws, as a real read would. */
function mockCgroup(files: Record<string, string>) {
  spyOn(fs, "readFileSync").mockImplementation(((p: string) => {
    for (const [suffix, body] of Object.entries(files)) {
      if (p.endsWith(suffix)) return body
    }
    throw new Error(`ENOENT: ${p}`)
  }) as unknown as typeof fs.readFileSync)
}

describe("parseStatsSize", () => {
  test("parses the binary units docker stats prints", () => {
    expect(parseStatsSize("1.5GiB")).toBe(1_610_612_736)
    expect(parseStatsSize("512MiB")).toBe(536_870_912)
    expect(parseStatsSize("4KiB")).toBe(4096)
    expect(parseStatsSize("900B")).toBe(900)
  })

  test("still parses decimal units", () => {
    expect(parseStatsSize("1.2GB")).toBe(1_200_000_000)
    expect(parseStatsSize("45.7MB")).toBe(45_700_000)
  })

  test("does not silently mis-scale a binary unit", () => {
    // The bug this parser exists to avoid: a decimal-only table misses "GIB",
    // falls through to a multiplier of 1 and records 1.5GiB as 2 bytes.
    expect(parseStatsSize("1.5GiB")).toBeGreaterThan(1_000_000_000)
  })

  test("returns null rather than 0 for anything unrecognised", () => {
    // 0 would be merged as a genuine measurement of zero bytes.
    expect(parseStatsSize(undefined)).toBeNull()
    expect(parseStatsSize("")).toBeNull()
    expect(parseStatsSize("n/a")).toBeNull()
    expect(parseStatsSize("12ZB")).toBeNull()
  })
})

describe("sampleContainers", () => {
  test("splits usage from the limit docker stats prints alongside it", () => {
    mockDocker({ stats: "abc123\tapi\t1.5GiB / 7.7GiB\t12\n" })
    expect(sampleContainers()).toEqual([
      { id: "abc123", name: "api", rssBytes: 1_610_612_736, pids: 12 },
    ])
  })

  test("returns an empty list when docker is unavailable", () => {
    mockDocker({})
    expect(sampleContainers()).toEqual([])
  })
})

describe("drainEvents", () => {
  test("parses oom and die events", () => {
    mockDocker({ events: "worker\toom\t\napi\tdie\t137\n" })
    expect(drainEvents(0, 100)).toEqual([
      { name: "worker", action: "oom", exitCode: null },
      { name: "api", action: "die", exitCode: 137 },
    ])
  })

  test("returns an empty list when docker is unavailable", () => {
    mockDocker({})
    expect(drainEvents(0, 100)).toEqual([])
  })
})

describe("readCgroupThrottling", () => {
  test("reports the share of periods that were throttled", () => {
    mockCgroup({ "cpu.stat": "usage_usec 100\nnr_periods 200\nnr_throttled 50\n" })
    expect(readCgroupThrottling("abc")).toBe(25)
  })

  test("returns null when no CPU quota is set", () => {
    // nr_periods is 0 without a quota. Reporting 0% would claim we measured
    // an absence of throttling rather than an absence of a limit.
    mockCgroup({ "cpu.stat": "usage_usec 100\nnr_periods 0\nnr_throttled 0\n" })
    expect(readCgroupThrottling("abc")).toBeNull()
  })

  test("returns null when the cgroup is unreadable", () => {
    mockCgroup({})
    expect(readCgroupThrottling("abc")).toBeNull()
  })
})

describe("accumulate", () => {
  test("prefers the kernel high-water mark over the instantaneous sample", () => {
    mockCgroup({ "memory.peak": "900000000\n" })
    const usage = accumulate({}, [
      { id: "c1", name: "api", rssBytes: 100_000_000, pids: 3 },
    ])
    expect(usage.api.peak_rss_bytes).toBe(900_000_000)
  })

  test("falls back to the sample when the cgroup is unreadable", () => {
    mockCgroup({})
    const usage = accumulate({}, [
      { id: "c1", name: "api", rssBytes: 100_000_000, pids: 3 },
    ])
    expect(usage.api.peak_rss_bytes).toBe(100_000_000)
    expect(usage.api.peak_pids).toBe(3)
  })

  test("peaks only ever move upward", () => {
    mockCgroup({})
    const first = accumulate({}, [
      { id: "c1", name: "api", rssBytes: 500, pids: 9 },
    ])
    const second = accumulate(first, [
      { id: "c1", name: "api", rssBytes: 100, pids: 2 },
    ])
    expect(second.api.peak_rss_bytes).toBe(500)
    expect(second.api.peak_pids).toBe(9)
    expect(second.api.samples).toBe(2)
  })

  test("records a container seen only in the event stream", () => {
    // A container that started and died between two ticks is never sampled,
    // but its OOM still has to reach the rules.
    mockCgroup({})
    const usage = accumulate({}, [], [
      { name: "worker", action: "oom", exitCode: null },
      { name: "worker", action: "die", exitCode: 137 },
    ])
    expect(usage.worker.oom_killed).toBe(true)
    expect(usage.worker.exit_code).toBe(137)
    expect(usage.worker.samples).toBe(0)
  })

  test("replaying the same events is idempotent", () => {
    // The post step re-drains from the start of the job, so events the daemon
    // already folded in arrive a second time.
    mockCgroup({})
    const events = [{ name: "worker", action: "oom", exitCode: null }]
    const once = accumulate({}, [], events)
    const twice = accumulate(once, [], events)
    expect(twice).toEqual(once)
  })

  test("leaves unmeasured counters null rather than zero", () => {
    mockCgroup({})
    const usage: ContainerUsageMap = accumulate({}, [
      { id: "c1", name: "api", rssBytes: null, pids: null },
    ])
    expect(usage.api.peak_rss_bytes).toBeNull()
    expect(usage.api.cpu_throttled_percent).toBeNull()
  })
})
