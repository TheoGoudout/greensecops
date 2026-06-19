import * as fs from "node:fs"
import type { ActionState } from "./types"

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
