import Prism from "prismjs"
import "prismjs/components/prism-hcl"
import { useMemo, useState } from "react"
import type { IssueSeverity, TerraformFindingPublic } from "@/client"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import { buildDiffEntries } from "@/components/WorkflowFileViewer"

type FlatToken = { type: string; text: string }

const HCL_TOKEN_COLORS: Record<string, string> = {
  comment: "text-slate-400 dark:text-slate-500 italic",
  keyword: "text-violet-600 dark:text-violet-400",
  property: "text-sky-600 dark:text-sky-400",
  string: "text-emerald-600 dark:text-emerald-400",
  "interpolation-punctuation": "text-pink-600 dark:text-pink-400",
  interpolation: "text-pink-600 dark:text-pink-400",
  number: "text-amber-600 dark:text-amber-400",
  boolean: "text-violet-600 dark:text-violet-400",
  function: "text-orange-600 dark:text-orange-400",
  punctuation: "text-slate-400 dark:text-slate-500",
  operator: "text-slate-400 dark:text-slate-500",
}

function extractText(content: Prism.Token["content"]): string {
  if (typeof content === "string") return content
  if (Array.isArray(content))
    return (content as (Prism.Token | string)[])
      .map((t) => (typeof t === "string" ? t : extractText(t.content)))
      .join("")
  return extractText((content as Prism.Token).content)
}

function tokenizeHclLine(line: string): FlatToken[] {
  if (!line) return [{ type: "plain", text: "" }]
  try {
    const stream = Prism.tokenize(line, Prism.languages.hcl)
    return stream.map((t) =>
      typeof t === "string"
        ? { type: "plain", text: t }
        : { type: t.type, text: extractText(t.content) },
    )
  } catch {
    return [{ type: "plain", text: line }]
  }
}

const SEVERITY_BORDER: Record<IssueSeverity, string> = {
  critical: "border-l-red-500",
  high: "border-l-orange-500",
  medium: "border-l-yellow-500",
  low: "border-l-blue-400",
  info: "border-l-muted-foreground",
}

const CONTEXT_LINES = 5

type Segment =
  | { kind: "lines"; start: number; end: number }
  | { kind: "collapsed"; start: number; end: number }

interface TerraformFileViewerProps {
  path: string
  rawContent: string
  // When a fix is ready/delivered, its patched content — rendered as a diff.
  fullContent?: string
  findings: TerraformFindingPublic[]
}

export function TerraformFileViewer({
  path,
  rawContent,
  fullContent,
  findings,
}: TerraformFileViewerProps) {
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set())

  const displayLines = useMemo(
    () => buildDiffEntries(rawContent, fullContent ?? undefined),
    [rawContent, fullContent],
  )

  // Findings for this file only, keyed by their 1-based line.
  const findingsByLine = useMemo(() => {
    const map = new Map<number, TerraformFindingPublic[]>()
    for (const finding of findings) {
      if (finding.line_start != null) {
        const list = map.get(finding.line_start) ?? []
        list.push(finding)
        map.set(finding.line_start, list)
      }
    }
    return map
  }, [findings])

  const findingsWithoutLine = useMemo(
    () => findings.filter((f) => f.line_start == null),
    [findings],
  )

  const interestingSet = useMemo(() => {
    const set = new Set<number>()
    displayLines.forEach((line, i) => {
      if (line.type !== "normal") set.add(i)
    })
    displayLines.forEach((line, i) => {
      if (line.lineNum != null && findingsByLine.has(line.lineNum)) {
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
  }, [displayLines, findingsByLine])

  const segments = useMemo((): Segment[] => {
    if (displayLines.length === 0) return []
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
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2 border-b bg-muted/50 rounded-t-lg">
        <span className="text-xs font-mono text-muted-foreground break-all min-w-0">
          {path}
        </span>
        {findings.length > 0 && (
          <span className="text-xs text-muted-foreground shrink-0">
            {findings.length} finding{findings.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {findingsWithoutLine.length > 0 && (
        <div className="border-b px-4 py-2 flex flex-col gap-2">
          <p className="text-xs text-muted-foreground font-medium">
            File-level findings
          </p>
          {findingsWithoutLine.map((finding) => (
            <div
              key={finding.id}
              className="flex flex-wrap items-start gap-x-2 gap-y-1 text-xs"
            >
              <SeverityChip severity={finding.severity} className="shrink-0" />
              <span className="font-mono text-blue-700 dark:text-blue-300 shrink-0">
                {finding.rule_slug}
              </span>
              <span className="text-foreground break-words">
                {finding.message}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="font-mono text-xs overflow-x-auto">
        <div className="min-w-full w-max">
          {segments.map((seg) => {
            if (seg.kind === "collapsed") {
              const count = seg.end - seg.start + 1
              const key = `collapsed-${seg.start}-${seg.end}`
              if (expandedBlocks.has(key)) {
                return displayLines
                  .slice(seg.start, seg.end + 1)
                  .map((line) => (
                    <LineRow key={line.key} line={line} findings={[]} />
                  ))
              }
              return (
                <button
                  key={key}
                  type="button"
                  className="w-full text-left flex items-center gap-2 px-3 py-1.5 text-muted-foreground hover:bg-muted/50 transition-colors"
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
              const lineFindings =
                line.lineNum != null
                  ? (findingsByLine.get(line.lineNum) ?? [])
                  : []
              return (
                <LineRow key={line.key} line={line} findings={lineFindings} />
              )
            })
          })}
        </div>
      </div>
    </div>
  )
}

function LineRow({
  line,
  findings,
}: {
  line: ReturnType<typeof buildDiffEntries>[number]
  findings: TerraformFindingPublic[]
}) {
  const topSeverity = findings[0]?.severity ?? null
  const lineClass =
    line.type === "add"
      ? "bg-green-50 dark:bg-green-950/30"
      : line.type === "remove"
        ? "bg-red-50 dark:bg-red-950/30"
        : ""
  const prefix = line.type === "add" ? "+" : line.type === "remove" ? "-" : " "

  return (
    <>
      {findings.map((finding) => (
        <div
          key={finding.id}
          className={`border-l-2 ${SEVERITY_BORDER[finding.severity]} bg-muted/40 flex flex-wrap items-start gap-x-2 gap-y-1 px-4 py-2`}
        >
          <SeverityChip severity={finding.severity} className="shrink-0" />
          <RuleSlugChip className="shrink-0">{finding.rule_slug}</RuleSlugChip>
          <span className="text-xs text-foreground break-words">
            {finding.message}
          </span>
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
          {tokenizeHclLine(line.text).map((token, i) => (
            <span key={i} className={HCL_TOKEN_COLORS[token.type] ?? ""}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </>
  )
}
