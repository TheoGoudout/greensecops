import { useMemo, useState } from "react"
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

interface LineEntry {
  key: number
  lineNum: number | null
  text: string
  type: "normal" | "remove" | "add"
}

type PatchLine = { prefix: "+" | "-" | " "; text: string }
type Hunk = { oldStart: number; lines: PatchLine[] }

function parsePatch(patch: string): Hunk[] {
  const hunks: Hunk[] = []
  let cur: Hunk | null = null
  for (const line of patch.split("\n")) {
    const m = line.match(/^@@ -(\d+)(?:,\d+)? /)
    if (m) {
      if (cur) hunks.push(cur)
      cur = { oldStart: Number(m[1]), lines: [] }
    } else if (cur && line.length > 0 && " +-".includes(line[0])) {
      cur.lines.push({
        prefix: line[0] as PatchLine["prefix"],
        text: line.slice(1),
      })
    }
  }
  if (cur) hunks.push(cur)
  return hunks
}

function applyPatches(
  originalLines: string[],
  fixes: FixPublic[],
): LineEntry[] {
  let entries: LineEntry[] = originalLines.map((text, i) => ({
    key: i,
    lineNum: i + 1,
    text,
    type: "normal" as const,
  }))

  let nextKey = originalLines.length

  for (const fix of fixes) {
    if (!fix.diff_patch) continue
    const hunks = parsePatch(fix.diff_patch)
    const next: LineEntry[] = []
    let i = 0

    for (const hunk of hunks) {
      const startI = entries.findIndex(
        (e, j) => j >= i && e.lineNum === hunk.oldStart,
      )
      if (startI === -1) continue

      next.push(...entries.slice(i, startI))
      i = startI

      const addBuf: LineEntry[] = []
      for (const { prefix, text } of hunk.lines) {
        if (prefix === " ") {
          next.push(...addBuf)
          addBuf.length = 0
          next.push(entries[i++])
        } else if (prefix === "-") {
          next.push(...addBuf)
          addBuf.length = 0
          next.push({ ...entries[i], type: "remove" })
          i++
        } else {
          addBuf.push({ key: nextKey++, lineNum: null, text, type: "add" })
        }
      }
      next.push(...addBuf)
    }
    next.push(...entries.slice(i))
    entries = next
  }

  return entries
}

type Segment =
  | { kind: "lines"; start: number; end: number }
  | { kind: "collapsed"; start: number; end: number }

