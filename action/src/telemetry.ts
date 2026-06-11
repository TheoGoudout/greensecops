import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import * as os from "node:os"
import type { MetricsSample, RunnerSpecs } from "./types"

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

  try {
    const dfOut = execFileSync("df", ["-Pk", "/"], { encoding: "utf8" })
    const parts = dfOut.trim().split("\n")[1]?.split(/\s+/)
    if (parts && parts.length >= 4) {
      const totalKb = parseInt(parts[1] ?? "0", 10)
      const freeKb = parseInt(parts[3] ?? "0", 10)
      specs.disk_total_gb = Math.round((totalKb / 1024 ** 2) * 100) / 100
      specs.disk_free_gb = Math.round((freeKb / 1024 ** 2) * 100) / 100
    }
  } catch {
    // disk info unavailable — not fatal
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

  try {
    const dfOut = execFileSync("df", ["-Pk", "/"], { encoding: "utf8" })
    const parts = dfOut.trim().split("\n")[1]?.split(/\s+/)
    if (parts && parts.length >= 3) {
      const usedKb = parseInt(parts[2] ?? "0", 10)
      sample.disk_used_gb = Math.round((usedKb / 1024 ** 2) * 100) / 100
    }
  } catch {
    // not fatal
  }

  try {
    const netDev = readFileSync("/proc/net/dev", "utf8")
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
