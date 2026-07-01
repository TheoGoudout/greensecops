import { useState } from "react"
import type { FixPublic, IssuePublic, IssueSeverity } from "@/client"
import { SeverityChip } from "@/components/SeverityChip"

interface WorkflowFileViewerProps {
  path: string
  rawContent: string
  issues: IssuePublic[]
  fixes: FixPublic[]
}

const SEVERITY_BORDER: Record<IssueSeverity, string> = {
  critical: "border-l-red-500",
  high: "border-l-orange-500",
  medium: "border-l-yellow-500",
  low: "border-l-blue-400",
  info: "border-l-muted-foreground",
}

const CONTEXT_LINES = 5

function parseDiffHunks(
  patch: string,
): Array<{ type: "context" | "add" | "remove"; text: string }> {
  const lines = patch.split("\n")
  const result: Array<{ type: "context" | "add" | "remove"; text: string }> = []
  for (const line of lines) {
    if (
      line.startsWith("@@") ||
      line.startsWith("---") ||
      line.startsWith("+++")
    )
      continue
    if (line.startsWith("+")) result.push({ type: "add", text: line.slice(1) })
    else if (line.startsWith("-"))
      result.push({ type: "remove", text: line.slice(1) })
    else if (line.startsWith(" "))
      result.push({ type: "context", text: line.slice(1) })
  }
  return result
}

