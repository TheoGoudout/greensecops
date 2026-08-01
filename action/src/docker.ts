import * as childProcess from "node:child_process"
import * as fs from "node:fs"
import type { ContainerStats, DockerBuildPayload, DockerLayer } from "./types"

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
 * Every probe returns null on failure and is non-fatal, following telemetry.ts:
 * a runner without Docker, or with a different Docker, must never fail the
 * user's build over telemetry.
 */

const EXEC_TIMEOUT_MS = 10_000
const MAX_BUFFER = 8 * 1024 * 1024

function run(cmd: string, args: string[]): string | null {
  try {
    return childProcess.execFileSync(cmd, args, {
      encoding: "utf8",
      timeout: EXEC_TIMEOUT_MS,
      maxBuffer: MAX_BUFFER,
      stdio: ["ignore", "pipe", "ignore"],
    })
  } catch {
    return null
  }
}

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

/** Per-container runtime stats, for the reliability rules. */
export function readContainers(): ContainerStats[] | null {
  const ids = run("docker", ["ps", "-aq"])
  if (!ids) return null
  const stats: ContainerStats[] = []
  for (const id of ids
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
    stats.push({
      name: name.replace(/^\//, ""),
      oom_killed: oom === "true",
      restart_count: Number.parseInt(restarts, 10) || 0,
      has_healthcheck: health !== "none",
      health_status: health,
      mem_limit_bytes: Number.parseInt(limit, 10) || 0,
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
  options: { metadataPath?: string; dockerfilePath?: string } = {},
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
    containers: readContainers(),
  }
}
