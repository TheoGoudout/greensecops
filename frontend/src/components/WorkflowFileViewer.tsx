import { diffLines } from "diff"
import Prism from "prismjs"
import "prismjs/components/prism-yaml"
import { useMemo, useState } from "react"
import type { FixPublic, IssuePublic, IssueSeverity } from "@/client"
import { SeverityChip } from "@/components/SeverityChip"

type FlatToken = { type: string; text: string }

const YAML_TOKEN_COLORS: Record<string, string> = {
  comment: "text-slate-400 dark:text-slate-500 italic",
  key: "text-sky-600 dark:text-sky-400",
  string: "text-emerald-600 dark:text-emerald-400",
  scalar: "text-emerald-600 dark:text-emerald-400",
  number: "text-amber-600 dark:text-amber-400",
  datetime: "text-amber-600 dark:text-amber-400",
  boolean: "text-violet-600 dark:text-violet-400",
  null: "text-violet-400 dark:text-violet-300",
  tag: "text-pink-600 dark:text-pink-400",
  important: "text-orange-600 dark:text-orange-400",
  directive: "text-orange-600 dark:text-orange-400",
  punctuation: "text-slate-400 dark:text-slate-500",
}

function extractText(content: Prism.Token["content"]): string {
  if (typeof content === "string") return content
  if (Array.isArray(content))
    return (content as (Prism.Token | string)[])
      .map((t) => (typeof t === "string" ? t : extractText(t.content)))
      .join("")
  return extractText((content as Prism.Token).content)
}

function tokenizeYamlLine(line: string): FlatToken[] {
  if (!line) return [{ type: "plain", text: "" }]
  try {
    const stream = Prism.tokenize(line, Prism.languages.yaml)
    return stream.map((t) =>
      typeof t === "string"
        ? { type: "plain", text: t }
        : { type: t.type, text: extractText(t.content) },
    )
  } catch {
    return [{ type: "plain", text: line }]
  }
}

interface WorkflowFileViewerProps {
  path: string
  rawContent: string
  fullContent?: string
  issues: IssuePublic[]
  fix?: FixPublic
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

export function buildDiffEntries(
  rawContent: string,
  fullContent?: string,
): LineEntry[] {
  const currentText = fullContent ?? rawContent

  const changes = diffLines(rawContent, currentText)
  const entries: LineEntry[] = []
  let origLineNum = 1
  let key = 0

  for (const change of changes) {
    const lines = change.value.split("\n")
    if (lines[lines.length - 1] === "") lines.pop()
    for (const text of lines) {
      if (change.removed) {
        entries.push({
          key: key++,
          lineNum: origLineNum++,
          text,
          type: "remove",
        })
      } else if (change.added) {
        entries.push({ key: key++, lineNum: null, text, type: "add" })
      } else {
        entries.push({
          key: key++,
          lineNum: origLineNum++,
          text,
          type: "normal",
        })
      }
    }
  }

  return entries
}

type Segment =
  | { kind: "lines"; start: number; end: number }
  | { kind: "collapsed"; start: number; end: number }

export function WorkflowFileViewer({
  path,
  rawContent,
  fullContent,
  issues,
  fix,
}: WorkflowFileViewerProps) {
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set())

  const displayLines = useMemo(
    () => buildDiffEntries(rawContent, fullContent ?? undefined),
    [rawContent, fullContent],
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

  const fixedIssueIds = useMemo(() => {
    if (!fix || (fix.status !== "ready" && fix.status !== "delivered")) {
      return new Set<string>()
    }
    return new Set((fix.issues ?? []).map((i) => i.id))
  }, [fix])

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
                    fixedIssueIds={fixedIssueIds}
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
                fixedIssueIds={fixedIssueIds}
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
  fixedIssueIds,
}: {
  line: LineEntry
  issues: IssuePublic[]
  fixedIssueIds: Set<string>
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
      {issues.map((issue) => (
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
          {fixedIssueIds.has(issue.id) && (
            <span className="text-xs text-green-600 dark:text-green-400 shrink-0">
              fix applied ↓
            </span>
          )}
        </div>
      ))}

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
          {tokenizeYamlLine(line.text).map((token, i) => (
            <span key={i} className={YAML_TOKEN_COLORS[token.type] ?? ""}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </>
  )
}