export function WorkflowFileViewer({
  path,
  rawContent,
  issues,
  fixes,
}: WorkflowFileViewerProps) {
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set())

  const originalLines = useMemo(() => rawContent.split("\n"), [rawContent])
  const readyFixes = useMemo(
    () => fixes.filter((f) => f.status === "ready" && f.diff_patch),
    [fixes],
  )
  const displayLines = useMemo(
    () => applyPatches(originalLines, readyFixes),
    [originalLines, readyFixes],
  )

  const issuesByOrigLine = useMemo(() => {
    const map = new Map<number, IssuePublic[]>()
    for (const issue of issues) {
      if (issue.line_start != null) {
        const list = map.get(issue.line_start) ?? []
        list.push(issue)
        map.set(issue.line_start, list)
      }
    }
    return map
  }, [issues])

  const issuesWithoutLine = useMemo(
    () => issues.filter((i) => i.line_start == null),
    [issues],
  )

  const fixByIssueId = useMemo(() => {
    const map = new Map<string, FixPublic>()
    for (const fix of fixes) map.set(fix.issue_id, fix)
    return map
  }, [fixes])

  const interestingSet = useMemo(() => {
    const set = new Set<number>()
    displayLines.forEach((line, i) => {
      if (line.type !== "normal") set.add(i)
    })
    displayLines.forEach((line, i) => {
      if (line.lineNum != null && issuesByOrigLine.has(line.lineNum)) {
        for (
          let j = Math.max(0, i - CONTEXT_LINES);
          j <= Math.min(displayLines.length - 1, i + CONTEXT_LINES);
          j++
        ) {
          set.add(j)
        }
      }
    })
    return set
  }, [displayLines, issuesByOrigLine])

  const segments = useMemo((): Segment[] => {
    if (displayLines.length === 0) return []
    // Show full file when nothing is interesting (no issues with line numbers, no patches)
    if (interestingSet.size === 0) {
      return [{ kind: "lines", start: 0, end: displayLines.length - 1 }]
    }
    const segs: Segment[] = []
    let i = 0
    while (i < displayLines.length) {
      if (interestingSet.has(i)) {
        const start = i
        while (i < displayLines.length && interestingSet.has(i)) i++
        segs.push({ kind: "lines", start, end: i - 1 })
      } else {
        const start = i
        while (i < displayLines.length && !interestingSet.has(i)) i++
        segs.push({ kind: "collapsed", start, end: i - 1 })
      }
    }
    return segs
  }, [displayLines, interestingSet])

  const toggleBlock = (key: string) =>
    setExpandedBlocks((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  return (
    <div className="rounded-lg border bg-muted/30">
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/50 rounded-t-lg">
        <span className="text-xs font-mono text-muted-foreground">{path}</span>
        {issues.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {issues.length} issue{issues.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

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

      <div className="font-mono text-xs overflow-x-auto">
        {segments.map((seg) => {
          if (seg.kind === "collapsed") {
            const count = seg.end - seg.start + 1
            const key = `collapsed-${seg.start}-${seg.end}`
            if (expandedBlocks.has(key)) {
              return displayLines
                .slice(seg.start, seg.end + 1)
                .map((line) => (
                  <LineRow
                    key={line.key}
                    line={line}
                    issues={[]}
                    fixByIssueId={fixByIssueId}
                  />
                ))
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

          return displayLines.slice(seg.start, seg.end + 1).map((line) => {
            const lineIssues =
              line.lineNum != null
                ? (issuesByOrigLine.get(line.lineNum) ?? [])
                : []
            return (
              <LineRow
                key={line.key}
                line={line}
                issues={lineIssues}
                fixByIssueId={fixByIssueId}
              />
            )
          })
        })}
      </div>
    </div>
  )
}

function LineRow({
  line,
  issues,
  fixByIssueId,
}: {
  line: LineEntry
  issues: IssuePublic[]
  fixByIssueId: Map<string, FixPublic>
}) {
  const topSeverity = issues[0]?.severity ?? null
  const lineClass =
    line.type === "add"
      ? "bg-green-50 dark:bg-green-950/30"
      : line.type === "remove"
        ? "bg-red-50 dark:bg-red-950/30"
        : ""
  const prefix = line.type === "add" ? "+" : line.type === "remove" ? "-" : " "

  return (
    <>
      <div
        className={`flex border-l-2 ${topSeverity ? SEVERITY_BORDER[topSeverity] : "border-l-transparent"} ${lineClass}`}
      >
        <span className="w-10 shrink-0 select-none text-right pr-3 text-muted-foreground/50 border-r border-border py-0.5">
          {line.lineNum ?? ""}
        </span>
        <span className="w-4 shrink-0 select-none text-center py-0.5 text-muted-foreground/70">
          {prefix !== " " ? prefix : ""}
        </span>
        <span
          className={`pl-2 py-0.5 whitespace-pre flex-1 ${line.type === "remove" ? "line-through opacity-60" : ""}`}
        >
          {line.text}
        </span>
      </div>

      {issues.map((issue) => {
        const fix = fixByIssueId.get(issue.id)
        return (
          <div
            key={issue.id}
            className={`border-l-2 ${SEVERITY_BORDER[issue.severity]} bg-muted/40 flex items-start gap-2 px-4 py-2`}
          >
            <SeverityChip severity={issue.severity} />
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 shrink-0">
              {issue.rule_slug}
            </span>
            <span className="text-xs text-foreground flex-1">
              {issue.message}
            </span>
            {fix?.status === "ready" && (
              <span className="text-xs text-green-600 dark:text-green-400 shrink-0">
                fix applied ↑
              </span>
            )}
          </div>
        )
      })}
    </>
  )
}
