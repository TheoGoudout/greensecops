import * as core from "@actions/core"

/**
 * Top-level wrapper for an action step's async entrypoint: telemetry must
 * never fail the user's workflow, so any escaped error is logged and swallowed.
 */
export function runStep(name: string, fn: () => Promise<void>): void {
  fn().catch((err: unknown) => {
    core.warning(`GreenSecOps ${name} step error: ${String(err)}`)
  })
}

/** Log a telemetry ingest outcome (warning on failure, never an error). */
export function reportIngest(
  ok: boolean,
  successMessage: string,
  failureMessage: string,
): void {
  if (ok) {
    core.info(successMessage)
  } else {
    core.warning(failureMessage)
  }
}
