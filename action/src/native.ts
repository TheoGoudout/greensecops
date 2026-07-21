import * as childProcess from "node:child_process"
import * as path from "node:path"
import type { TopProcess } from "./types"

const ARCH_MAP: Record<string, string> = {
  x64: "amd64",
  arm64: "arm64",
  ia32: "386",
}

const EXEC_TIMEOUT_MS = 2000

function resolveBinaryPath(): string | null {
  if (process.platform !== "linux") return null
  const goArch = ARCH_MAP[process.arch]
  if (!goArch) return null
  // dist/bin/ sits alongside dist/pre, dist/main, dist/post — a sibling of
  // this bundled file's own directory (dist/main/index.js at runtime).
  return path.join(__dirname, "..", "bin", `proc-sampler-linux-${goArch}`)
}

/** Per-process CPU/RAM snapshot from the proc-sampler binary, or null if
 * unavailable (wrong platform/arch, binary missing, or it failed) — never
 * throws, matching the rest of this module's "not fatal" telemetry style. */
export function getTopProcesses(): TopProcess[] | null {
  const binPath = resolveBinaryPath()
  if (!binPath) return null

  try {
    const output = childProcess.execFileSync(binPath, [], {
      encoding: "utf8",
      timeout: EXEC_TIMEOUT_MS,
    })
    const parsed = JSON.parse(output)
    return Array.isArray(parsed) ? (parsed as TopProcess[]) : null
  } catch {
    return null
  }
}
