import * as childProcess from "node:child_process"

const EXEC_TIMEOUT_MS = 10_000
const MAX_BUFFER = 8 * 1024 * 1024

/**
 * Run a command and return its stdout, or null on any failure.
 *
 * Shared by every Docker probe. Returning null rather than throwing is the
 * whole contract: a runner without Docker, or with a Docker that answers
 * differently, must never fail the user's build over telemetry.
 */
export function run(cmd: string, args: string[]): string | null {
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
