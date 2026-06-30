import type { FixPublic, IssuePublic } from "@/client"

export function workflowLabel(path: string): string {
  if (!path) return "Unknown workflow"
  return path.split("/").pop() ?? path
}

export function groupByWorkflowFile(
  issues: IssuePublic[],
): Map<string, IssuePublic[]> {
  const groups = new Map<string, IssuePublic[]>()
  for (const issue of issues) {
    const key = issue.workflow_file_path ?? ""
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(issue)
  }
  return groups
}

export function extractFilePath(patch: string): string {
  const gitMatch = patch.match(/^diff --git a\/(.+?) b\/.+$/m)
  if (gitMatch) return gitMatch[1]
  const unifiedMatch = patch.match(/^--- a\/(.+)$/m)
  return unifiedMatch?.[1] ?? ""
}

export function combinePatchesForFile(patches: string[]): string {
  if (patches.length === 0) return ""
  const validPatches = patches.filter(
    (p) => p.includes("@@") || p.startsWith("---"),
  )
  if (validPatches.length === 0) return ""
  const unique = [...new Set(validPatches)]
  if (unique.length === 1) return unique[0]
  const hunkStart = unique[0].indexOf("@@")
  const header = hunkStart !== -1 ? unique[0].slice(0, hunkStart) : unique[0]
  const hunks = unique
    .map((p) => {
      const start = p.indexOf("@@")
      return start !== -1 ? p.slice(start) : ""
    })
    .filter(Boolean)
    .join("\n")
  return header + hunks
}

export function groupFixesByWorkflow(
  fixes: FixPublic[],
  issueById?: Map<string, IssuePublic>,
): Map<string, FixPublic[]> {
  const groups = new Map<string, FixPublic[]>()
  for (const fix of fixes) {
    const key =
      fix.workflow_file_path ??
      issueById?.get(fix.issue_id)?.workflow_file_path ??
      ""
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(fix)
  }
  return groups
}

export const PAGE_SIZE = 20
