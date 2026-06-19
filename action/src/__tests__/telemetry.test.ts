import { afterEach, describe, expect, it, mock, spyOn } from "bun:test"
import * as childProcess from "node:child_process"
import * as fs from "node:fs"
import * as os from "node:os"
import { getMetricsSample, getRunnerSpecs } from "../telemetry"

afterEach(() => {
  mock.restore()
  delete process.env.RUNNER_OS
  delete process.env.RUNNER_ARCH
  delete process.env.RUNNER_NAME
})

const FAKE_CPU: os.CpuInfo = {
  model: "Intel(R) Xeon(R)",
  speed: 2400,
  times: { user: 0, nice: 0, sys: 0, idle: 0, irq: 0 },
}

// df -Pk output: 100 GB total, 50 GB used, 50 GB free
const DF_OUTPUT =
  "Filesystem     1K-blocks      Used Available Use% Mounted on\n" +
  "/dev/sda1     104857600  52428800  52428800  50% /"

// /proc/net/dev with two real interfaces and loopback
const NET_DEV =
  "Inter-|   Receive                                                |  Transmit\n" +
  " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n" +
  "    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0\n" +
  "  eth0:  1234567    1000    0    0    0     0          0         0  7654321    2000    0    0    0     0       0          0\n" +
  "  eth1:   222222     500    0    0    0     0          0         0   333333     600    0    0    0     0       0          0\n"

describe("getRunnerSpecs", () => {
  it("returns vcpus and ram_total_gb from os", () => {
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU, FAKE_CPU, FAKE_CPU, FAKE_CPU])
    spyOn(os, "totalmem").mockReturnValue(16 * 1024 ** 3)
    spyOn(childProcess, "execFileSync").mockReturnValue(DF_OUTPUT)

    const specs = getRunnerSpecs()

    expect(specs.vcpus).toBe(4)
    expect(specs.ram_total_gb).toBe(16)
  })

  it("parses df output into disk_total_gb and disk_free_gb", () => {
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(childProcess, "execFileSync").mockReturnValue(DF_OUTPUT)

    const specs = getRunnerSpecs()

    expect(specs.disk_total_gb).toBe(100)
    expect(specs.disk_free_gb).toBe(50)
  })

  it("omits disk fields when df fails", () => {
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("df: command not found")
    })

    const specs = getRunnerSpecs()

    expect(specs.disk_total_gb).toBeUndefined()
    expect(specs.disk_free_gb).toBeUndefined()
  })

  it("uses RUNNER_* env vars when present", () => {
    process.env.RUNNER_OS = "Linux"
    process.env.RUNNER_ARCH = "ARM64"
    process.env.RUNNER_NAME = "my-runner"
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(childProcess, "execFileSync").mockReturnValue(DF_OUTPUT)

    const specs = getRunnerSpecs()

    expect(specs.os).toBe("Linux")
    expect(specs.arch).toBe("ARM64")
    expect(specs.runner_name).toBe("my-runner")
  })
})

describe("getMetricsSample", () => {
  it("computes ram_used_mb and ram_percent from os memory", () => {
    // 8 GB total, 2 GB free → 6 GB used = 6144 MB, 75%
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(os, "freemem").mockReturnValue(2 * 1024 ** 3)
    spyOn(os, "loadavg").mockReturnValue([0, 0, 0])
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("no df")
    })
    spyOn(fs, "readFileSync").mockImplementation(() => {
      throw new Error("no proc")
    })

    const sample = getMetricsSample()

    expect(sample.ram_used_mb).toBe(6144)
    expect(sample.ram_percent).toBe(75)
  })

  it("computes cpu_load_percent when loadavg > 0", () => {
    // load 2.0 on 4 CPUs → 50%
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(os, "freemem").mockReturnValue(4 * 1024 ** 3)
    spyOn(os, "loadavg").mockReturnValue([2, 1.5, 1])
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU, FAKE_CPU, FAKE_CPU, FAKE_CPU])
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("no df")
    })
    spyOn(fs, "readFileSync").mockImplementation(() => {
      throw new Error("no proc")
    })

    const sample = getMetricsSample()

    expect(sample.cpu_load_percent).toBe(50)
  })

  it("omits cpu_load_percent when loadavg is 0", () => {
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(os, "freemem").mockReturnValue(4 * 1024 ** 3)
    spyOn(os, "loadavg").mockReturnValue([0, 0, 0])
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("no df")
    })
    spyOn(fs, "readFileSync").mockImplementation(() => {
      throw new Error("no proc")
    })

    const sample = getMetricsSample()

    expect(sample.cpu_load_percent).toBeUndefined()
  })

  it("parses /proc/net/dev and excludes loopback", () => {
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(os, "freemem").mockReturnValue(4 * 1024 ** 3)
    spyOn(os, "loadavg").mockReturnValue([0, 0, 0])
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("no df")
    })
    spyOn(fs, "readFileSync").mockReturnValue(NET_DEV)

    const sample = getMetricsSample()

    expect(sample.net_bytes_recv).toBe(1234567 + 222222)
    expect(sample.net_bytes_sent).toBe(7654321 + 333333)
  })

  it("omits net fields when /proc/net/dev is unavailable", () => {
    spyOn(os, "totalmem").mockReturnValue(8 * 1024 ** 3)
    spyOn(os, "freemem").mockReturnValue(4 * 1024 ** 3)
    spyOn(os, "loadavg").mockReturnValue([0, 0, 0])
    spyOn(os, "cpus").mockReturnValue([FAKE_CPU])
    spyOn(childProcess, "execFileSync").mockImplementation(() => {
      throw new Error("no df")
    })
    spyOn(fs, "readFileSync").mockImplementation(() => {
      throw new Error("ENOENT")
    })

    const sample = getMetricsSample()

    expect(sample.net_bytes_recv).toBeUndefined()
    expect(sample.net_bytes_sent).toBeUndefined()
  })
})
