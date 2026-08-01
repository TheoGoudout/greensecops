import * as fs from "node:fs"
import { run } from "./exec"
import type { ContainerUsage, ContainerUsageMap } from "./types"

/**
 * Per-container runtime sampling, accumulated across the life of a job.
 *
 * Why this runs in the daemon and not in the post step: CI containers do not
 * survive to post. `docker compose down`, `docker run --rm` and any test
 * harness's cleanup remove them, so a `docker ps -a` in the post step reports
 * nothing about the containers whose behaviour the runtime rules grade. The
 * daemon is the only part of the action alive while they exist.
 *
 * Three sources, in descending order of trust:
 *
 *  - **cgroup v2** — `memory.peak` and `pids.peak` are kernel-maintained
 *    high-water marks, so they are correct no matter how rarely we poll. A
 *    `docker stats` reading taken 30s after the spike is not.
 *  - **`docker stats`** — the fallback when the cgroup files are unreadable
 *    (older kernel, unexpected cgroup driver, rootless). Instantaneous, so the
 *    peak it yields is only a lower bound.
 *  - **`docker events`** — drained once per tick with an explicit `--until`, so
 *    it returns instead of streaming. This is what lets a container that both
 *    started and died between two ticks still contribute its OOM and exit
 *    facts.
 */

// Both cgroup v2 layouts Docker produces: the systemd driver names a scope per
// container, the cgroupfs driver nests them under a `docker` directory. Trying
// both is cheaper and steadier than parsing the daemon's configured driver.
const CGROUP_PATHS = [
  (id: string) => `/sys/fs/cgroup/system.slice/docker-${id}.scope`,
  (id: string) => `/sys/fs/cgroup/docker/${id}`,
]

const BINARY_UNITS: Record<string, number> = {
  B: 1,
  KIB: 1024,
  MIB: 1024 ** 2,
  GIB: 1024 ** 3,
  TIB: 1024 ** 4,
}

const DECIMAL_UNITS: Record<string, number> = {
  B: 1,
  KB: 1e3,
  MB: 1e6,
  GB: 1e9,
  TB: 1e12,
}

/**
 * Parse a size as `docker stats` prints it.
 *
 * Deliberately *not* docker.ts's `parseSize`. That one serves `docker history`,
 * which prints decimal units, and its multiplier table has no entry for the
 * binary ones — so "1.5GiB" would miss the table, fall through to a multiplier
 * of 1 and be recorded as 2 bytes. `docker stats` prints binary units, hence a
 * separate parser that understands both.
 *
 * Returns null rather than 0 for anything unrecognised, so an unparseable
 * reading is never merged into a peak as a real measurement of zero.
 */
export function parseStatsSize(raw: string | undefined): number | null {
  if (!raw) return null
  const match = raw.trim().match(/^([\d.]+)\s*([A-Za-z]*)$/)
  if (!match) return null
  const value = Number.parseFloat(match[1])
  if (Number.isNaN(value)) return null
  const unit = (match[2] || "B").toUpperCase()
  const multiplier = BINARY_UNITS[unit] ?? DECIMAL_UNITS[unit]
  if (multiplier === undefined) return null
  return Math.round(value * multiplier)
}

function readCgroupFile(id: string, file: string): string | null {
  for (const layout of CGROUP_PATHS) {
    try {
      return fs.readFileSync(`${layout(id)}/${file}`, "utf8")
    } catch {
      // wrong layout, or the container is already gone — try the next
    }
  }
  return null
}

function readCgroupNumber(id: string, file: string): number | null {
  const raw = readCgroupFile(id, file)
  if (raw === null) return null
  const value = Number.parseInt(raw.trim(), 10)
  return Number.isNaN(value) ? null : value
}

/** Kernel high-water mark for memory, in bytes. Needs cgroup v2 and kernel ≥5.19. */
export function readCgroupPeakRss(id: string): number | null {
  return readCgroupNumber(id, "memory.peak")
}

/** Kernel high-water mark for the process count. */
export function readCgroupPeakPids(id: string): number | null {
  return readCgroupNumber(id, "pids.peak")
}

/**
 * Share of CPU scheduling periods in which the container was throttled.
 *
 * `nr_throttled / nr_periods` rather than `throttled_usec / usage_usec`: the
 * period ratio is what a CPU quota actually governs, and it stays meaningful
 * for a container that is throttled often but briefly. Returns null when
 * `nr_periods` is 0, which is the normal reading for a container with no CPU
 * quota — no quota means no throttling, and reporting 0% would imply we had
 * measured something.
 */
export function readCgroupThrottling(id: string): number | null {
  const raw = readCgroupFile(id, "cpu.stat")
  if (raw === null) return null
  const values: Record<string, number> = {}
  for (const line of raw.split("\n")) {
    const [key, value] = line.trim().split(/\s+/)
    if (key && value !== undefined) values[key] = Number.parseInt(value, 10)
  }
  const periods = values.nr_periods
  const throttled = values.nr_throttled
  if (!periods || Number.isNaN(periods) || Number.isNaN(throttled)) return null
  return Math.round((throttled / periods) * 1000) / 10
}

