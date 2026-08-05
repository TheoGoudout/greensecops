import { diffLines } from "diff"
import Prism from "prismjs"
import "prismjs/components/prism-yaml"
import "prismjs/components/prism-hcl"
import "prismjs/components/prism-docker"
import type { FixPublic, IssueSeverity } from "@/client"

/**
 * The mechanics behind {@link FileViewer}: turning a file (optionally with a
 * proposed rewrite) into annotated, collapsible, syntax-highlighted lines.
 *
 * Kept apart from the component so the pure functions can be unit tested
 * without rendering, and so the four engines' viewers cannot drift.
 */

/** How many unchanged lines to keep either side of an annotated one. */
export const CONTEXT_LINES = 5

export const SEVERITY_BORDER: Record<IssueSeverity, string> = {
  critical: "border-l-red-500",
  high: "border-l-orange-500",
  medium: "border-l-yellow-500",
  low: "border-l-blue-400",
  info: "border-l-muted-foreground",
}

/**
 * The Prism grammars a file can be highlighted with. Supplied by the caller —
 * for Docker targets it comes from the API's `kind`, so the frontend never
 * re-derives a language from a filename.
 */
export type Grammar = "yaml" | "hcl" | "dockerfile" | "compose"

const GRAMMARS: Record<Grammar, Prism.Grammar> = {
  yaml: Prism.languages.yaml,
  hcl: Prism.languages.hcl,
  dockerfile: Prism.languages.docker,
  compose: Prism.languages.yaml,
}

/**
 * One colour map across every grammar rather than one per language: the token
 * *types* overlap almost entirely (comment, string, number, punctuation), and
 * three near-identical maps would drift. A grammar that emits a type absent
 * here simply renders unstyled.
 */
const TOKEN_COLORS: Record<string, string> = {
  comment: "text-slate-400 dark:text-slate-500 italic",
  keyword: "text-violet-600 dark:text-violet-400",
  instruction: "text-violet-600 dark:text-violet-400",
  directive: "text-violet-600 dark:text-violet-400",
  "directive-block": "text-violet-600 dark:text-violet-400",
  boolean: "text-violet-600 dark:text-violet-400",
  null: "text-violet-400 dark:text-violet-300",
  key: "text-sky-600 dark:text-sky-400",
  atrule: "text-sky-600 dark:text-sky-400",
  property: "text-sky-600 dark:text-sky-400",
  string: "text-emerald-600 dark:text-emerald-400",
  scalar: "text-emerald-600 dark:text-emerald-400",
  number: "text-amber-600 dark:text-amber-400",
  datetime: "text-amber-600 dark:text-amber-400",
  function: "text-orange-600 dark:text-orange-400",
  important: "text-orange-600 dark:text-orange-400",
  variable: "text-pink-600 dark:text-pink-400",
  interpolation: "text-pink-600 dark:text-pink-400",
  "interpolation-punctuation": "text-pink-600 dark:text-pink-400",
  anchor: "text-pink-600 dark:text-pink-400",
  tag: "text-pink-600 dark:text-pink-400",
  punctuation: "text-slate-400 dark:text-slate-500",
  operator: "text-slate-400 dark:text-slate-500",
}

export type FlatToken = { type: string; text: string; className: string }

function extractText(content: Prism.Token["content"]): string {
  if (typeof content === "string") return content
  if (Array.isArray(content))
    return (content as (Prism.Token | string)[])
      .map((t) => (typeof t === "string" ? t : extractText(t.content)))
      .join("")
  return extractText((content as Prism.Token).content)
}

export function tokenizeLine(line: string, grammar: Grammar): FlatToken[] {
  const plain = (text: string): FlatToken[] => [
    { type: "plain", text, className: "" },
  ]
  if (!line) return plain("")
  try {
    return Prism.tokenize(line, GRAMMARS[grammar]).map((t) => {
      const type = typeof t === "string" ? "plain" : t.type
      return {
        type,
        text: typeof t === "string" ? t : extractText(t.content),
        className: TOKEN_COLORS[type] ?? "",
      }
    })
  } catch {
    // Tokenizing one line out of context can trip a multi-line grammar rule;
    // rendering it unhighlighted is strictly better than losing the file.
    return plain(line)
  }
}

export interface LineEntry {
  key: number
  /** 1-based line in the *original* file; null for an added line. */
  lineNum: number | null
  text: string
  type: "normal" | "remove" | "add"
}

/**
 * Lines to render for a file, as a diff against its proposed rewrite.
 *
 * With no `fullContent` this is just the file's own lines. With one, removed
 * lines keep their original numbering so an annotation still lands on the line
 * it was reported against.
 */
export function buildDiffEntries(
  rawContent: string,
  fullContent?: string,
): LineEntry[] {
  const entries: LineEntry[] = []
  let origLineNum = 1
  let key = 0

  for (const change of diffLines(rawContent, fullContent ?? rawContent)) {
    const lines = change.value.split("\n")
    if (lines[lines.length - 1] === "") lines.pop()
    for (const text of lines) {
      if (change.added) {
        entries.push({ key: key++, lineNum: null, text, type: "add" })
      } else {
        entries.push({
          key: key++,
          lineNum: origLineNum++,
          text,
          type: change.removed ? "remove" : "normal",
        })
      }
    }
  }
  return entries
}

export type Segment =
  | { kind: "lines"; start: number; end: number }
  | { kind: "collapsed"; start: number; end: number }

/**
 * Split the file into runs worth showing and runs worth folding away.
 *
 * A line is worth showing when it changed, or sits within {@link CONTEXT_LINES}
 * of an annotated line. A file with nothing interesting is shown whole rather
 * than collapsed to nothing.
 */
export function computeSegments(
  lines: LineEntry[],
  annotatedLineNumbers: Set<number>,
): Segment[] {
  if (lines.length === 0) return []

  const interesting = new Set<number>()
  lines.forEach((line, i) => {
    if (line.type !== "normal") interesting.add(i)
    if (line.lineNum != null && annotatedLineNumbers.has(line.lineNum)) {
      const from = Math.max(0, i - CONTEXT_LINES)
      const to = Math.min(lines.length - 1, i + CONTEXT_LINES)
      for (let j = from; j <= to; j++) interesting.add(j)
    }
  })
  if (interesting.size === 0) {
    return [{ kind: "lines", start: 0, end: lines.length - 1 }]
  }

  const segments: Segment[] = []
  let i = 0
  while (i < lines.length) {
    const start = i
    const wanted = interesting.has(i)
    while (i < lines.length && interesting.has(i) === wanted) i++
    segments.push({ kind: wanted ? "lines" : "collapsed", start, end: i - 1 })
  }
  return segments
}

/**
 * The issues a fix claims to resolve, for badging them in the viewer.
 *
 * Only a fix that actually produced content counts: a pending or failed fix
 * has resolved nothing yet, and badging its issues would promise a change the
 * diff below does not contain.
 */
export function resolvedIssueIds(fix?: FixPublic | null): Set<string> {
  if (!fix || (fix.status !== "ready" && fix.status !== "delivered")) {
    return new Set<string>()
  }
  return new Set((fix.issues ?? []).map((issue) => issue.id))
}
