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

export function groupFixesByWorkflow(
  fixes: FixPublic[],
): Map<string, FixPublic[]> {
  const groups = new Map<string, FixPublic[]>()
  for (const fix of fixes) {
    const key = fix.workflow_file_path ?? ""
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(fix)
  }
  return groups
}

export const PAGE_SIZE = 20