export function WorkflowFileViewer({
  path,
  rawContent,
  issues,
  fixes,
}: WorkflowFileViewerProps) {
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set())
  const [expandedIssues, setExpandedIssues] = useState<Set<string>>(new Set())

  const lines = rawContent.split("\n")

  // Build lookup maps
  const issuesByLine = new Map<number, IssuePublic[]>()
  const issuesWithoutLine: IssuePublic[] = []
  for (const issue of issues) {
    if (issue.line_start != null) {
      const lineIssues = issuesByLine.get(issue.line_start) ?? []
      lineIssues.push(issue)
      issuesByLine.set(issue.line_start, lineIssues)
    } else {
      issuesWithoutLine.push(issue)
    }
  }

  const fixByIssueId = new Map<string, FixPublic>()
  for (const fix of fixes) {
    if (fix.status === "ready" && fix.diff_patch) {
      fixByIssueId.set(fix.issue_id, fix)
    }
  }

  // Determine interesting lines (within CONTEXT_LINES of any annotated issue)
  const interestingLines = new Set<number>()
  for (const [lineNum] of issuesByLine) {
    for (
      let i = Math.max(1, lineNum - CONTEXT_LINES);
      i <= Math.min(lines.length, lineNum + CONTEXT_LINES);
      i++
    ) {
      interestingLines.add(i)
    }
  }

  // Build segments: runs of interesting vs collapsed
  type Segment =
    | { kind: "lines"; from: number; to: number }
    | { kind: "collapsed"; from: number; to: number }

  const segments: Segment[] = []
  let i = 1
  while (i <= lines.length) {
    if (interestingLines.has(i)) {
      const start = i
      while (i <= lines.length && interestingLines.has(i)) i++
      segments.push({ kind: "lines", from: start, to: i - 1 })
    } else {
      const start = i
      while (i <= lines.length && !interestingLines.has(i)) i++
      segments.push({ kind: "collapsed", from: start, to: i - 1 })
    }
  }

  const toggleBlock = (key: string) =>
    setExpandedBlocks((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  const toggleIssue = (id: string) =>
    setExpandedIssues((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  return (
    <div className="rounded-lg border bg-muted/30">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/50 rounded-t-lg">
        <span className="text-xs font-mono text-muted-foreground">{path}</span>
        {issues.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {issues.length} issue{issues.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Workflow-level issues (no line_start) */}
      {issuesWithoutLine.length > 0 && (
        <div className="border-b px-4 py-2 flex flex-col gap-1">
          <p className="text-xs text-muted-foreground font-medium mb-1">
            Workflow-level issues
          </p>
          {issuesWithoutLine.map((issue) => (
            <div key={issue.id} className="flex items-start gap-2 text-xs">
              <SeverityChip severity={issue.severity} />
              <span className="font-mono text-blue-700 dark:text-blue-300">
                {issue.rule_slug}
              </span>
              <span className="text-foreground">{issue.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* No issues at all and no raw content */}
      {issues.length === 0 && lines.length === 0 && (
        <div className="px-4 py-6 text-center text-xs text-muted-foreground">
          No content available.
        </div>
      )}

      {/* Code viewer */}
      <div className="font-mono text-xs overflow-x-auto">
        {segments.map((seg) => {
          if (seg.kind === "collapsed") {
            const count = seg.to - seg.from + 1
            const key = `collapsed-${seg.from}-${seg.to}`
            const isExpanded = expandedBlocks.has(key)
            if (isExpanded) {
              return Array.from({ length: count }, (_, idx) => {
                const lineNum = seg.from + idx
                return (
                  <div key={lineNum} className="flex">
                    <span className="w-10 shrink-0 select-none text-right pr-3 text-muted-foreground/50 border-r border-border py-0.5">
                      {lineNum}
                    </span>
                    <span className="pl-3 py-0.5 whitespace-pre">
                      {lines[lineNum - 1]}
                    </span>
                  </div>
                )
              })
            }
            return (
              <button
                key={key}
                type="button"
                className="w-full text-left flex items-center gap-2 px-3 py-0.5 text-muted-foreground hover:bg-muted/50 transition-colors"
                onClick={() => toggleBlock(key)}
              >
                <span className="w-10 shrink-0" />
                <span>
                  ··· {count} line{count !== 1 ? "s" : ""} ···
                </span>
              </button>
            )
          }

          // Render visible lines
          return Array.from({ length: seg.to - seg.from + 1 }, (_, idx) => {
            const lineNum = seg.from + idx
            const lineIssues = issuesByLine.get(lineNum) ?? []
            const hasIssue = lineIssues.length > 0
            const topSeverity = hasIssue ? lineIssues[0].severity : null

            return (
              <div key={lineNum}>
                <div
                  className={`flex border-l-2 ${topSeverity ? SEVERITY_BORDER[topSeverity] : "border-l-transparent"}`}
                >
                  <span className="w-10 shrink-0 select-none text-right pr-3 text-muted-foreground/50 border-r border-border py-0.5">
                    {lineNum}
                  </span>
                  <span className="pl-3 py-0.5 whitespace-pre flex-1">
                    {lines[lineNum - 1]}
                  </span>
                </div>

                {/* Inline issue annotations */}
                {lineIssues.map((issue) => {
                  const fix = fixByIssueId.get(issue.id)
                  const isExpanded = expandedIssues.has(issue.id)
                  const hunks = fix?.diff_patch
                    ? parseDiffHunks(fix.diff_patch)
                    : []

                  return (
                    <div
                      key={issue.id}
                      className={`border-l-2 ml-0 ${SEVERITY_BORDER[issue.severity]} bg-muted/40`}
                    >
                      <button
                        type="button"
                        className="w-full text-left flex items-start gap-2 px-4 py-2 hover:bg-muted/60 transition-colors"
                        onClick={() => toggleIssue(issue.id)}
                      >
                        <SeverityChip severity={issue.severity} />
                        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 shrink-0">
                          {issue.rule_slug}
                        </span>
                        <span className="text-xs text-foreground flex-1">
                          {issue.message}
                        </span>
                        {fix && (
                          <span className="text-xs text-green-600 dark:text-green-400 shrink-0">
                            fix available
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground shrink-0">
                          {isExpanded ? "▲" : "▼"}
                        </span>
                      </button>

                      {isExpanded && fix && hunks.length > 0 && (
                        <div className="mx-4 mb-2 rounded border overflow-hidden text-xs">
                          {hunks.map((hunk, hi) => (
                            <div
                              key={hi}
                              className={
                                hunk.type === "add"
                                  ? "bg-green-50 dark:bg-green-950/30 text-green-800 dark:text-green-300"
                                  : hunk.type === "remove"
                                    ? "bg-red-50 dark:bg-red-950/30 text-red-800 dark:text-red-300 line-through opacity-70"
                                    : "bg-transparent text-muted-foreground"
                              }
                            >
                              <span className="select-none pr-2 opacity-50">
                                {hunk.type === "add"
                                  ? "+"
                                  : hunk.type === "remove"
                                    ? "-"
                                    : " "}
                              </span>
                              <span className="whitespace-pre">
                                {hunk.text}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })
        })}
      </div>
    </div>
  )
}
