import * as childProcess from "node:child_process"
import * as fs from "node:fs"
import * as os from "node:os"
import type { MetricsSample, RunnerSpecs } from "./types"

/** Root-filesystem usage from `df`, or null when unavailable (not fatal). */
function readDiskKb(): {
  totalKb: number
  usedKb: number
  freeKb: number
} | null {
  try {
    const dfOut = childProcess.execFileSync("df", ["-Pk", "/"], {
      encoding: "utf8",
    })
    const parts = dfOut.trim().split("\n")[1]?.split(/\s+/)
    if (!parts || parts.length < 4) return null
    return {
      totalKb: parseInt(parts[1] ?? "0", 10),
      usedKb: parseInt(parts[2] ?? "0", 10),
      freeKb: parseInt(parts[3] ?? "0", 10),
    }
  } catch {
    return null
  }
}

function kbToGb(kb: number): number {
  return Math.round((kb / 1024 ** 2) * 100) / 100
}

export function getRunnerSpecs(): RunnerSpecs {
  const cpus = os.cpus()
  const totalMem = os.totalmem()

  const specs: RunnerSpecs = {
    os: process.env.RUNNER_OS ?? os.type(),
    arch: process.env.RUNNER_ARCH ?? os.arch(),
    runner_name: process.env.RUNNER_NAME ?? "unknown",
    platform: os.platform(),
    node_version: process.version,
    vcpus: cpus.length,
    ram_total_gb: Math.round((totalMem / 1024 ** 3) * 100) / 100,
  }

  const disk = readDiskKb()
  if (disk) {
    specs.disk_total_gb = kbToGb(disk.totalKb)
    specs.disk_free_gb = kbToGb(disk.freeKb)
  }

  return specs
}

export function getMetricsSample(): MetricsSample {
  const sample: MetricsSample = { collected_at: Date.now() / 1000 }

  const freeMem = os.freemem()
  const totalMem = os.totalmem()
  const usedMem = totalMem - freeMem
  sample.ram_used_mb = Math.round((usedMem / 1024 ** 2) * 10) / 10
  sample.ram_percent = Math.round((usedMem / totalMem) * 1000) / 10

  // load average as cpu utilisation proxy (unix only; 0 on Windows)
  const loadAvg = os.loadavg()
  const cpuCount = os.cpus().length
  if (loadAvg[0] > 0) {
    sample.cpu_load_percent = Math.min(
      100,
      Math.round((loadAvg[0] / cpuCount) * 1000) / 10,
    )
  }

  const disk = readDiskKb()
  if (disk) {
    sample.disk_used_gb = kbToGb(disk.usedKb)
  }

  try {
    const netDev = fs.readFileSync("/proc/net/dev", "utf8")
    let totalSent = 0
    let totalRecv = 0
    for (const line of netDev.split("\n").slice(2)) {
      const trimmed = line.trim()
      if (!trimmed || trimmed.startsWith("lo:")) continue
      const cols = trimmed.split(/\s+/)
      const recv = parseInt(cols[1] ?? "0", 10)
      const sent = parseInt(cols[9] ?? "0", 10)
      if (!Number.isNaN(recv)) totalRecv += recv
      if (!Number.isNaN(sent)) totalSent += sent
    }
    sample.net_bytes_recv = totalRecv
    sample.net_bytes_sent = totalSent
  } catch {
    // not on Linux or /proc unavailable — not fatal
  }

  return sample
}
