import * as fs from "node:fs"
import { run } from "./exec"
import type {
  ContainerStats,
  ContainerUsageMap,
  DockerBuildPayload,
  DockerLayer,
} from "./types"

/**
 * Docker build/runtime collection.
 *
 * Two tiers, and the difference matters to what the rules can say:
 *
 *  - **Zero-config** — diff `docker images` between the pre and post steps,
 *    then `docker image inspect` + `docker history` whatever is new. Gives
 *    sizes and per-layer `created_by`, needs nothing from the user's workflow,
 *    and *cannot* tell whether a layer was cached.
 *  - **Opt-in** — a `docker buildx build --metadata-file` JSON supplied via the
 *    `docker_build_metadata` action input. This is the only source of
 *    cache-hit data, which is the most valuable metric of the set.
 *
 * Container behaviour is a third source and does not belong here: it has to be
 * measured while the containers are alive, which the post step is far too late
 * for. See containers.ts, which the daemon drives; this module only joins that
 * accumulator onto what `docker inspect` can still see.
 *
 * Every probe returns null on failure and is non-fatal, following telemetry.ts:
 * a runner without Docker, or with a different Docker, must never fail the
 * user's build over telemetry.
 */

/** Image ids currently present, for diffing pre against post. */
export function listImageIds(): string[] {
  const out = run("docker", ["images", "--no-trunc", "--format", "{{.ID}}"])
  if (!out) return []
  return out
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
}

/**
 * `docker history` gives per-layer size and the instruction that created it.
 *
 * `CreatedBy` is scrubbed before it leaves the runner: it is the literal RUN
 * command, which routinely contains build args and inline credentials. Only
 * the leading instruction keyword is kept — enough to attribute a layer,
 * impossible to leak a secret through.
 */
export function readLayers(imageId: string): DockerLayer[] | null {
  const out = run("docker", [
    "history",
    "--no-trunc",
    "--format",
    "{{.Size}}\t{{.CreatedBy}}",
    imageId,
  ])
  if (!out) return null
  const layers: DockerLayer[] = []
  for (const [index, line] of out.split("\n").entries()) {
    if (!line.trim()) continue
    const [size, createdBy = ""] = line.split("\t")
    layers.push({
      index,
      size_bytes: parseSize(size),
      instruction: scrubInstruction(createdBy),
    })
  }
  return layers
}

/** `docker history` prints human sizes ("1.2GB", "0B"); normalise to bytes. */
export function parseSize(raw: string | undefined): number {
  if (!raw) return 0
  const match = raw.trim().match(/^([\d.]+)\s*([A-Za-z]*)$/)
  if (!match) return 0
  const value = Number.parseFloat(match[1])
  if (Number.isNaN(value)) return 0
  const unit = (match[2] || "B").toUpperCase()
  const multipliers: Record<string, number> = {
    B: 1,
    KB: 1e3,
    MB: 1e6,
    GB: 1e9,
    TB: 1e12,
  }
  return Math.round(value * (multipliers[unit] ?? 1))
}

/**
 * Reduce a layer's creating command to its instruction keyword.
 *
 * The full text is deliberately discarded rather than redacted by pattern:
 * a denylist of secret-shaped substrings would leak anything it failed to
 * anticipate, and the keyword alone is all the rules use.
 */
export function scrubInstruction(createdBy: string): string {
  const cleaned = createdBy.replace(/^\/bin\/sh\s+-c\s+#\(nop\)\s*/, "").trim()
  const keyword = cleaned.split(/\s+/)[0] ?? ""
  return /^[A-Z]+$/.test(keyword) ? keyword : "RUN"
}

export function readImageSize(imageId: string): number | null {
  const out = run("docker", [
    "image",
    "inspect",
    "--format",
    "{{.Size}}",
    imageId,
  ])
  if (!out) return null
  const size = Number.parseInt(out.trim(), 10)
  return Number.isNaN(size) ? null : size
}

/**
 * Cache-hit ratio from a BuildKit `--metadata-file`, when the user opted in.
 *
 * Returns null rather than 0 when the file is absent or unreadable: 0 would be
 * indistinguishable from "every layer missed", which is exactly the condition
 * image_layer_cache_ineffective fires on.
 */
export function readCacheHitRatio(metadataPath: string): number | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(fs.readFileSync(metadataPath, "utf8"))
  } catch {
    return null
  }
  const steps = (parsed as { steps?: { cached?: boolean }[] })?.steps
  if (!Array.isArray(steps) || steps.length === 0) return null
  const cached = steps.filter((s) => s?.cached === true).length
  return cached / steps.length
}

