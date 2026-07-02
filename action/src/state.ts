import * as fs from "node:fs"
import * as os from "node:os"
import * as path from "node:path"
import type { ActionState, GitHubContext } from "./types"

export const STATE_FILE = path.join(
  process.env.RUNNER_TEMP ?? os.tmpdir(),
  "greensecops-state.json",
)

export function getGitHubContext(): GitHubContext {
  return {
    workflowRunId: parseInt(process.env.GITHUB_RUN_ID ?? "0", 10),
    repository: process.env.GITHUB_REPOSITORY ?? "",
    branch: (process.env.GITHUB_REF ?? "").replace("refs/heads/", ""),
    commitSha: process.env.GITHUB_SHA ?? "",
    workflowName: process.env.GITHUB_WORKFLOW ?? "",
  }
}

export function loadState(stateFile: string): ActionState | null {
  try {
    return JSON.parse(fs.readFileSync(stateFile, "utf8")) as ActionState
  } catch {
    return null
  }
}

export function killDaemon(pid: number): void {
  if (!pid) return
  try {
    process.kill(pid, "SIGTERM")
  } catch {
    // process already exited — not fatal
  }
}