export interface ContainerSample {
  id: string
  name: string
  rssBytes: number | null
  pids: number | null
}

/**
 * One reading of every running container.
 *
 * `docker stats --no-stream` is a single shot rather than the streaming form:
 * it fits the same execFileSync contract as every other probe, needs no child
 * process to supervise, and the cgroup peaks above are what carry the accuracy
 * that streaming would otherwise be needed for.
 */
export function sampleContainers(): ContainerSample[] {
  const out = run("docker", [
    "stats",
    "--no-stream",
    "--format",
    "{{.ID}}\t{{.Name}}\t{{.MemUsage}}\t{{.PIDs}}",
  ])
  if (!out) return []
  const samples: ContainerSample[] = []
  for (const line of out.split("\n")) {
    if (!line.trim()) continue
    const [id = "", name = "", memUsage = "", pids = ""] = line.split("\t")
    if (!id) continue
    // "1.5GiB / 7.7GiB" — the left side is usage, the right the effective
    // limit. The declared limit comes from `docker inspect` instead, because
    // stats reports host memory when no limit is set.
    const used = memUsage.split("/")[0]
    const parsedPids = Number.parseInt(pids, 10)
    samples.push({
      id,
      name,
      rssBytes: parseStatsSize(used),
      pids: Number.isNaN(parsedPids) ? null : parsedPids,
    })
  }
  return samples
}

export interface ContainerEvent {
  name: string
  action: string
  exitCode: number | null
}

/**
 * Container events in a closed time window.
 *
 * `--until` is what makes this return rather than stream, so it can be called
 * from the same tick loop as everything else. Without it the daemon would need
 * a supervised long-lived child just to notice that a container died.
 */
export function drainEvents(
  sinceSec: number,
  untilSec: number,
): ContainerEvent[] {
  const out = run("docker", [
    "events",
    "--since",
    String(Math.floor(sinceSec)),
    "--until",
    String(Math.floor(untilSec)),
    "--filter",
    "type=container",
    "--format",
    "{{.Actor.Attributes.name}}\t{{.Action}}\t{{.Actor.Attributes.exitCode}}",
  ])
  if (!out) return []
  const events: ContainerEvent[] = []
  for (const line of out.split("\n")) {
    if (!line.trim()) continue
    const [name = "", action = "", exitCode = ""] = line.split("\t")
    if (!name || !action) continue
    const parsed = Number.parseInt(exitCode, 10)
    events.push({
      name,
      action,
      exitCode: Number.isNaN(parsed) ? null : parsed,
    })
  }
  return events
}

function blankUsage(name: string, id: string): ContainerUsage {
  return {
    name,
    id,
    peak_rss_bytes: null,
    peak_pids: null,
    cpu_throttled_percent: null,
    oom_killed: false,
    exit_code: null,
    samples: 0,
  }
}

function highest(
  current: number | null,
  candidate: number | null,
): number | null {
  if (candidate === null) return current
  if (current === null) return candidate
  return Math.max(current, candidate)
}

/**
 * Fold one tick's readings into the running accumulator.
 *
 * Keyed by container name because that is the identifier the runtime rules
 * report and the only one an event carries. Peaks only ever move upward, so a
 * container that has already been observed keeps its high-water mark after it
 * stops being sampled — which is the point, since it will be gone by post.
 */
export function accumulate(
  previous: ContainerUsageMap,
  samples: ContainerSample[],
  events: ContainerEvent[] = [],
): ContainerUsageMap {
  const usage: ContainerUsageMap = { ...previous }

  for (const sample of samples) {
    const entry = usage[sample.name] ?? blankUsage(sample.name, sample.id)
    // Prefer the kernel's high-water mark; the stats reading is a lower bound
    // taken at whatever moment the tick happened to land on.
    const peakRss = readCgroupPeakRss(sample.id)
    entry.id = sample.id
    entry.peak_rss_bytes = highest(
      entry.peak_rss_bytes,
      peakRss ?? sample.rssBytes,
    )
    entry.peak_pids = highest(
      entry.peak_pids,
      readCgroupPeakPids(sample.id) ?? sample.pids,
    )
    entry.cpu_throttled_percent = highest(
      entry.cpu_throttled_percent,
      readCgroupThrottling(sample.id),
    )
    entry.samples += 1
    usage[sample.name] = entry
  }

  for (const event of events) {
    const entry = usage[event.name] ?? blankUsage(event.name, "")
    if (event.action === "oom") entry.oom_killed = true
    if (event.action === "die" && event.exitCode !== null) {
      entry.exit_code = event.exitCode
    }
    usage[event.name] = entry
  }

  return usage
}

export function loadUsage(file: string): ContainerUsageMap {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8")) as ContainerUsageMap
  } catch {
    return {}
  }
}

export function saveUsage(file: string, usage: ContainerUsageMap): void {
  try {
    fs.writeFileSync(file, JSON.stringify(usage), "utf8")
  } catch {
    // a runner with a read-only temp dir loses container peaks, not the build
  }
}
