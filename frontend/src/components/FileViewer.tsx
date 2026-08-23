import { useMemo, useState } from "react"
import type { Severity } from "@/client"
import { RuleSlugChip } from "@/components/RuleSlugChip"
import { SeverityChip } from "@/components/SeverityChip"
import {
  buildDiffEntries,
  computeSegments,
  type Grammar,
  type LineEntry,
  SEVERITY_BORDER,
  tokenizeLine,
} from "@/lib/file-viewer"

/**
 * What every engine reports against a line of a file: an issue from the CI
 * workflow engine, a finding from Terraform, Docker or cloud. Structural
 * typing means IssuePublic and the three *FindingPublic types all satisfy it.
 */
export interface Annotation {
  id: string
  severity: Severity
  rule_slug: string
  message: string
  line_start?: number | null
}

interface FileViewerProps {
  path: string
  rawContent: string
  /** Which syntax grammar to highlight with. */
  grammar: Grammar
  /** When a fix is ready or delivered, its patched content — shown as a diff. */
  fullContent?: string
  annotations: Annotation[]
  /** What one annotation is called here, for the header count. */
  noun?: string
  /** Heading for annotations that name no line at all. */
  fileLevelLabel?: string
  /**
   * Annotations the pending fix claims to resolve, badged so a reader can see
   * which of the issues above the diff it actually addresses. Only the CI
   * workflow engine has this; the others pass nothing.
   */
  resolvedIds?: Set<string>
}

/**
 * A file with its violations annotated inline, and its proposed fix as a diff.
 *
 * One component for all four engines. They differ only in the grammar, what
 * they call a violation, and whether a fix can claim to resolve one — every
 * other aspect (diffing, collapsing uninteresting runs, severity gutters,
 * file-level annotations) was previously duplicated three times over.
 */
export function FileViewer({
  path,
  rawContent,
  grammar,
  fullContent,
  annotations,
  noun = "finding",
  fileLevelLabel = "File-level findings",
  resolvedIds,
}: FileViewerProps) {
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(new Set())

  const displayLines = useMemo(
    () => buildDiffEntries(rawContent, fullContent ?? undefined),
    [rawContent, fullContent],
  )

  const byLine = useMemo(() => {
    const map = new Map<number, Annotation[]>()
    for (const annotation of annotations) {
      if (annotation.line_start != null) {
        const list = map.get(annotation.line_start) ?? []
        list.push(annotation)
        map.set(annotation.line_start, list)
      }
    }
    return map
  }, [annotations])

  const withoutLine = useMemo(
    () => annotations.filter((a) => a.line_start == null),
    [annotations],
  )

  const segments = useMemo(
    () => computeSegments(displayLines, new Set(byLine.keys())),
    [displayLines, byLine],
  )

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
        {annotations.length > 0 && (
          <span className="text-xs text-muted-foreground shrink-0">
            {annotations.length} {noun}
            {annotations.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {withoutLine.length > 0 && (
        <div className="border-b px-4 py-2 flex flex-col gap-2">
          <p className="text-xs text-muted-foreground font-medium">
            {fileLevelLabel}
          </p>
          {withoutLine.map((annotation) => (
            <div
              key={annotation.id}
              className="flex flex-wrap items-start gap-x-2 gap-y-1 text-xs"
            >
              <SeverityChip
                severity={annotation.severity}
                className="shrink-0"
              />
              <span className="font-mono text-blue-700 dark:text-blue-300 shrink-0">
                {annotation.rule_slug}
              </span>
              <span className="text-foreground break-words">
                {annotation.message}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="font-mono text-xs overflow-x-auto">
        <div className="min-w-full w-max">
          {segments.map((seg) => {
            const key = `collapsed-${seg.start}-${seg.end}`
            const collapsed =
              seg.kind === "collapsed" && !expandedBlocks.has(key)
            if (collapsed) {
              const count = seg.end - seg.start + 1
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
            return displayLines
              .slice(seg.start, seg.end + 1)
              .map((line) => (
                <LineRow
                  key={line.key}
                  line={line}
                  grammar={grammar}
                  annotations={
                    seg.kind === "lines" && line.lineNum != null
                      ? (byLine.get(line.lineNum) ?? [])
                      : []
                  }
                  resolvedIds={resolvedIds}
                />
              ))
          })}
        </div>
      </div>
    </div>
  )
}

function LineRow({
  line,
  grammar,
  annotations,
  resolvedIds,
}: {
  line: LineEntry
  grammar: Grammar
  annotations: Annotation[]
  resolvedIds?: Set<string>
}) {
  const topSeverity = annotations[0]?.severity ?? null
  const lineClass =
    line.type === "add"
      ? "bg-green-50 dark:bg-green-950/30"
      : line.type === "remove"
        ? "bg-red-50 dark:bg-red-950/30"
        : ""
  const prefix = line.type === "add" ? "+" : line.type === "remove" ? "-" : " "

  return (
    <>
      {annotations.map((annotation) => (
        <div
          key={annotation.id}
          className={`border-l-2 ${SEVERITY_BORDER[annotation.severity]} bg-muted/40 flex flex-wrap items-start gap-x-2 gap-y-1 px-4 py-2`}
        >
          <SeverityChip severity={annotation.severity} className="shrink-0" />
          <RuleSlugChip className="shrink-0">
            {annotation.rule_slug}
          </RuleSlugChip>
          <span className="text-xs text-foreground break-words">
            {annotation.message}
          </span>
          {resolvedIds?.has(annotation.id) && (
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
          {tokenizeLine(line.text, grammar).map((token, i) => (
            <span key={i} className={token.className}>
              {token.text}
            </span>
          ))}
        </span>
      </div>
    </>
  )
}