/**
 * Per-container stats for the runtime rules.
 *
 * Two halves that have to be joined. `docker inspect` supplies the *declared*
 * shape — memory limit, healthcheck, restart count — but only for containers
 * that still exist. The daemon's accumulator supplies what was *measured*, and
 * survives the container's removal. A container that `docker compose down`
 * cleaned up before the post step appears here from the accumulator alone,
 * because dropping it would silently exclude exactly the short-lived
 * containers most likely to have been OOM-killed.
 */
export function readContainers(
  usage: ContainerUsageMap = {},
): ContainerStats[] | null {
  const ids = run("docker", ["ps", "-aq"])
  // A runner without Docker has neither half; a runner with Docker but no
  // surviving containers still has the accumulator.
  if (!ids && Object.keys(usage).length === 0) return null
  const stats: ContainerStats[] = []
  const seen = new Set<string>()

  for (const id of (ids ?? "")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)) {
    const out = run("docker", [
      "inspect",
      "--format",
      "{{.Name}}\t{{.State.OOMKilled}}\t{{.RestartCount}}\t{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}\t{{.HostConfig.Memory}}",
      id,
    ])
    if (!out) continue
    const [name = "", oom = "", restarts = "", health = "none", limit = "0"] =
      out.trim().split("\t")
    const cleanName = name.replace(/^\//, "")
    const measured = usage[cleanName]
    seen.add(cleanName)
    stats.push({
      name: cleanName,
      // Either source is authoritative for an OOM: inspect reports it while
      // the container survives, the event stream catches it when it does not.
      oom_killed: oom === "true" || measured?.oom_killed === true,
      restart_count: Number.parseInt(restarts, 10) || 0,
      has_healthcheck: health !== "none",
      health_status: health,
      mem_limit_bytes: Number.parseInt(limit, 10) || 0,
      peak_rss_bytes: measured?.peak_rss_bytes ?? null,
      peak_pids: measured?.peak_pids ?? null,
      cpu_throttled_percent: measured?.cpu_throttled_percent ?? null,
      exit_code: measured?.exit_code ?? null,
      observed: (measured?.samples ?? 0) > 0,
    })
  }

  for (const [name, measured] of Object.entries(usage)) {
    if (seen.has(name)) continue
    stats.push({
      name,
      oom_killed: measured.oom_killed,
      restart_count: 0,
      // Unknown rather than false: the container is gone, so we cannot tell
      // whether it declared a healthcheck. `none` keeps it out of the
      // healthcheck rules instead of reporting a healthy one as unhealthy.
      has_healthcheck: false,
      health_status: "none",
      // Null, not 0: `docker inspect` reports 0 for "explicitly unlimited",
      // which container_unbounded_memory fires on. Reporting 0 for a container
      // we simply could not inspect would invent that finding for every
      // container the job cleaned up.
      mem_limit_bytes: null,
      peak_rss_bytes: measured.peak_rss_bytes,
      peak_pids: measured.peak_pids,
      cpu_throttled_percent: measured.cpu_throttled_percent,
      exit_code: measured.exit_code,
      observed: measured.samples > 0,
    })
  }

  return stats
}

/**
 * Assemble the payload for one newly built image.
 *
 * Returns null when the image cannot be inspected at all — there is nothing
 * worth posting, and an empty row would make `observed_builds` misleading.
 */
export function collectBuild(
  imageId: string,
  workflowRunId: number,
  options: {
    metadataPath?: string
    dockerfilePath?: string
    usage?: ContainerUsageMap
  } = {},
): DockerBuildPayload | null {
  const imageSize = readImageSize(imageId)
  if (imageSize === null) return null
  return {
    workflow_run_id: workflowRunId,
    image_ref: imageId,
    dockerfile_path: options.dockerfilePath ?? null,
    image_size_bytes: imageSize,
    context_size_bytes: null,
    build_duration_ms: null,
    cache_hit_ratio: options.metadataPath
      ? readCacheHitRatio(options.metadataPath)
      : null,
    layers: readLayers(imageId),
    containers: readContainers(options.usage ?? {}),
  }
}
