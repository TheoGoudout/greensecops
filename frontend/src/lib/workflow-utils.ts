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

interface ParsedHunk {
  oldStart: number
  oldCount: number
  newCount: number
  context: string
  bodyLines: string[]
}

function parseHunkHeader(line: string): Omit<ParsedHunk, "bodyLines"> | null {
  const match = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/)
  if (!match) return null
  return {
    oldStart: parseInt(match[1], 10),
    oldCount: match[2] !== undefined ? parseInt(match[2], 10) : 1,
    newCount: match[4] !== undefined ? parseInt(match[4], 10) : 1,
    context: match[5] ?? "",
  }
}

function extractHunks(patch: string): ParsedHunk[] {
  const hunks: ParsedHunk[] = []
  let current: ParsedHunk | null = null
  for (const line of patch.split("\n")) {
    if (line.startsWith("@@")) {
      if (current) hunks.push(current)
      const parsed = parseHunkHeader(line)
      if (parsed) current = { ...parsed, bodyLines: [] }
    } else if (current) {
      current.bodyLines.push(line)
    }
  }
  if (current) hunks.push(current)
  return hunks
}

export function combinePatchesForFile(patches: string[]): string {
  if (patches.length === 0) return ""
  const validPatches = patches.filter(
    (p) => p.includes("@@") || p.startsWith("---"),
  )
  if (validPatches.length === 0) return ""
  const unique = [...new Set(validPatches)]
  if (unique.length === 1) return unique[0]

  const firstHunkIdx = unique[0].indexOf("@@")
  const header = firstHunkIdx !== -1 ? unique[0].slice(0, firstHunkIdx) : ""

  const allHunks = unique.flatMap(extractHunks)
  allHunks.sort((a, b) => a.oldStart - b.oldStart)

  let cumulativeDelta = 0
  const hunkStrings: string[] = []

  for (const hunk of allHunks) {
    const adjustedNewStart = hunk.oldStart + cumulativeDelta
    const oldCountStr = hunk.oldCount !== 1 ? `,${hunk.oldCount}` : ""
    const newCountStr = hunk.newCount !== 1 ? `,${hunk.newCount}` : ""
    const hunkHeader = `@@ -${hunk.oldStart}${oldCountStr} +${adjustedNewStart}${newCountStr} @@${hunk.context}`
    hunkStrings.push([hunkHeader, ...hunk.bodyLines].join("\n"))
    cumulativeDelta += hunk.newCount - hunk.oldCount
  }

  return header + hunkStrings.join("\n")
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
